from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from src.application.chat_service import (
    ChatCommand,
    ChatDependencies,
    TurnCancelled,
)
from src.context_builder import build_messages
from src.mode_manager import RuntimeModes
from src.router import route_request


CANDIDATE = "该版本已正式发布。"
EVIDENCE_ID = "evidence_sync_cancel"
CLAIM_ID = "claim_sync_cancel"


@pytest.fixture(autouse=True)
def _legacy_strict_publication_contract(monkeypatch):
    monkeypatch.setenv("RESEARCH_PUBLICATION_MODE", "strict")


class _FakeRagResult:
    context = ""

    def to_dict(self) -> dict[str, Any]:
        return {"status": "skipped", "context": "", "result_count": 0}


def _row() -> dict[str, Any]:
    return {
        "evidence_id": EVIDENCE_ID,
        "claim_id": CLAIM_ID,
        "title": "Official release",
        "url": "https://official.example/release",
        "source_role": "official_statement",
        "source_cluster_id": "cluster_sync_cancel",
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


def test_sync_cancel_after_binder_call_settles_as_cancelled(runtime_test_context) -> None:
    binder_calls = 0
    active_turn_id = ""
    active_operation_id = ""

    def chat_fn(*_args: Any, **kwargs: Any) -> str:
        nonlocal binder_calls
        if kwargs.get("task_name") == "answer_claim_binding":
            binder_calls += 1
            reserved = runtime_test_context.repository.get_chat_turn(active_turn_id)
            assert reserved is not None
            assert reserved.route_snapshot["answer_claim_binding_calls_started"] == 1
            outcome, _turn = runtime_test_context.repository.request_turn_cancel(
                active_turn_id,
                expected_operation_id=active_operation_id,
            )
            assert outcome == "accepted"
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
            chat_max_tokens=lambda _performance_mode: 1000,
        )
    )
    prepared = service.start_turn(
        ChatCommand(
            user_input="该版本发布了吗？",
            thread_id="sync-binder-cancel-session",
            turn_id="sync-binder-cancel-turn",
        )
    )
    active_turn_id = prepared.turn.id
    active_operation_id = prepared.turn.operation_id or ""
    prepared = replace(
        prepared,
        answer_validation={"evidence_rows": [_row()], "allowed_attempts": 1},
    )

    with pytest.raises(TurnCancelled) as exc_info:
        service.generate(prepared)

    turn = runtime_test_context.repository.get_chat_turn(prepared.turn.id)
    assert binder_calls == 1
    assert exc_info.value.stage == "complete_turn"
    assert turn is not None
    assert turn.status == "cancelled"
    assert turn.assistant_message == ""
    assert turn.route_snapshot["answer_generation_calls"] == 1
    assert turn.route_snapshot["answer_claim_binding_calls_started"] == 1
