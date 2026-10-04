from __future__ import annotations

import asyncio
from dataclasses import replace
import threading
import time

import pytest

from src.application.chat_service import ChatCommand
from src.application.research_deadline import (
    bounded_model_call,
    bounded_stream,
    request_options,
)
from tests.test_chat_service import _service


def test_non_research_calls_keep_original_request_signature():
    assert request_options(None) == {}
    assert bounded_model_call(None, lambda: "answer") == "answer"
    assert list(bounded_stream(None, iter(["a", "b"]))) == ["a", "b"]


def test_expired_deadline_never_starts_inference():
    called = []
    with pytest.raises(TimeoutError):
        bounded_model_call(time.monotonic() - 1, lambda: called.append(True))
    assert called == []


def test_blocked_model_cannot_return_a_late_answer():
    release, finished = threading.Event(), threading.Event()

    def inference():
        release.wait(timeout=2)
        finished.set()
        return "late answer"

    try:
        with pytest.raises(TimeoutError):
            bounded_model_call(time.monotonic() + 0.05, inference)
        assert not finished.is_set()
    finally:
        release.set()
    assert finished.wait(timeout=2)


def test_blocked_stream_preserves_received_prefix_and_drops_late_tokens():
    release, closed = threading.Event(), threading.Event()

    def source():
        try:
            yield "prefix"
            release.wait(timeout=2)
            yield "late"
        finally:
            closed.set()

    stream = bounded_stream(time.monotonic() + 0.1, source())
    try:
        assert next(stream) == "prefix"
        with pytest.raises(TimeoutError):
            next(stream)
    finally:
        release.set()
    assert closed.wait(timeout=2)


def test_chat_sync_deadline_failure_settles_turn_without_publishing_late_answer(
    tmp_path,
):
    service, repository = _service(tmp_path)
    prepared = service.start_turn(
        ChatCommand(user_input="Question", thread_id="deadline-sync")
    )
    prepared = replace(prepared, research_deadline=time.monotonic() - 1)
    with pytest.raises(TimeoutError):
        service.generate(prepared)
    restored = repository.get_chat_turn(prepared.turn.id)
    assert restored.status == "failed"
    assert not restored.assistant_message
    assert prepared.route.get("answer_generation_calls", 0) == 0


def test_async_stream_has_absolute_deadline_even_when_provider_keeps_connection_open(
    tmp_path,
):
    service, _ = _service(tmp_path)

    async def source(*_args, **kwargs):
        # Subtracting a large Windows monotonic timestamp can add a few ULPs.
        assert 0 < kwargs["timeout"] <= 0.1 + 1e-8
        yield "prefix"
        await asyncio.sleep(1)
        yield "late"

    service.dependencies = replace(service.dependencies, async_stream_chat=source)
    prepared = service.start_turn(
        ChatCommand(user_input="Question", thread_id="deadline-async")
    )
    prepared = replace(prepared, research_deadline=time.monotonic() + 0.1)
    received = []

    async def consume():
        async for token in service.stream_async(prepared):
            received.append(token)

    with pytest.raises(TimeoutError):
        asyncio.run(consume())
    assert received == ["prefix"]
