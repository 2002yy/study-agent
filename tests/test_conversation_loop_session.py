"""Lifecycle receipts and non-replay boundaries for the bounded loop."""

import asyncio
from contextlib import aclosing
from dataclasses import FrozenInstanceError
import json

import pytest

from src.application.conversation_action_dispatch import ActionBudget, ActionEvent
from src.application.conversation_bounded_loop import LoopStopped, run_conversation_loop
from src.application.conversation_decision import ConversationAction, DecisionContext
from src.application.conversation_decision_runner import DecisionBudget, DecisionResult
from src.application.conversation_loop_session import ConversationLoopSession


def fake_session():
    calls = []

    async def source():
        try:
            calls.append("decision")
            yield DecisionResult("completed")
            calls.append("action")
            yield ActionEvent(
                "request-1",
                "observed",
                ConversationAction.ANSWER,
                "private observation text",
                attempted=True,
            )
            yield LoopStopped("answered", 1, 1)
        finally:
            calls.append("closed")

    return ConversationLoopSession("request-1", source()), calls


def test_normal_drain_has_terminal_receipt_without_observation_text():
    async def run():
        session, calls = fake_session()
        assert session.receipt.status == "ready"
        stream = session.events()
        assert session.receipt.status == "claimed"
        async with aclosing(stream):
            events = [item async for item in stream]
        receipt = session.receipt
        assert len(events) == 3 and calls == ["decision", "action", "closed"]
        assert (
            receipt.status,
            receipt.stop_reason,
            receipt.decision_steps,
            receipt.observations,
        ) == ("stopped", "answered", 1, 1)
        assert not receipt.outcome_unknown
        assert "private" not in repr(receipt)
        with pytest.raises(FrozenInstanceError):
            receipt.status = "changed"
        with pytest.raises(RuntimeError, match="already consumed"):
            session.events()

    asyncio.run(run())


@pytest.mark.parametrize("events_read", [0, 1, 2])
def test_close_at_each_boundary_is_not_completion_or_replay(events_read):
    async def run():
        session, calls = fake_session()
        stream = session.events()
        for _ in range(events_read):
            await anext(stream)
        await stream.aclose()
        receipt = session.receipt
        assert receipt.status == "closed" and receipt.stop_reason == ""
        assert receipt.observations == int(events_read == 2)
        assert not receipt.outcome_unknown
        assert "action" not in calls if events_read < 2 else "action" in calls
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        with pytest.raises(RuntimeError, match="already consumed"):
            session.events()

    asyncio.run(run())


def test_close_before_claim_never_starts_source():
    async def run():
        session, calls = fake_session()
        await session.aclose()
        await session.aclose()
        assert session.receipt.status == "closed" and calls == []
        with pytest.raises(RuntimeError, match="already consumed"):
            session.events()

    asyncio.run(run())


def test_second_handle_cannot_claim_while_first_is_active():
    async def run():
        session, calls = fake_session()
        stream = session.events()
        with pytest.raises(RuntimeError, match="already consumed"):
            session.events()
        assert calls == []
        await stream.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["caller_cancel", "explicit_close", "concurrent_read"])
def test_active_pull_cancellation_and_concurrent_close_have_truthful_receipts(mode):
    async def run():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def source():
            entered.set()
            try:
                await asyncio.Event().wait()
                yield DecisionResult("unreachable")
            finally:
                cancelled.set()

        session = ConversationLoopSession("request-1", source())
        stream = session.events()
        task = asyncio.create_task(anext(stream))
        await entered.wait()
        if mode == "concurrent_read":
            with pytest.raises(RuntimeError, match="concurrent"):
                await anext(stream)
            await session.aclose()
            with pytest.raises(StopAsyncIteration):
                await task
        elif mode == "explicit_close":
            await session.aclose()
            with pytest.raises(StopAsyncIteration):
                await task
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        await asyncio.wait_for(cancelled.wait(), 0.5)
        receipt = session.receipt
        assert receipt.status == ("cancelled" if mode == "caller_cancel" else "closed")
        assert receipt.outcome_unknown and receipt.decision_steps == 0
        await session.aclose()
        assert session.receipt == receipt

    asyncio.run(run())


def test_abrupt_source_end_is_failed_and_does_not_claim_completion():
    async def run():
        async def source():
            yield DecisionResult("completed")

        session = ConversationLoopSession("request-1", source())
        async with aclosing(session.events()) as stream:
            events = [event async for event in stream]
        assert len(events) == 1
        assert session.receipt.status == "failed"
        assert session.receipt.detail == "missing_terminal_event"
        assert session.receipt.outcome_unknown

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["exception", "counts", "invalid_event"])
def test_bad_stream_is_sanitized_and_closed(failure):
    async def run():
        closed = []

        async def source():
            try:
                if failure == "exception":
                    raise ValueError("private exception material")
                yield (
                    LoopStopped("answered", 1, 0) if failure == "counts" else "invalid"
                )
            finally:
                closed.append(True)

        session = ConversationLoopSession("request-1", source())
        async with aclosing(session.events()) as stream:
            with pytest.raises(RuntimeError, match="^conversation session failed$"):
                await anext(stream)
        assert closed and session.receipt.status == "failed"
        assert (
            session.receipt.detail == "stream_error" and session.receipt.outcome_unknown
        )
        assert "private" not in repr(session.receipt)

    asyncio.run(run())


def test_unknown_outcome_remains_unknown_when_stream_is_closed():
    async def run():
        async def source():
            yield DecisionResult("provider_error", attempted=True, outcome_unknown=True)
            yield LoopStopped("decision_failed", 1, 0, True, "provider_error")

        session = ConversationLoopSession("request-1", source())
        stream = session.events()
        await anext(stream)
        await stream.aclose()
        assert session.receipt.status == "closed" and session.receipt.outcome_unknown

    asyncio.run(run())


def test_close_failure_is_sanitized_and_is_not_reported_as_closed():
    async def run():
        async def source():
            try:
                yield DecisionResult("completed")
            finally:
                raise ValueError("private cleanup payload")

        session = ConversationLoopSession("request-1", source())
        stream = session.events()
        await anext(stream)
        with pytest.raises(RuntimeError, match="^conversation session close failed$"):
            await stream.aclose()
        assert (
            session.receipt.status == "failed"
            and session.receipt.detail == "close_error"
        )
        assert session.receipt.outcome_unknown and "private" not in repr(
            session.receipt
        )

    asyncio.run(run())


def test_caller_cancellation_during_close_is_not_swallowed():
    async def run():
        closing = asyncio.Event()

        async def source():
            try:
                yield DecisionResult("completed")
            finally:
                closing.set()
                await asyncio.Event().wait()

        session = ConversationLoopSession("request-1", source())
        stream = session.events()
        await anext(stream)
        task = asyncio.create_task(stream.aclose())
        await closing.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert session.receipt.status == "cancelled" and session.receipt.outcome_unknown

    asyncio.run(run())


def test_real_loop_session_reuses_admission_and_cannot_resubmit_after_close():
    async def run():
        ctx = DecisionContext("request-1", "直接回答")
        calls = []

        async def model(request):
            calls.append("model")
            return json.dumps(
                {
                    "schema": "conversation-decision-v1",
                    "request_id": ctx.request_id,
                    "action": "answer",
                    "relation": "new_topic",
                    "reason": "已有信息足够",
                    "focus": "回答",
                    "tool": None,
                    "target_run_id": None,
                    "target_revision": None,
                    "active_run_disposition": "none",
                }
            )

        async def answer(_):
            calls.append("answer")
            return "初步回答"

        budget = DecisionBudget(2, 100000, 1600)

        def make():
            return ConversationLoopSession(
                ctx.request_id,
                run_conversation_loop(
                    ctx,
                    current_context=lambda: ctx,
                    transport=model,
                    decision_budget=budget,
                    action_budget=ActionBudget(2, 0),
                    handlers={ConversationAction.ANSWER: answer},
                ),
            )

        first = make()
        async with aclosing(first.events()) as stream:
            await anext(stream)
        assert first.receipt.status == "closed" and calls == ["model"]
        # Even a new session cannot turn a consumed identity into a new model attempt.
        second = make()
        async with aclosing(second.events()) as stream:
            events = [event async for event in stream]
        assert events[-1].detail == "already_attempted" and calls == ["model"]
        assert (
            second.receipt.status == "stopped"
            and second.receipt.stop_reason == "decision_failed"
        )

    asyncio.run(run())


@pytest.mark.parametrize("request_id", ["", " ", "x" * 161, None])
def test_invalid_identity_is_rejected_without_starting_stream(request_id):
    async def source():
        yield LoopStopped("answered", 0, 0)

    stream = source()
    with pytest.raises(ValueError):
        ConversationLoopSession(request_id, stream)
    asyncio.run(stream.aclose())
