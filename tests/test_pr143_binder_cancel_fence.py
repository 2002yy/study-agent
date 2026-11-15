from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any, AsyncIterator, Mapping, Sequence

import pytest

from src.api.models.chat import ChatRequest
from src.api.routes.chat_routes import chat_stream_endpoint
from src.application.answer_claim_binder import (
    AnswerClaimBindingRequest,
    AnswerClaimBindingRow,
    bind_answer_claims,
)
from src.application.chat_service import ChatDependencies
from src.context_builder import build_messages
from src.mode_manager import RuntimeModes
from src.router import route_request


CANDIDATE = "该版本已正式发布。"
EVIDENCE_ID = "evidence_cancel_fence"
CLAIM_ID = "claim_cancel_fence"


@pytest.fixture(autouse=True)
def _legacy_strict_publication_contract(monkeypatch):
    monkeypatch.setenv("RESEARCH_PUBLICATION_MODE", "strict")


class _FakeRagResult:
    context = ""

    def to_dict(self) -> dict[str, Any]:
        return {"status": "skipped", "context": "", "result_count": 0}


class _ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def _row() -> dict[str, Any]:
    return {
        "evidence_id": EVIDENCE_ID,
        "claim_id": CLAIM_ID,
        "title": "Official release",
        "url": "https://official.example/release",
        "source_role": "official_statement",
        "source_cluster_id": "cluster_cancel_fence",
        "relation": "supports",
        "strength": "strong",
        "locator": "paragraph 1",
        "anchored_spans": ("official confirmation",),
        "caveats": (),
    }


def _binder_payload() -> str:
    return json.dumps(
        {
            "refused": False,
            "segments": [
                {
                    "segment_ref": "s1",
                    "kind": "factual",
                    "research_claim_id": CLAIM_ID,
                    "status": "asserted",
                    "evidence_support": [EVIDENCE_ID],
                }
            ],
        },
        ensure_ascii=False,
    )


def test_before_model_call_control_flow_is_not_swallowed_or_retried() -> None:
    model_calls = 0
    checkpoints = 0

    class StopBinder(Exception):
        pass

    def before_model_call() -> None:
        nonlocal checkpoints
        checkpoints += 1
        raise StopBinder

    def model_fn(_messages: Sequence[Mapping[str, Any]]) -> str:
        nonlocal model_calls
        model_calls += 1
        return _binder_payload()

    with pytest.raises(StopBinder):
        bind_answer_claims(
            request=AnswerClaimBindingRequest(
                question="发布了吗？",
                final_answer=CANDIDATE,
                evidence_rows=(
                    AnswerClaimBindingRow(
                        evidence_id=EVIDENCE_ID,
                        claim_id=CLAIM_ID,
                        relation="supports",
                        strength="strong",
                    ),
                ),
            ),
            model_fn=model_fn,
            max_attempts=2,
            before_model_call=before_model_call,
        )

    assert checkpoints == 1
    assert model_calls == 0


def test_sse_cancel_after_worker_precheck_blocks_binder_provider_call(
    runtime_test_context,
) -> None:
    binder_calls = 0

    async def async_tokens(*_args: Any, **_kwargs: Any) -> AsyncIterator[str]:
        yield CANDIDATE

    def chat_fn(*_args: Any, **kwargs: Any) -> str:
        nonlocal binder_calls
        if kwargs.get("task_name") == "answer_claim_binding":
            binder_calls += 1
            return _binder_payload()
        return CANDIDATE

    service = runtime_test_context.override_chat(
        ChatDependencies(
            load_runtime_modes=lambda: RuntimeModes(performance_mode="fast"),
            read_memory_bundle=lambda _context_mode: {},
            build_role_prompt=lambda role, **_kwargs: f"role prompt for {role}",
            route_request=route_request,
            retrieve_local_knowledge=lambda *_args, **_kwargs: _FakeRagResult(),
            build_messages=build_messages,
            chat=chat_fn,
            stream_chat=lambda *_args, **_kwargs: iter((CANDIDATE,)),
            async_stream_chat=async_tokens,
            chat_max_tokens=lambda _performance_mode: 1000,
        )
    )

    original_start_turn = service.start_turn

    def gated_start_turn(command: Any) -> Any:
        prepared = original_start_turn(command)
        return replace(
            prepared,
            answer_validation={"evidence_rows": [_row()], "allowed_attempts": 1},
        )

    service.start_turn = gated_start_turn
    original_complete_turn = service.complete_turn

    def cancel_then_complete(prepared: Any, suffix: str) -> Any:
        outcome, _turn = runtime_test_context.repository.request_turn_cancel(
            prepared.turn.id,
            expected_operation_id=prepared.turn.operation_id or "",
        )
        assert outcome == "accepted"
        return original_complete_turn(prepared, suffix)

    service.complete_turn = cancel_then_complete

    async def scenario() -> str:
        response = await chat_stream_endpoint(
            ChatRequest(
                user_input="该版本发布了吗？",
                session_id="binder-cancel-fence-session",
                turn_id="binder-cancel-fence-turn",
            ),
            _ConnectedRequest(),
            service,
            runtime_test_context.web_lookup_service,
            runtime_test_context.session_service,
        )
        chunks: list[str] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    body = asyncio.run(scenario())
    turn = runtime_test_context.repository.get_chat_turn("binder-cancel-fence-turn")

    assert binder_calls == 0
    assert "event: cancelled" in body
    assert "event: error" not in body
    assert CANDIDATE not in body
    assert turn is not None
    assert turn.status == "cancelled"
    assert turn.route_snapshot["answer_generation_calls"] == 1
