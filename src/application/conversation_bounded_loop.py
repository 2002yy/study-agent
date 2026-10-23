"""Opt-in bounded model/action loop; no production routing or publication."""

from __future__ import annotations

from contextlib import aclosing
from dataclasses import dataclass, replace
import math
import time
from typing import AsyncGenerator, Callable, Mapping

from src.application.conversation_action_dispatch import (
    ActionBudget,
    ActionEvent,
    ActionHandler,
    ActionInvocation,
    RefusalRecord,
    dispatch_conversation_action,
    forbidden_action,
    refusal_allows_reselection,
)
from src.application.conversation_answer_generator import BoundedAnswerGenerator
from src.application.conversation_answer_input import AnswerHandler, AnswerInput
from src.application.conversation_decision import (
    ConversationAction,
    DecisionContext,
)
from src.application.conversation_decision_runner import (
    DecisionAdmission,
    DecisionLimits,
    DecisionResult,
    DecisionTransport,
    decide_conversation_action,
)
from src.application.conversation_observation_followup import (
    tool_followup_context,
)
from src.application.conversation_observation_trail import (
    ObservationLimitError,
    ObservationTrail,
    decide_with_observation_trail,
    trail_extra_chars,
    with_observation_trail,
)
from src.application.conversation_refusal_state import (
    MAX_RESELECTIONS,
    RefusalState,
    refusal_extra_chars,
    refusal_followup_context,
    with_refusal_state,
)


@dataclass(frozen=True)
class _PaddedAdmission:
    """Charge the prompt for the messages appended after the decision context.

    The appended payloads are real input tokens. Leaving them out of the reservation would
    under-count every observation and every refusal, which is the kind of silent
    under-billing the ledger exists to prevent.
    """

    delegate: DecisionAdmission
    extra: int

    def reserve(self, request_id: str, prompt_chars: int, output_tokens: int) -> str:
        return self.delegate.reserve(request_id, prompt_chars + self.extra, output_tokens)


@dataclass(frozen=True)
class LoopLimits:
    max_decisions: int = 4
    timeout_seconds: float = 30.0
    action_timeout_seconds: float = 5.0
    decision: DecisionLimits = DecisionLimits()

    def __post_init__(self) -> None:
        if type(self.max_decisions) is not int or not 1 <= self.max_decisions <= 8:
            raise ValueError("invalid loop decision cap")
        for value, cap in (
            (self.timeout_seconds, 120),
            (self.action_timeout_seconds, 30),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 < value <= cap
            ):
                raise ValueError("invalid loop timeout")
        if not isinstance(self.decision, DecisionLimits):
            raise ValueError("invalid loop decision limits")


@dataclass(frozen=True)
class LoopStopped:
    reason: str
    decision_steps: int
    observations: int
    outcome_unknown: bool = False
    detail: str = ""


LoopEvent = DecisionResult | ActionEvent | LoopStopped


async def run_conversation_loop(
    context: DecisionContext,
    *,
    current_context: Callable[[], DecisionContext],
    transport: DecisionTransport,
    decision_budget: DecisionAdmission,
    action_budget: ActionBudget,
    handlers: Mapping[ConversationAction, ActionHandler],
    limits: LoopLimits = LoopLimits(),
    answer_handler: AnswerHandler | None = None,
    answer_generator: BoundedAnswerGenerator | None = None,
) -> AsyncGenerator[LoopEvent, None]:
    """Stream decisions/observations and one normal terminal event.

    Only successful tool observations can request another decision. All calls
    share the supplied budgets and total deadline, including consumer pauses.
    An optional trusted answer handler receives bounded accumulated inputs; it
    owns actual generation budgets and output/evidence validation. An optional
    bounded generator instead uses the loop's projected fresh snapshots; the two
    answer adapters are mutually exclusive.
    The host owns fresh snapshots and real tool consumption. Closing/cancelling
    stops this iterator; it does not assert rollback of admitted external work.
    """
    if answer_handler is not None and not callable(answer_handler):
        raise ValueError("invalid answer handler")
    if answer_generator is not None and (
        not isinstance(answer_generator, BoundedAnswerGenerator)
        or answer_handler is not None
    ):
        raise ValueError("invalid or conflicting answer generator")
    deadline = time.monotonic() + limits.timeout_seconds
    # Observations and refusals both move the decision identity, and they can interleave
    # (observe, then be refused, then observe again). Recording them as one ordered list is
    # what keeps `latest()` rebuilding the same identity chain the loop actually walked; two
    # separate lists would replay every frame before every refusal and break the chain.
    projection: list[tuple[str, object]] = []
    trail = ObservationTrail(context)
    refusal_state = RefusalState(context.request_id)
    reselections = 0
    steps = observations = 0

    def latest() -> DecisionContext:
        fresh = current_context()
        # Preserve an unrelated new intent instead of projecting an old identity
        # onto it; the downstream freshness check will reject that snapshot.
        if (
            fresh.request_id != context.request_id
            or fresh.user_message != context.user_message
            or fresh.history != context.history
        ):
            return fresh
        # Rebuild execution identities using the original research snapshot,
        # then restore the actual snapshot for every freshness/receipt check.
        # Otherwise a handler-owned STEER revision loses its projected identity
        # before dispatch can compare it with the exact completion receipt.
        actual_research = fresh.active_research
        fresh = replace(fresh, active_research=context.active_research)
        for kind, payload in projection:
            if kind == "observation":
                before, proposal, observation = payload  # type: ignore[misc]
                fresh = tool_followup_context(before, fresh, proposal, observation)
            else:
                before, index = payload  # type: ignore[misc]
                fresh = refusal_followup_context(before, fresh, index=index)
        return replace(fresh, active_research=actual_research)

    expected = context

    async def next_decision(remaining_seconds: float) -> DecisionResult:
        """Ask for the next proposal, appending exactly the state that exists.

        Kept in one place because the payoff is in what is *not* here: a refusal never
        reaches the observation trail. The two payloads are composed, each charged for its
        own characters, and the plain paths stay exactly as they were so the verified
        no-refusal behaviour is not re-derived through a new code path.
        """

        limits_for_call = replace(
            limits.decision,
            timeout_seconds=min(remaining_seconds, limits.decision.timeout_seconds),
        )
        if not refusal_state.records:
            if not trail.frames:
                return await decide_conversation_action(
                    expected,
                    transport=transport,
                    budget=decision_budget,
                    current_context=latest,
                    limits=limits_for_call,
                )
            return await decide_with_observation_trail(
                expected,
                trail,
                current_context=latest,
                transport=transport,
                budget=decision_budget,
                limits=limits_for_call,
            )
        wrapped = transport
        extra = 0
        if trail.frames:
            try:
                trail.validate_next_context(expected)
            except (TypeError, ValueError):
                return DecisionResult("invalid_observation_trail")
            wrapped = with_observation_trail(wrapped, trail)
            extra += trail_extra_chars(trail)
        wrapped = with_refusal_state(wrapped, refusal_state)
        extra += refusal_extra_chars(refusal_state)
        return await decide_conversation_action(
            expected,
            transport=wrapped,
            budget=_PaddedAdmission(decision_budget, extra),
            current_context=latest,
            limits=limits_for_call,
        )

    async def answer(invocation: ActionInvocation) -> str:
        # Dispatch owns admission, freshness, timeout and cancellation. Capture
        # the current completed trail before this answer is appended to it.
        value = AnswerInput(expected, invocation, trail)
        if answer_generator is not None:
            return await answer_generator.generate(value, current_context=latest)
        if answer_handler is None:
            raise ValueError("missing answer handler")
        return await answer_handler(value)

    selected_handlers = handlers
    if answer_handler is not None or answer_generator is not None:
        selected_handlers = {**handlers, ConversationAction.ANSWER: answer}
    decision = await next_decision(limits.timeout_seconds)
    while True:
        steps += 1
        yield decision
        if decision.status != "completed" or decision.proposal is None:
            yield LoopStopped(
                "decision_failed",
                steps,
                observations,
                decision.outcome_unknown,
                decision.status,
            )
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            yield LoopStopped("timeout", steps, observations)
            return
        proposal = decision.proposal
        # A refusal already told us this exact request is off the table. Stopping here costs
        # nothing; letting it reach dispatch would buy a tool slot back only to refuse again,
        # and would let "the model rephrased it" look like a new attempt at a denied tool.
        blocked = forbidden_action(
            list(refusal_state.records),
            action=proposal.action,
            tool=proposal.tool,
            focus=proposal.focus,
        )
        if blocked:
            yield LoopStopped(blocked, steps, observations, False, proposal.action)
            return
        refused: ActionEvent | None = None
        tool_observation: ActionEvent | None = None
        async with aclosing(
            dispatch_conversation_action(
                proposal,
                expected,
                current_context=latest,
                handlers=selected_handlers,
                budget=action_budget,
                timeout_seconds=min(remaining, limits.action_timeout_seconds),
            )
        ) as actions:
            async for event in actions:
                trail_error = ""
                if event.status == "observed":
                    observations += 1
                    if event.stage == ConversationAction.USE_TOOL:
                        tool_observation = event
                    if event.stage == ConversationAction.USE_TOOL or (
                        proposal.action == ConversationAction.ANSWER_THEN_RESEARCH
                        and event.stage == ConversationAction.ANSWER
                    ):
                        try:
                            trail = trail.append(expected, proposal, event)
                        except ObservationLimitError:
                            trail_error = "observation_limit"
                        except (TypeError, ValueError):
                            trail_error = "invalid_observation"
                yield event
                if trail_error:
                    yield LoopStopped(trail_error, steps, observations)
                    return
                if event.status == "refused":
                    # Stop draining: the adapter declined before any effect, so there is no
                    # observation to collect. Whether the turn continues is decided below,
                    # from the structured kind rather than from the reason text.
                    refused = event
                    break
                if event.status != "observed":
                    yield LoopStopped(
                        "action_failed",
                        steps,
                        observations,
                        event.outcome_unknown,
                        event.status,
                    )
                    return
        if refused is not None:
            # Whether the turn continues is decided here, from the structured kind. The
            # contract's six cases collapse to: some refusals are about *this request*
            # (argue again, differently), and some are about *the turn* (stop now).
            kind = refused.refusal_kind
            if not refusal_allows_reselection(kind):
                yield LoopStopped("tool_refused", steps, observations, False, kind)
                return
            if reselections >= MAX_RESELECTIONS:
                yield LoopStopped("refusal_limit", steps, observations, False, kind)
                return
            if steps >= limits.max_decisions:
                yield LoopStopped("decision_limit", steps, observations)
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                yield LoopStopped("timeout", steps, observations)
                return
            # Execution state, never evidence. This is the whole difference between
            # "we were refused" and "we searched and found nothing": the record goes to the
            # refusal payload and to nowhere else, so it cannot reach the trail or the
            # episode as a finding.
            refusal_state = refusal_state.append(
                RefusalRecord(
                    request_id=refused.request_id,
                    kind=kind,
                    reason=refused.refusal_reason,
                    tool=proposal.tool or "",
                    focus=proposal.focus,
                )
            )
            reselections += 1
            projection.append(("refusal", (expected, reselections)))
            # The identity chain grows with the refusal so a later answer (or a later
            # observation) derives from it. Nothing is added to the entries: the trail's
            # payload is still observations only.
            trail = trail.advance_refusal(reselections)
            try:
                expected = latest()
            except Exception:
                yield LoopStopped("context_unavailable", steps, observations)
                return
            decision = await next_decision(remaining)
            continue
        if tool_observation is None:
            reason = {
                ConversationAction.ANSWER: "answered",
                ConversationAction.CLARIFY: "clarification_required",
                ConversationAction.STEER: "steering_observed",
                ConversationAction.QUEUE: "queue_observed",
            }[proposal.action]
            yield LoopStopped(reason, steps, observations)
            return
        if steps >= limits.max_decisions:
            yield LoopStopped("decision_limit", steps, observations)
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            yield LoopStopped("timeout", steps, observations)
            return
        try:
            fresh = latest()
        except Exception:
            yield LoopStopped("context_unavailable", steps, observations)
            return
        if (
            fresh.request_id != expected.request_id
            or fresh.user_message != expected.user_message
            or fresh.history != expected.history
            or fresh.active_research != expected.active_research
        ):
            yield LoopStopped("stale_context", steps, observations)
            return
        try:
            projected = tool_followup_context(
                expected, fresh, proposal, tool_observation
            )
        except (TypeError, ValueError):
            yield LoopStopped("invalid_observation", steps, observations)
            return
        projection.append(("observation", (expected, proposal, tool_observation)))
        expected = projected
        decision = await next_decision(remaining)
