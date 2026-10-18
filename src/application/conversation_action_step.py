"""Opt-in single decision/action stream; observations carry no evidence authority."""

from __future__ import annotations

from contextlib import aclosing
from dataclasses import replace
import math
import time
from typing import AsyncGenerator, Callable, Mapping

from src.application.conversation_action_dispatch import (
    ActionBudget,
    ActionEvent,
    ActionHandler,
    dispatch_conversation_action,
)
from src.application.conversation_decision import ConversationAction, DecisionContext
from src.application.conversation_decision_runner import (
    DecisionBudget,
    DecisionLimits,
    DecisionResult,
    DecisionTransport,
    decide_conversation_action,
)


async def run_conversation_step(
    context: DecisionContext,
    *,
    current_context: Callable[[], DecisionContext],
    transport: DecisionTransport,
    decision_budget: DecisionBudget,
    action_budget: ActionBudget,
    handlers: Mapping[ConversationAction, ActionHandler],
    limits: DecisionLimits = DecisionLimits(),
    timeout_seconds: float = 10.0,
) -> AsyncGenerator[DecisionResult | ActionEvent, None]:
    """Make at most one decision, then stream its action observations.

    Consumer pause time counts against the total deadline. Closing after the
    decision or preliminary answer prevents subsequent actions. No automatic
    retry, next decision, publication, or promotion of observations to evidence.
    The caller must drain or close this iterator and own durable admission.
    """
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 30
    ):
        raise ValueError("invalid step timeout")
    deadline = time.monotonic() + timeout_seconds
    decision = await decide_conversation_action(
        context,
        transport=transport,
        budget=decision_budget,
        current_context=current_context,
        limits=replace(
            limits, timeout_seconds=min(limits.timeout_seconds, timeout_seconds)
        ),
    )
    yield decision
    if decision.status != "completed" or decision.proposal is None:
        return
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        yield ActionEvent(context.request_id, "timeout")
        return
    # aclosing propagates early closure through the nested action stream.
    async with aclosing(
        dispatch_conversation_action(
            decision.proposal,
            context,
            current_context=current_context,
            handlers=handlers,
            budget=action_budget,
            timeout_seconds=remaining,
        )
    ) as actions:
        async for event in actions:
            yield event
