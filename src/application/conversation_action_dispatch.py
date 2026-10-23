"""Opt-in action handlers and observations; no production tool/publication wiring.

Handlers are trusted server adapters, not model-provided code. They own argument
validation, durable execution identity and any paid-call/permission checks. The
local budget prevents duplicate dispatch within one live executor only.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field, replace
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


@dataclass(frozen=True)
class SteeringObservation:
    """Trusted adapter receipt, captured by the handler's own state update.

    The adapter must return the exact research snapshot it committed, not read
    an unrelated latest revision after committing. This is not an applied or
    evidence receipt for the production research system.
    """

    observation: str
    research_after: ActiveResearch


ActionHandler = Callable[[ActionInvocation], Awaitable[str | SteeringObservation]]


@dataclass
class ActionBudget:
    """Live-executor proposal/slot cap, not a durable lease or currency ledger.

    max_actions counts accepted proposals. answer_then_research has two handler
    stages but reserves one proposal and one tool slot before either starts.
    """

    max_actions: int
    max_tool_calls: int
    _claimed: set[str] = field(default_factory=set, init=False, repr=False)
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
            self._tool_calls += tool_cost
            return "claimed"


def _same_intent(left: DecisionContext, right: DecisionContext) -> bool:
    # Budget/evidence may evolve as a result of this action. Identity, user
    # intent and active run/revision must remain the same before observation.
    return (left.request_id, left.user_message, left.history, left.active_research) == (
        right.request_id,
        right.user_message,
        right.history,
        right.active_research,
    )


def _discard_late(task: asyncio.Task[str | SteeringObservation]) -> None:
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
        ) -> str | SteeringObservation:
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
        content: str | SteeringObservation = ""
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
