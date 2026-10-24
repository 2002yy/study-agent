"""Opt-in action handlers and observations; no production tool/publication wiring.

Handlers are trusted server adapters, not model-provided code. They own argument
validation, durable execution identity and any paid-call/permission checks. The
local budget prevents duplicate dispatch within one live executor only.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
import math
import threading
import time
from typing import AsyncGenerator, Awaitable, Callable, Mapping, cast

from src.application.conversation_decision import (
    ActionProposal,
    ActiveResearch,
    ConversationAction,
    DecisionContext,
    validate_proposal,
)
from src.web.action_window import MAX_ACTION_SECONDS, ActionTimePolicy


@dataclass(frozen=True)
class ActionInvocation:
    proposal: ActionProposal
    stage: ConversationAction


@dataclass(frozen=True)
class ActionEvent:
    request_id: str
    status: str
    stage: ConversationAction | None = None
    observation: str = ""
    outcome_unknown: bool = False
    attempted: bool = False
    # Only set on ``refused``. The loop decides whether a reselection is safe from the
    # kind, not from the adapter's prose, so the classification is structured rather than
    # parsed. The reason is carried for receipts and for the model, never for control flow.
    refusal_kind: str = ""
    refusal_reason: str = ""


class RefusalKind(StrEnum):
    """Why an adapter declined, and what may follow.

    The distinction that matters is *not* severity - it is what the refusal tells us about
    the world. A tool that does not exist and a permission that is missing both mean "this
    exact call is off the table", while bad arguments mean "this call was wrong". A budget
    exhaustion says nothing about the tool at all, only that nothing new may be started.
    """

    TOOL_UNAVAILABLE = "tool_unavailable"
    ARGUMENTS_REJECTED = "arguments_rejected"
    PERMISSION_DENIED = "permission_denied"
    TOOL_BUDGET_EXHAUSTED = "tool_budget_exhausted"
    CANCELLED = "cancelled"
    STALE_CONTEXT = "stale_context"
    OUTCOME_UNKNOWN = "outcome_unknown"


# A refusal may be followed by one more decision unless the refusal says the turn itself is
# over. Cancellation and staleness end it because the user's intent is gone; an unknown
# outcome ends it because retrying could execute twice.
_RECOVERABLE = frozenset(
    {
        RefusalKind.TOOL_UNAVAILABLE,
        RefusalKind.ARGUMENTS_REJECTED,
        RefusalKind.PERMISSION_DENIED,
        RefusalKind.TOOL_BUDGET_EXHAUSTED,
    }
)

# These refuse the *tool*, not the arguments: proposing it again with different wording is
# an attempt to get around a permission, so it is stopped rather than re-run.
_TOOL_FORBIDDEN = frozenset(
    {RefusalKind.TOOL_UNAVAILABLE, RefusalKind.PERMISSION_DENIED}
)

# These refuse anything that would need a slice of the exhausted budget.
_BUDGET_BLOCKING_ACTIONS = frozenset(
    {ConversationAction.USE_TOOL, ConversationAction.ANSWER_THEN_RESEARCH}
)


@dataclass(frozen=True)
class ActionRefusal:
    """A trusted adapter declining to execute, before any external effect.

    This is not an error. The adapter checked a permission the dispatcher cannot check
    itself (Q-11's tool name comes from the model) and stopped. Recording it as
    ``handler_error`` would claim the outcome is unknown when nothing was attempted, and
    would charge the action for a call that provably did not happen.
    """

    reason: str
    kind: RefusalKind = RefusalKind.TOOL_UNAVAILABLE

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("invalid_refusal_reason")
        if not isinstance(self.kind, RefusalKind):
            raise ValueError("invalid_refusal_kind")


def refusal_allows_reselection(kind: str) -> bool:
    """Whether another decision may follow this refusal at all."""

    try:
        return RefusalKind(kind) in _RECOVERABLE
    except ValueError:
        return False


@dataclass(frozen=True)
class SteeringObservation:
    """Trusted adapter receipt, captured by the handler's own state update.

    The adapter must return the exact research snapshot it committed, not read
    an unrelated latest revision after committing. This is not an applied or
    evidence receipt for the production research system.
    """

    observation: str
    research_after: ActiveResearch


@dataclass(frozen=True)
class RefusalRecord:
    """A trusted record of what was refused, kept outside observations and evidence.

    The ``tool`` and ``focus`` are kept so a later proposal can be compared against it
    without re-running the adapter. Nothing here is a search result: a refusal says what
    did not happen, so it can never become a research finding.
    """

    request_id: str
    kind: str
    reason: str
    tool: str
    focus: str

    def __post_init__(self) -> None:
        for name in ("request_id", "kind", "reason", "tool", "focus"):
            if not isinstance(getattr(self, name), str):
                raise ValueError("invalid_refusal_record")


def forbidden_action(
    records: list[RefusalRecord],
    *,
    action: ConversationAction,
    tool: str | None,
    focus: str,
) -> str:
    """Why this proposal must not be dispatched, or ``""`` if it may be.

    Checked *before* dispatch, so a forbidden follow-up costs neither a model call nor an
    execution attempt. Without it a model could retry a permission-denied tool with
    reworded arguments and call that "fixing the parameters".
    """

    for record in records:
        if record.kind in _TOOL_FORBIDDEN:
            if action in _BUDGET_BLOCKING_ACTIONS and (tool or "") == record.tool:
                return "refused_tool_repeated"
        elif record.kind == RefusalKind.ARGUMENTS_REJECTED:
            if (
                action in _BUDGET_BLOCKING_ACTIONS
                and (tool or "") == record.tool
                and focus == record.focus
            ):
                return "refused_request_repeated"
        elif record.kind == RefusalKind.TOOL_BUDGET_EXHAUSTED:
            if action in _BUDGET_BLOCKING_ACTIONS:
                return "refused_budget_action"
    return ""


ActionHandler = Callable[[ActionInvocation], Awaitable[str | SteeringObservation | ActionRefusal]]


@dataclass
class ActionBudget:
    """Live-executor proposal/slot cap, not a durable lease or currency ledger.

    max_actions counts accepted proposals. answer_then_research has two handler
    stages but reserves one proposal and one tool slot before either starts.
    """

    max_actions: int
    max_tool_calls: int
    _claimed: set[str] = field(default_factory=set, init=False, repr=False)
    _tool_costs: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _tool_calls: int = field(default=0, init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (self.max_actions, self.max_tool_calls)
        ):
            raise ValueError("invalid action budget")

    def claim(self, request_id: str, tool_cost: int) -> str:
        if (
            not isinstance(request_id, str)
            or not request_id.strip()
            or len(request_id) > 160
        ):
            raise ValueError("invalid action identity")
        if type(tool_cost) is not int or tool_cost not in {0, 1}:
            raise ValueError("invalid tool reservation")
        with self._lock:
            if request_id in self._claimed:
                return "already_dispatched"
            if (
                len(self._claimed) >= self.max_actions
                or self._tool_calls + tool_cost > self.max_tool_calls
            ):
                return "budget_exhausted"
            self._claimed.add(request_id)
            self._tool_costs[request_id] = tool_cost
            self._tool_calls += tool_cost
            return "claimed"

    def release_tool(self, request_id: str) -> str:
        """Return a tool slot for a claim that provably never ran.

        Only the tool slot is returned. The action claim is kept, so a model that keeps
        proposing unauthorized tools still burns ``max_actions`` and cannot use refusals to
        search forever. This is a live-executor counter, not a currency refund: any real
        spend is the ledger's record, not this object's.
        """

        with self._lock:
            cost = self._tool_costs.pop(request_id, 0)
            if cost <= 0:
                return "no_tool_reservation"
            self._tool_calls -= cost
            return "released"


def _same_intent(left: DecisionContext, right: DecisionContext) -> bool:
    # Budget/evidence may evolve as a result of this action. Identity, user
    # intent and active run/revision must remain the same before observation.
    return (left.request_id, left.user_message, left.history, left.active_research) == (
        right.request_id,
        right.user_message,
        right.history,
        right.active_research,
    )


def _discard_late(task: asyncio.Task[str | SteeringObservation | ActionRefusal]) -> None:
    if not task.cancelled():
        task.exception()


class _StaleContext(Exception):
    pass


async def dispatch_conversation_action(
    proposal: ActionProposal,
    expected_context: DecisionContext,
    *,
    current_context: Callable[[], DecisionContext],
    handlers: Mapping[ConversationAction, ActionHandler],
    budget: ActionBudget,
    timeout_seconds: float = 5.0,
    time_policy: ActionTimePolicy | None = None,
) -> AsyncGenerator[ActionEvent, None]:
    """Yield unverified observations, with preliminary answer before research.

    The consumer must keep draining/closing this iterator to continue/stop work.
    Observations are not committed chat answers or Evidence Gate approvals.
    An admitted attempt is never automatically retried or refunded.

    Timing follows ``time_policy`` when given. Without one, both classes of action keep the
    legacy single ``timeout_seconds`` window, so existing callers are unchanged - but the
    two phases of ``answer_then_research`` then still split that one window instead of both
    being allowed to consume all of it.
    """
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= MAX_ACTION_SECONDS
    ):
        raise ValueError("invalid action timeout")
    started = time.monotonic()
    await asyncio.sleep(0)
    try:
        fresh = current_context()
    except Exception:
        yield ActionEvent(proposal.request_id, "context_unavailable")
        return
    if fresh != expected_context:
        yield ActionEvent(proposal.request_id, "stale_context")
        return
    try:
        checked = validate_proposal(
            {"schema": "conversation-decision-v1", **asdict(proposal)}, fresh
        )
    except (TypeError, ValueError):
        yield ActionEvent(proposal.request_id, "invalid_proposal")
        return
    stages = (
        (ConversationAction.ANSWER, ConversationAction.USE_TOOL)
        if checked.action == ConversationAction.ANSWER_THEN_RESEARCH
        else (checked.action,)
    )
    # Layered windows: a research action gets a research-sized deadline, and the two phases
    # of one action share a single `started`, so a slow preliminary answer eats its own
    # budget rather than the search's reserve.
    policy = (
        time_policy
        if time_policy is not None
        else ActionTimePolicy(
            conversational_seconds=timeout_seconds, research_seconds=timeout_seconds
        )
    )
    window = policy.window_for(
        started=started,
        is_research=checked.action
        in {
            ConversationAction.USE_TOOL,
            ConversationAction.ANSWER_THEN_RESEARCH,
            ConversationAction.STEER,
        },
    )
    two_phase = len(stages) == 2

    def stage_deadline(index: int) -> float:
        """A single stage owns the whole window; two stages split it, first phase first."""

        if not two_phase:
            return window.overall_deadline
        return window.first_deadline if index == 0 else window.overall_deadline

    # Freeze server handler selection before claiming, so partial configuration
    # cannot consume a budget or publish an answer without the research adapter.
    selected = tuple(handlers.get(stage) for stage in stages)
    if any(handler is None for handler in selected):
        yield ActionEvent(checked.request_id, "unsupported_action")
        return
    bound_handlers = tuple(cast(ActionHandler, handler) for handler in selected)
    if time.monotonic() >= stage_deadline(0):
        yield ActionEvent(checked.request_id, "timeout")
        return
    tool_cost = int(
        checked.action
        in {ConversationAction.USE_TOOL, ConversationAction.ANSWER_THEN_RESEARCH}
    )
    admission = budget.claim(checked.request_id, tool_cost)
    if admission != "claimed":
        yield ActionEvent(checked.request_id, admission)
        return

    for index, (stage, handler) in enumerate(zip(stages, bound_handlers)):
        deadline = stage_deadline(index)
        try:
            fresh = current_context()
            if not _same_intent(fresh, expected_context):
                yield ActionEvent(checked.request_id, "stale_context", stage)
                return
            # Recheck real capabilities before each action; a preliminary answer
            # cannot grant a tool that was removed while the consumer paused.
            validate_proposal(
                {"schema": "conversation-decision-v1", **asdict(checked)}, fresh
            )
        except Exception:
            yield ActionEvent(checked.request_id, "stale_context", stage)
            return

        invoked = False

        async def invoke(
            bound_handler: ActionHandler = handler,
            bound_stage: ConversationAction = stage,
            bound_deadline: float = deadline,
        ) -> str | SteeringObservation | ActionRefusal:
            nonlocal invoked
            if time.monotonic() >= bound_deadline:
                raise TimeoutError("action deadline")
            try:
                current = current_context()
                if not _same_intent(current, expected_context):
                    raise ValueError("stale intent")
                validate_proposal(
                    {"schema": "conversation-decision-v1", **asdict(checked)}, current
                )
            except Exception:
                raise _StaleContext from None
            invoked = True
            return await bound_handler(ActionInvocation(checked, bound_stage))

        task = asyncio.create_task(invoke())
        error = ""
        content: str | SteeringObservation | ActionRefusal = ""
        try:
            done, _ = await asyncio.wait(
                {task}, timeout=max(0, deadline - time.monotonic())
            )
            if not done:
                error = "timeout"
            else:
                content = task.result()
        except asyncio.CancelledError:
            caller = asyncio.current_task()
            if caller is not None and caller.cancelling():
                raise
            error = "handler_error"
        except TimeoutError:
            error = "timeout"
        except _StaleContext:
            error = "stale_context"
        except Exception:
            error = "handler_error"
        finally:
            if not task.done():
                task.cancel()
            task.add_done_callback(_discard_late)
        if error:
            yield ActionEvent(
                checked.request_id,
                error,
                stage,
                outcome_unknown=invoked and error != "stale_context",
                attempted=invoked,
            )
            return
        if isinstance(content, ActionRefusal):
            # Nothing ran: no unknown outcome, and the tool slot goes back so a refused
            # proposal cannot spend the search budget. The action claim is not released.
            budget.release_tool(checked.request_id)
            yield ActionEvent(
                checked.request_id,
                "refused",
                stage,
                attempted=False,
                outcome_unknown=False,
                refusal_kind=str(content.kind),
                refusal_reason=content.reason,
            )
            return
        completion_context = expected_context
        if isinstance(content, SteeringObservation):
            before = expected_context.active_research
            after = content.research_after
            if (
                stage != ConversationAction.STEER
                or before is None
                or not isinstance(after, ActiveResearch)
                or after.run_id != before.run_id
                or after.revision <= before.revision
            ):
                yield ActionEvent(
                    checked.request_id, "invalid_observation", stage, attempted=invoked
                )
                return
            completion_context = replace(expected_context, active_research=after)
            content = content.observation
        try:
            still_current = _same_intent(current_context(), completion_context)
        except Exception:
            still_current = False
        if not still_current:
            yield ActionEvent(
                checked.request_id, "stale_context", stage, attempted=invoked
            )
            return
        if time.monotonic() >= deadline:
            yield ActionEvent(
                checked.request_id,
                "timeout",
                stage,
                outcome_unknown=True,
                attempted=invoked,
            )
            return
        if not isinstance(content, str) or not content.strip() or len(content) > 8000:
            yield ActionEvent(
                checked.request_id, "invalid_observation", stage, attempted=invoked
            )
            return
        yield ActionEvent(
            checked.request_id, "observed", stage, content, attempted=invoked
        )
