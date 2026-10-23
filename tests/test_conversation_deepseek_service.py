"""Service lifecycle over real SDK/fake HTTP; never real credentials or spend."""

import asyncio
from contextlib import aclosing
from dataclasses import replace
import json

import httpx
import pytest

from src.application.conversation_action_dispatch import ActionBudget
from src.application.conversation_decision import ConversationAction, DecisionContext
from src.application.conversation_decision_runner import DecisionBudget
from src.application.conversation_deepseek_service import DeepSeekConversationService
from tests.test_conversation_deepseek_session import factory, response, settings


def setup(actions=("answer",), *, answer="具体分析", failure=False):
    clients, arguments, requests, calls = [], [], [], []
    state = [
        DecisionContext(
            "service-1",
            "比较自动化方案",
            available_tools=("compute",),
            remaining_tool_calls=2,
        )
    ]
    choices = iter(actions)

    def http(req):
        wire = json.loads(req.content)
        requests.append(wire)
        if failure:
            return httpx.Response(503, json={"error": {"message": "private-failure"}})
        if "response_format" in wire:
            data = json.loads(wire["messages"][1]["content"])
            action = next(choices)
            text = json.dumps(
                {
                    "schema": "conversation-decision-v1",
                    "request_id": data["request_id"],
                    "action": action,
                    "relation": "continuation",
                    "reason": "选择下一步",
                    "focus": "比较",
                    "tool": "compute"
                    if action in {"use_tool", "answer_then_research"}
                    else None,
                    "target_run_id": None,
                    "target_revision": None,
                    "active_run_disposition": "none",
                }
            )
        else:
            text = answer
        return httpx.Response(200, json=response(text))

    async def tool(invocation):
        calls.append(invocation.stage)
        state[0] = replace(
            state[0], remaining_tool_calls=state[0].remaining_tool_calls - 1
        )
        return "工具计算结果"

    service = DeepSeekConversationService(settings(), factory(http, clients, arguments))
    budgets = DecisionBudget(8, 1000000, 20000), ActionBudget(8, 2)

    def start(*, context=None):
        return service.start(
            context or state[0],
            current_context=lambda: state[0],
            model_budget=budgets[0],
            action_budget=budgets[1],
            handlers={ConversationAction.USE_TOOL: tool},
        )

    return start, clients, requests, calls, state, budgets


def test_unread_claimed_run_closes_without_sdk_or_requests():
    async def run():
        start, clients, requests, _, _, _ = setup()
        session = start()
        assert session.receipt.status == "ready"
        async with aclosing(session.events()):
            assert session.receipt.status == "claimed"
        assert session.receipt.status == "closed"
        assert not clients and not requests

    asyncio.run(run())


def test_direct_answer_finishes_and_closes_owned_sdk_before_terminal_delivery():
    async def run():
        start, clients, requests, calls, _, budget = setup()
        session = start()
        async with aclosing(session.events()) as stream:
            events = [event async for event in stream]
        assert events[-1].reason == "answered"
        assert clients[0].is_closed()
        assert session.receipt.status == "stopped"
        assert (session.receipt.decision_steps, session.receipt.observations) == (1, 1)
        assert len(requests) == 2 and len(budget[0]._requests) == 2 and not calls
        assert "具体分析" not in repr(session.receipt)

    asyncio.run(run())


def test_preliminary_tool_and_final_are_one_owned_run_with_accumulated_input():
    async def run():
        start, clients, requests, calls, _, _ = setup(
            ("answer_then_research", "answer")
        )
        session = start()
        async with aclosing(session.events()) as stream:
            events = [event async for event in stream]
        assert events[-1].reason == "answered" and clients[0].is_closed()
        assert calls == [ConversationAction.USE_TOOL]
        entries = json.loads(requests[-1]["messages"][1]["content"])["observations"][
            "entries"
        ]
        assert [item["content"] for item in entries] == ["具体分析", "工具计算结果"]
        assert (session.receipt.decision_steps, session.receipt.observations) == (2, 3)

    asyncio.run(run())


def test_close_after_preliminary_keeps_tool_and_later_generation_unstarted():
    async def run():
        start, clients, requests, calls, _, _ = setup(
            ("answer_then_research", "answer")
        )
        session = start()
        stream = session.events()
        await anext(stream)
        assert (await anext(stream)).observation == "具体分析"
        await stream.aclose()
        assert clients[0].is_closed() and not calls and len(requests) == 2
        assert session.receipt.status == "closed"

    asyncio.run(run())


def test_stale_snapshot_sends_nothing_and_still_closes_owned_client():
    async def run():
        start, clients, requests, _, state, _ = setup()
        original = state[0]
        state[0] = replace(original, user_message="另一个问题")
        session = start(context=original)
        async with aclosing(session.events()) as stream:
            events = [event async for event in stream]
        assert events[-1].detail == "stale_context"
        assert not requests and clients[0].is_closed()

    asyncio.run(run())


def test_duplicate_service_start_cannot_recharge_shared_admission():
    async def run():
        start, clients, requests, _, _, _ = setup()
        for expected in ("answered", "decision_failed"):
            session = start()
            async with aclosing(session.events()) as stream:
                events = [event async for event in stream]
            assert events[-1].reason == expected
        assert len(requests) == 2 and all(client.is_closed() for client in clients)

    asyncio.run(run())


def test_provider_failure_is_receipted_without_retry_or_raw_error():
    async def run():
        start, clients, requests, _, _, _ = setup(failure=True)
        session = start()
        async with aclosing(session.events()) as stream:
            events = [event async for event in stream]
        assert events[-1].detail == "provider_error" and session.receipt.outcome_unknown
        assert "private-failure" not in repr(events)
        assert len(requests) == 1 and clients[0].is_closed()

    asyncio.run(run())


def test_run_consumer_can_only_be_claimed_once():
    async def run():
        start, clients, requests, _, _, _ = setup()
        session = start()
        stream = session.events()
        with pytest.raises(RuntimeError):
            session.events()
        await stream.aclose()
        assert not clients and not requests

    asyncio.run(run())


def test_active_consumer_cancellation_closes_nested_sdk_and_marks_unknown():
    async def run():
        clients, arguments = [], []
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def http(req):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            return httpx.Response(200, json=response("unreachable"))

        service = DeepSeekConversationService(
            settings(), factory(http, clients, arguments)
        )
        ctx = DecisionContext("cancel-run", "解释")
        session = service.start(
            ctx,
            current_context=lambda: ctx,
            model_budget=DecisionBudget(2, 400000, 5000),
            action_budget=ActionBudget(1, 0),
            handlers={},
        )
        stream = session.events()
        task = asyncio.create_task(anext(stream))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(cancelled.wait(), 1)
        assert clients[0].is_closed()
        assert session.receipt.status == "cancelled" and session.receipt.outcome_unknown
        await stream.aclose()

    asyncio.run(run())
