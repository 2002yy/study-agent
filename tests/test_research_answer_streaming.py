"""Research-backed streaming buffering tests (RQ1-C answer batch).

A research-backed turn buffers the whole candidate until the publication gate
passes; a binding failure therefore emits zero candidate tokens while the
canonical blocked copy is what the learner sees. Ordinary chat streaming keeps
emitting tokens as they arrive.
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import replace
from typing import Any, AsyncIterator

import pytest

from src.api.models.chat import ChatRequest
from src.api.routes.chat_routes import chat_stream_endpoint
from src.application.chat_service import (
    RESEARCH_ANSWER_BLOCKED_COPY,
    ChatCommand,
    ChatDependencies,
    ChatService,
)
from src.context_builder import build_messages
from src.mode_manager import RuntimeModes
from src.router import route_request

EVIDENCE_ID = "evidence_stream_1"
RESEARCH_CLAIM_ID = "research_claim_stream_1"


@pytest.fixture(autouse=True)
def _legacy_strict_publication_contract(monkeypatch):
    monkeypatch.setenv("RESEARCH_PUBLICATION_MODE", "strict")


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


class DisconnectedRequest:
    async def is_disconnected(self) -> bool:
        return True


def _row(evidence_id: str = EVIDENCE_ID) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "claim_id": RESEARCH_CLAIM_ID,
        "title": "Stream release note",
        "url": "https://official.example/stream-release",
        "source_role": "official_statement",
        "source_cluster_id": "cluster_s1",
        "relation": "supports",
        "strength": "strong",
        "locator": "第二段",
        "anchored_spans": ("official confirmation",),
        "caveats": (),
    }


def _payload(
    support: tuple[str, ...] = (EVIDENCE_ID,), *, refused: bool = False
) -> str:
    segment = {
        "segment_ref": "s1",
        "kind": "factual",
        "research_claim_id": RESEARCH_CLAIM_ID,
        "status": "asserted",
        "evidence_support": list(support),
    }
    return json.dumps(
        {"refused": refused, "segments": [segment]}, ensure_ascii=False
    )


def _gate_plan(*, binding_json: str, allowed_attempts: int = 1) -> dict[str, Any]:
    return {
        "evidence_rows": [_row()],
        "allowed_attempts": allowed_attempts,
        "binding_json": binding_json,
    }


def _service(
    runtime_test_context,
    *,
    tokens: tuple[str, ...],
    binding_json: str,
    refuse_binding: bool = False,
    plan: dict[str, Any] | None = None,
    user_input: str = "该版本发布了吗？",
    deny_web_policy: bool = False,
    async_stream_chat: Any | None = None,
    binding_model: Any | None = None,
) -> ChatService:
    async def async_tokens(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
        for token in tokens:
            yield token

    effective_plan = plan if plan is not None else _gate_plan(binding_json=binding_json)

    def sync_chat(*args: Any, **kwargs: Any) -> str:
        if kwargs.get("task_name") == "answer_claim_binding":
            if refuse_binding:
                return json.dumps({"refused": True, "segments": []})
            if binding_model is not None:
                return binding_model()
            return effective_plan["binding_json"]
        return "".join(tokens)

    service = runtime_test_context.override_chat(
        ChatDependencies(
            load_runtime_modes=lambda: RuntimeModes(performance_mode="fast"),
            read_memory_bundle=lambda context_mode: {},
            build_role_prompt=lambda role, **kwargs: f"role prompt for {role}",
            route_request=route_request,
            retrieve_local_knowledge=lambda *args, **kwargs: _FakeRagResult(),
            build_messages=build_messages,
            chat=sync_chat,
            stream_chat=lambda *args, **kwargs: iter(tokens),
            async_stream_chat=async_stream_chat or async_tokens,
            chat_max_tokens=lambda performance_mode: 1000,
        )
    )
    original_start_turn = service.start_turn
    plan_marker = dict(effective_plan)

    def gated_start_turn(command: Any) -> Any:
        prepared = original_start_turn(command)
        route = prepared.route
        if deny_web_policy:
            route = {**route, "external_data_policy": {"web_allowed": False}}
        prepared = replace(prepared, route=route)
        return replace(
            prepared,
            answer_validation={
                "evidence_rows": plan_marker["evidence_rows"],
                "allowed_attempts": plan_marker["allowed_attempts"],
            },
        )

    service.start_turn = gated_start_turn
    return service


class _FakeRagResult:
    context = ""

    def to_dict(self) -> dict[str, Any]:
        return {"status": "skipped", "context": "", "result_count": 0}


async def _consume(
    service,
    research_service,
    session_service,
    session_id: str,
    *,
    user_input: str = "该版本发布了吗？",
    http_request: Any | None = None,
    turn_id: str | None = None,
) -> str:
    response = await chat_stream_endpoint(
        ChatRequest(
            user_input=user_input,
            session_id=session_id,
            turn_id=turn_id,
        ),
        http_request or ConnectedRequest(),
        service,
        research_service,
        session_service,
    )
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


def test_research_stream_passes_binding_and_flushes_once(runtime_test_context) -> None:
    candidate = "该版本已正式发布。"
    service = _service(
        runtime_test_context,
        tokens=("该版本已正式", "发布。"),
        binding_json=_payload(),
    )
    body = asyncio.run(
        _consume(
            service,
            runtime_test_context.web_lookup_service,
            runtime_test_context.session_service,
            "stream-pass-session",
        )
    )
    assert body.count("event: token") == 1
    assert body.count(candidate) == 2
    assert body.index("event: done") > body.index(candidate)


def test_research_stream_binding_failure_emits_zero_candidate_tokens(
    runtime_test_context,
) -> None:
    candidate = "该版本已正式发布。"
    service = _service(
        runtime_test_context,
        tokens=("该版本已正式", "发布。"),
        binding_json="",
        refuse_binding=True,
    )
    body = asyncio.run(
        _consume(
            service,
            runtime_test_context.web_lookup_service,
            runtime_test_context.session_service,
            "stream-reject-session",
        )
    )
    assert candidate not in body
    assert RESEARCH_ANSWER_BLOCKED_COPY in body
    assert "event: done" in body


def test_plain_stream_keeps_emitting_tokens_immediately(runtime_test_context) -> None:
    service = runtime_test_context.override_chat(
        ChatDependencies(
            load_runtime_modes=lambda: RuntimeModes(performance_mode="fast"),
            read_memory_bundle=lambda context_mode: {},
            build_role_prompt=lambda role, **kwargs: f"role prompt for {role}",
            route_request=route_request,
            retrieve_local_knowledge=lambda *args, **kwargs: _FakeRagResult(),
            build_messages=build_messages,
            chat=lambda *args, **kwargs: "unused",
            stream_chat=lambda *args, **kwargs: iter(("part", " two")),
            async_stream_chat=lambda *args, **kwargs: _async_iter(("part", " two")),
            chat_max_tokens=lambda performance_mode: 1000,
        )
    )
    body = asyncio.run(
        _consume(
            service,
            runtime_test_context.web_lookup_service,
            runtime_test_context.session_service,
            "plain-stream-session",
        )
    )
    assert "event: token" in body
    assert "part" in body and " two" in body
    assert "event: done" in body


def test_policy_denied_turn_streams_tokens_immediately(runtime_test_context) -> None:
    candidate = "该版本已正式发布。"
    service = _service(
        runtime_test_context,
        tokens=("该版本已正式", "发布。"),
        binding_json="",
        deny_web_policy=True,
    )
    body = asyncio.run(
        _consume(
            service,
            runtime_test_context.web_lookup_service,
            runtime_test_context.session_service,
            "policy-denied-stream-session",
        )
    )
    assert body.count("event: token") >= 2
    assert candidate in body
    assert "event: done" in body
    assert RESEARCH_ANSWER_BLOCKED_COPY not in body


def test_research_stream_disconnect_discards_unvalidated_partial(
    runtime_test_context,
) -> None:
    candidate = "未验证候选"

    async def partial_then_block(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
        yield candidate
        await asyncio.Event().wait()

    service = _service(
        runtime_test_context,
        tokens=(),
        binding_json=_payload(),
        async_stream_chat=partial_then_block,
    )

    async def scenario() -> str:
        return await asyncio.wait_for(
            _consume(
                service,
                runtime_test_context.web_lookup_service,
                runtime_test_context.session_service,
                "research-disconnect-session",
                http_request=DisconnectedRequest(),
            ),
            timeout=1,
        )

    body = asyncio.run(scenario())
    turns = runtime_test_context.repository.list_chat_turns(
        "research-disconnect-session"
    )

    assert candidate not in body
    assert "event: done" not in body
    assert len(turns) == 1
    assert turns[0].status == "interrupted"
    assert turns[0].assistant_message == ""


def test_research_stream_cancel_discards_unvalidated_partial(
    runtime_test_context,
) -> None:
    candidate = "未验证候选"
    turn_id = "research-cancel-turn"

    class DisconnectOnceCancelled:
        async def is_disconnected(self) -> bool:
            turn = runtime_test_context.repository.get_chat_turn(turn_id)
            return turn is not None and turn.cancel_requested_at is not None

    async def partial_then_cancel(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
        yield candidate
        turn = runtime_test_context.repository.get_chat_turn(turn_id)
        assert turn is not None
        runtime_test_context.repository.request_turn_cancel(
            turn_id,
            expected_operation_id=turn.operation_id,
        )
        await asyncio.Event().wait()

    service = _service(
        runtime_test_context,
        tokens=(),
        binding_json=_payload(),
        async_stream_chat=partial_then_cancel,
    )

    async def scenario() -> str:
        return await asyncio.wait_for(
            _consume(
                service,
                runtime_test_context.web_lookup_service,
                runtime_test_context.session_service,
                "research-cancel-session",
                http_request=DisconnectOnceCancelled(),
                turn_id=turn_id,
            ),
            timeout=1,
        )

    body = asyncio.run(scenario())
    turn = runtime_test_context.repository.get_chat_turn(turn_id)

    assert candidate not in body
    assert "event: cancelled" in body
    assert '"partial": ""' in body
    assert turn is not None
    assert turn.status == "cancelled"
    assert turn.assistant_message == ""


def test_research_stream_processes_cancel_while_binder_runs_off_loop(
    runtime_test_context,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    turn_id = "research-cancel-during-binder-turn"

    def blocking_binding() -> str:
        entered.set()
        if not release.wait(timeout=1):
            raise AssertionError("event loop did not process binder cancellation")
        return _payload()

    service = _service(
        runtime_test_context,
        tokens=("该版本已正式发布。",),
        binding_json=_payload(),
        binding_model=blocking_binding,
    )

    async def scenario() -> str:
        consume_task = asyncio.create_task(
            _consume(
                service,
                runtime_test_context.web_lookup_service,
                runtime_test_context.session_service,
                "research-cancel-during-binder-session",
                turn_id=turn_id,
            )
        )
        assert await asyncio.to_thread(entered.wait, 0.5)
        turn = runtime_test_context.repository.get_chat_turn(turn_id)
        assert turn is not None
        outcome, _ = runtime_test_context.repository.request_turn_cancel(
            turn_id,
            expected_operation_id=turn.operation_id,
        )
        assert outcome == "accepted"
        release.set()
        return await asyncio.wait_for(consume_task, timeout=1)

    body = asyncio.run(scenario())
    turn = runtime_test_context.repository.get_chat_turn(turn_id)

    assert "event: cancelled" in body
    assert '"partial": ""' in body
    assert turn is not None
    assert turn.status == "cancelled"
    assert turn.assistant_message == ""


def test_continuation_cancel_before_generation_skips_binder(
    runtime_test_context,
) -> None:
    session_id = "research-cancel-before-continuation-session"
    turn_id = "research-cancel-before-continuation-turn"
    partial = "旧的已发布片段"
    binder_calls = 0

    def binding_model() -> str:
        nonlocal binder_calls
        binder_calls += 1
        return _payload()

    def provider_must_not_run(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
        raise AssertionError("continuation provider ran after cancellation")

    service = _service(
        runtime_test_context,
        tokens=(),
        binding_json=_payload(),
        async_stream_chat=provider_must_not_run,
        binding_model=binding_model,
    )

    first = service.start_turn(
        ChatCommand(
            user_input="该版本发布了吗？",
            thread_id=session_id,
            turn_id=turn_id,
        )
    )
    assert list(service.stream(first)) == []
    interrupted = service.interrupt_turn(first, partial)
    assert interrupted.status == "interrupted"
    assert interrupted.route_snapshot["answer_generation_calls"] == 1

    original_start_turn = service.start_turn

    def cancel_after_continuation_start(command: Any) -> Any:
        prepared = original_start_turn(command)
        if getattr(command, "continuation_of_turn_id", None):
            outcome, _ = runtime_test_context.repository.request_turn_cancel(
                prepared.turn.id,
                expected_operation_id=prepared.turn.operation_id or "",
            )
            assert outcome == "accepted"
        return prepared

    service.start_turn = cancel_after_continuation_start

    async def scenario() -> str:
        response = await chat_stream_endpoint(
            ChatRequest(
                user_input="该版本发布了吗？",
                session_id=session_id,
                turn_id=turn_id,
                continuation_of_turn_id=turn_id,
                partial_reply=partial,
            ),
            ConnectedRequest(),
            service,
            runtime_test_context.web_lookup_service,
            runtime_test_context.session_service,
        )
        chunks: list[str] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    body = asyncio.run(scenario())
    stored = runtime_test_context.repository.get_chat_turn(turn_id)

    assert binder_calls == 0
    assert "event: cancelled" in body
    assert "event: done" not in body
    assert stored is not None
    assert stored.status == "interrupted"
    assert stored.assistant_message == partial
    assert stored.route_snapshot["answer_generation_calls"] == 1


async def _async_iter(values: tuple[str, ...]) -> AsyncIterator[str]:
    for value in values:
        yield value

def test_simple_mode_streams_markdown_without_calling_the_binder(
    runtime_test_context, monkeypatch
) -> None:
    """The default mode must publish what streamed, not re-verify it.

    The binder is wired to refuse, so any binder call would replace the answer:
    the candidate surviving the final event proves no binder ran.
    """

    monkeypatch.delenv("RESEARCH_PUBLICATION_MODE", raising=False)
    candidate = "## 结论\n\n4 个 worker 竞争写锁，保持短事务。"
    service = _service(
        runtime_test_context,
        tokens=("## 结论\n\n", "4 个 worker 竞争写锁，保持短事务。"),
        binding_json="",
        refuse_binding=True,
    )
    body = asyncio.run(
        _consume(
            service,
            runtime_test_context.web_lookup_service,
            runtime_test_context.session_service,
            "stream-simple-session",
        )
    )
    final = json.loads(
        [line for line in body.split("event: done", 1)[-1].splitlines()
         if line.startswith("data: ")][-1][6:]
    )
    assert final["reply"] == candidate
    assert final["reply"].startswith("## 结论")


def test_simple_mode_stream_still_rejects_an_unread_citation(
    runtime_test_context, monkeypatch
) -> None:
    """Streaming is not an exemption: the gate runs on the complete answer."""

    monkeypatch.delenv("RESEARCH_PUBLICATION_MODE", raising=False)
    service = _service(
        runtime_test_context,
        tokens=("见[备份](https://official.example/backup)。",),
        binding_json="",
        refuse_binding=True,
    )
    body = asyncio.run(
        _consume(
            service,
            runtime_test_context.web_lookup_service,
            runtime_test_context.session_service,
            "stream-simple-unread-session",
        )
    )
    final = json.loads(
        [line for line in body.split("event: done", 1)[-1].splitlines()
         if line.startswith("data: ")][-1][6:]
    )
    assert final["reply"] == RESEARCH_ANSWER_BLOCKED_COPY
    assert "/backup" not in final["reply"]
