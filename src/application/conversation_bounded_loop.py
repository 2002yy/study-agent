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
    dispatch_conversation_action,
)
from src.application.conversation_decision import (
    ActionProposal,
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
    decide_after_tool_observation,
    tool_followup_context,
)


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
) -> AsyncGenerator[LoopEvent, None]:
    """Stream decisions/observations and one normal terminal event.

    Only successful tool observations can request another decision. All calls
    share the supplied budgets and total deadline, including consumer pauses.
    The host owns fresh snapshots and real tool consumption. Closing/cancelling
    stops this iterator; it does not assert rollback of admitted external work.
    """
    deadline = time.monotonic() + limits.timeout_seconds
    frames: list[tuple[DecisionContext, ActionProposal, ActionEvent]] = []
    steps = observations = 0

    def latest() -> DecisionContext:
        fresh = current_context()
        # Preserve an unrelated new intent instead of projecting an old identity
        # onto it; the downstream freshness check will reject that snapshot.
        if (
            fresh.request_id != context.request_id
            or fresh.user_message != context.user_message
            or fresh.history != context.history
            or fresh.active_research != context.active_research
        ):
            return fresh
        for before, proposal, observation in frames:
            fresh = tool_followup_context(before, fresh, proposal, observation)
        return fresh

    expected = context
    decision = await decide_conversation_action(
        expected,
        transport=transport,
        budget=decision_budget,
        current_context=latest,
        limits=replace(
            limits.decision,
            timeout_seconds=min(
                limits.decision.timeout_seconds, limits.timeout_seconds
            ),
        ),
    )
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
        tool_observation: ActionEvent | None = None
        async with aclosing(
            dispatch_conversation_action(
                proposal,
                expected,
                current_context=latest,
                handlers=handlers,
                budget=action_budget,
                timeout_seconds=min(remaining, limits.action_timeout_seconds),
            )
        ) as actions:
            async for event in actions:
                if event.status == "observed":
                    observations += 1
                    if event.stage == ConversationAction.USE_TOOL:
                        tool_observation = event
                yield event
                if event.status != "observed":
                    yield LoopStopped(
                        "action_failed",
                        steps,
                        observations,
                        event.outcome_unknown,
                        event.status,
                    )
                    return
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
        decision = await decide_after_tool_observation(
            expected,
            proposal,
            tool_observation,
            current_context=latest,
            transport=transport,
            budget=decision_budget,
            limits=replace(
                limits.decision,
                timeout_seconds=min(remaining, limits.decision.timeout_seconds),
            ),
        )
        frames.append((expected, proposal, tool_observation))
        expected = projected
