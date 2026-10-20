"""Provisional display events, no raw reasoning, tool bodies or authority."""

import asyncio
from contextlib import aclosing
from dataclasses import FrozenInstanceError
import json

import pytest

from src.application.conversation_action_dispatch import ActionEvent
from src.application.conversation_bounded_loop import LoopStopped
from src.application.conversation_decision import ConversationAction
from src.application.conversation_decision_runner import DecisionResult
from src.application.conversation_loop_session import ConversationLoopSession
from src.application.conversation_progress_stream import (
    ConversationProgress,
    conversation_progress_stream,
)
from tests.test_conversation_deepseek_service import setup
from tests.test_conversation_observation_trail import root, proposal


def test_owned_service_progress_has_ordered_preliminary_and_final_answers():
    async def run():
        start, clients, _, calls, _, _ = setup(("answer_then_research", "answer"))
        session = start()
        async with aclosing(conversation_progress_stream(session)) as stream:
            frames = [item async for item in stream]
        assert [item.phase for item in frames if item.kind == "answer"] == [
            "preliminary",
            "final",
        ]
        assert [item.sequence for item in frames] == list(range(1, len(frames) + 1))
        assert len({item.event_id for item in frames}) == len(frames)
        assert all(item.request_id == "service-1" for item in frames)
        assert frames[-1].kind == "terminal" and frames[-1].status == "answered"
        assert all(
            item.publication_status == "provisional"
            and item.evidence_status == "unverified"
            for item in frames
        )
        assert "工具计算结果" not in json.dumps(
            [item.to_dict() for item in frames], ensure_ascii=False
        )
        assert calls == [ConversationAction.USE_TOOL] and clients[0].is_closed()

    asyncio.run(run())


def test_unread_progress_claim_can_close_without_sdk():
    async def run():
        start, clients, requests, _, _, _ = setup()
        session = start()
        stream = conversation_progress_stream(session)
        assert session.receipt.status == "claimed"
        with pytest.raises(RuntimeError):
            conversation_progress_stream(session)
        await stream.aclose()
        assert session.receipt.status == "closed" and not clients and not requests

    asyncio.run(run())


def test_closing_after_preliminary_does_not_start_the_tool():
    async def run():
        start, clients, requests, calls, _, _ = setup(
            ("answer_then_research", "answer")
        )
        stream = conversation_progress_stream(start())
        assert (await anext(stream)).status == "planned"
        assert (await anext(stream)).phase == "preliminary"
        await stream.aclose()
        assert not calls and len(requests) == 2 and clients[0].is_closed()

    asyncio.run(run())


def test_sse_escapes_answer_newlines_and_never_exposes_reason_or_context():
    async def run():
        text = "回答\n\nevent: injected\ndata: another\n中文"
        start, _, _, _, _, _ = setup(answer=text)
        async with aclosing(conversation_progress_stream(start())) as stream:
            frames = [item async for item in stream]
        answer = next(item for item in frames if item.kind == "answer")
        wire = answer.to_sse()
        assert len(wire.splitlines()) == 4
        assert wire.count("\nevent:") == 1
        payload = json.loads(wire.splitlines()[2].removeprefix("data: "))
        assert payload["text"] == text
        assert (
            not {"reason", "history", "messages", "user_message", "evidence_summary"}
            & payload.keys()
        )
        assert "选择下一步" not in wire
        assert answer.event_id == answer.event_id
        with pytest.raises(FrozenInstanceError):
            answer.text = "changed"
        with pytest.raises(TypeError):
            ConversationProgress(
                "id", 1, "answer", "observed", evidence_status="verified"
            )

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["missing_terminal", "exception", "close_error"])
def test_stream_failures_become_one_sanitized_failed_terminal(failure):
    async def run():
        ctx = root()

        async def source():
            try:
                yield DecisionResult(
                    "completed", proposal(ctx, "answer"), attempted=True
                )
                if failure == "exception":
                    raise RuntimeError("private-stream-detail")
                if failure == "close_error":
                    yield LoopStopped("answered", 1, 0)
            finally:
                if failure == "close_error":
                    raise RuntimeError("private-close-detail")

        session = ConversationLoopSession(ctx.request_id, source())
        async with aclosing(conversation_progress_stream(session)) as stream:
            frames = [item async for item in stream]
        terminal = frames[-1]
        assert terminal.kind == "terminal" and terminal.status == "failed"
        assert (
            terminal.detail
            == {
                "missing_terminal": "missing_terminal_event",
                "exception": "stream_error",
                "close_error": "close_error",
            }[failure]
        )
        assert terminal.outcome_unknown and terminal.publication_status == "provisional"
        assert "private-" not in repr(frames)
        assert sum(frame.kind == "terminal" for frame in frames) == 1

    asyncio.run(run())


def test_unbound_action_is_rejected_without_showing_its_body():
    async def run():
        async def source():
            yield ActionEvent(
                "other",
                "observed",
                ConversationAction.ANSWER,
                "must-not-display",
                attempted=True,
            )

        session = ConversationLoopSession("root", source())
        async with aclosing(conversation_progress_stream(session)) as stream:
            frames = [item async for item in stream]
        assert (
            len(frames) == 1
            and frames[0].status == "failed"
            and frames[0].outcome_unknown
        )
        assert "must-not-display" not in repr(frames)

    asyncio.run(run())


def test_caller_cancellation_propagates_and_closes_source():
    async def run():
        entered, closed = asyncio.Event(), asyncio.Event()

        async def source():
            try:
                entered.set()
                await asyncio.Event().wait()
                yield LoopStopped("unreachable", 0, 0)
            finally:
                closed.set()

        session = ConversationLoopSession("root", source())
        stream = conversation_progress_stream(session)
        task = asyncio.create_task(anext(stream))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set() and session.receipt.status == "cancelled"
        await stream.aclose()

    asyncio.run(run())


def test_concurrent_read_is_rejected_without_closing_the_active_reader():
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        ctx = root()

        async def source():
            entered.set()
            await release.wait()
            yield DecisionResult("completed", proposal(ctx, "answer"), attempted=True)

        stream = conversation_progress_stream(
            ConversationLoopSession(ctx.request_id, source())
        )
        task = asyncio.create_task(anext(stream))
        await entered.wait()
        with pytest.raises(RuntimeError, match="concurrent"):
            await anext(stream)
        release.set()
        assert (await task).status == "planned"
        await stream.aclose()

    asyncio.run(run())
