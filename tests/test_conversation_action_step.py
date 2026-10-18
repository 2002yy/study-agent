"""Single-step integration; injected model output is not live model acceptance."""

import asyncio
from contextlib import aclosing
from dataclasses import replace
import json

import pytest

from src.application.conversation_action_dispatch import ActionBudget, ActionEvent
from src.application.conversation_action_step import run_conversation_step
from src.application.conversation_decision import ConversationAction, DecisionContext
from src.application.conversation_decision_runner import DecisionBudget, DecisionResult


def setup_step(*, timeout=1, current=None, model=None, handler=None):
    ctx = DecisionContext(
        "step-1", "分析后计算", available_tools=("compute",), remaining_tool_calls=1
    )
    calls = []

    async def transport(request):
        calls.append("model")
        if model:
            return await model(request)
        return json.dumps(
            {
                "schema": "conversation-decision-v1",
                "request_id": ctx.request_id,
                "action": "answer_then_research",
                "relation": "new_topic",
                "reason": "需要计算",
                "focus": "加法",
                "tool": "compute",
                "target_run_id": None,
                "target_revision": None,
                "active_run_disposition": "none",
            }
        )

    async def action(invocation):
        calls.append(invocation.stage.value)
        if handler:
            return await handler(invocation)
        return "先分析" if invocation.stage == ConversationAction.ANSWER else str(2 + 3)

    decisions = DecisionBudget(1, 100000, 800)
    actions = ActionBudget(1, 1)
    stream = run_conversation_step(
        ctx,
        current_context=current or (lambda: ctx),
        transport=transport,
        decision_budget=decisions,
        action_budget=actions,
        handlers={
            ConversationAction.ANSWER: action,
            ConversationAction.USE_TOOL: action,
        },
        timeout_seconds=timeout,
    )
    return ctx, calls, stream, actions


def test_stream_exposes_preliminary_answer_before_tool_and_returns_observation():
    async def scenario():
        _, calls, stream, _ = setup_step()
        async with aclosing(stream):
            decision = await anext(stream)
            assert (
                isinstance(decision, DecisionResult) and decision.status == "completed"
            )
            assert calls == ["model"]
            answer = await anext(stream)
            assert isinstance(answer, ActionEvent) and answer.observation == "先分析"
            assert calls == ["model", "answer"]
            observed = await anext(stream)
            assert observed.observation == "5" and observed.status == "observed"
            assert [event async for event in stream] == []
        assert calls == ["model", "answer", "use_tool"]

    asyncio.run(scenario())


@pytest.mark.parametrize("count", [1, 2])
def test_close_at_decision_or_answer_prevents_tool(count):
    async def scenario():
        _, calls, stream, _ = setup_step()
        for _ in range(count):
            await anext(stream)
        await stream.aclose()
        assert calls == ["model"] + (["answer"] if count == 2 else [])

    asyncio.run(scenario())


def test_changed_intent_after_decision_rejects_dispatch_without_claim():
    async def scenario():
        snapshots = []
        ctx, calls, stream, budget = setup_step(current=lambda: snapshots[-1])
        snapshots.append(ctx)
        await anext(stream)
        snapshots.append(replace(ctx, user_message="换个话题"))
        event = await anext(stream)
        assert event.status == "stale_context" and not event.attempted
        assert budget.claim(ctx.request_id, 1) == "claimed"
        assert calls == ["model"]
        await stream.aclose()

    asyncio.run(scenario())


def test_consumer_pause_counts_against_total_deadline():
    async def scenario():
        ctx, calls, stream, budget = setup_step(timeout=0.04)
        await anext(stream)
        await asyncio.sleep(0.06)
        event = await anext(stream)
        assert event.status == "timeout" and not event.attempted
        assert budget.claim(ctx.request_id, 1) == "claimed"
        assert calls == ["model"]
        await stream.aclose()

    asyncio.run(scenario())


def test_invalid_model_output_never_dispatches():
    async def model(_):
        return "invalid"

    async def scenario():
        _, calls, stream, _ = setup_step(model=model)
        events = [event async for event in stream]
        assert len(events) == 1 and events[0].status != "completed"
        assert calls == ["model"]

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["model", "action"])
def test_caller_cancellation_reaches_active_adapter(phase):
    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def blocked(_):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        _, calls, stream, _ = setup_step(
            model=blocked if phase == "model" else None,
            handler=blocked if phase == "action" else None,
        )
        if phase == "action":
            await anext(stream)
        task = asyncio.create_task(anext(stream))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(cancelled.wait(), 0.5)
        await stream.aclose()
        assert "use_tool" not in calls

    asyncio.run(scenario())


@pytest.mark.parametrize("timeout", [True, 0, -1, 31, float("nan"), float("inf")])
def test_invalid_total_limit_does_not_call_model(timeout):
    async def scenario():
        _, calls, stream, _ = setup_step(timeout=timeout)
        with pytest.raises(ValueError, match="step timeout"):
            await anext(stream)
        assert not calls

    asyncio.run(scenario())
