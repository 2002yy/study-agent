from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.api import app
from src.application.chat_service import ChatDependencies
from src.context_builder import build_messages
from src.mode_manager import RuntimeModes
from src.performance_budget import chat_max_tokens
from src.router import route_request


class FakeRagResult:
    context = ""

    def to_dict(self):
        return {"status": "skipped", "context": "", "result_count": 0}


def test_interruption_continuation_retry_restore_and_archive_e2e(runtime_test_context):
    calls = 0

    async def scripted_stream(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield "first partial"
            raise RuntimeError("first interruption")
        if calls == 2:
            yield " plus continuation"
            raise RuntimeError("second interruption")
        yield "replacement answer"

    runtime_test_context.override_chat(
        ChatDependencies(
            load_runtime_modes=lambda: RuntimeModes(performance_mode="fast"),
            read_memory_bundle=lambda context_mode: {},
            build_role_prompt=lambda role, **kwargs: f"role prompt for {role}",
            route_request=route_request,
            retrieve_local_knowledge=lambda *args, **kwargs: FakeRagResult(),
            build_messages=build_messages,
            chat=lambda *args, **kwargs: "unused",
            stream_chat=lambda *args, **kwargs: iter(()),
            async_stream_chat=scripted_stream,
            chat_max_tokens=chat_max_tokens,
        )
    )
    client = TestClient(app)
    session_id = "chat-lifecycle-e2e"

    first = client.post(
        "/chat/stream",
        json={"user_input": "question", "session_id": session_id},
    )
    assert first.status_code == 200
    assert "event: error" in first.text
    original = runtime_test_context.repository.list_chat_turns(session_id)[0]
    assert original.status == "interrupted"
    assert original.assistant_message == "first partial"

    continued = client.post(
        "/chat/stream",
        json={
            "user_input": "question",
            "session_id": session_id,
            "turn_id": original.id,
            "continuation_of_turn_id": original.id,
            "partial_reply": "first partial",
        },
    )
    assert continued.status_code == 200
    assert "event: error" in continued.text
    continued_turn = runtime_test_context.repository.get_chat_turn(original.id)
    assert continued_turn is not None
    assert continued_turn.status == "interrupted"
    assert continued_turn.assistant_message == "first partial plus continuation"

    retried = client.post(
        "/chat/stream",
        json={
            "user_input": "question",
            "session_id": session_id,
            "retry_of_turn_id": original.id,
        },
    )
    assert retried.status_code == 200
    assert "event: done" in retried.text
    turns = runtime_test_context.repository.list_chat_turns(session_id)
    assert len(turns) == 2
    assert turns[0].id == original.id
    assert turns[0].status == "superseded"
    assert turns[1].parent_turn_id == original.id
    assert turns[1].status == "completed"
    assert turns[1].assistant_message == "replacement answer"

    restored = client.get(f"/sessions/{session_id}")
    assert restored.status_code == 200
    detail = restored.json()
    assert [turn["status"] for turn in detail["turns"]] == [
        "superseded",
        "completed",
    ]
    assert detail["turns"][-1]["parent_turn_id"] == original.id
    assert detail["messages"][-1]["content"] == "replacement answer"

    archived_response = client.post(f"/sessions/{session_id}/archive")
    assert archived_response.status_code == 200
    archived = runtime_test_context.repository.get_chat_thread(session_id)
    assert archived is not None
    assert archived.status == "archived"
    archive_path = Path(archived.export_path)
    assert archive_path.is_file()
    archive_text = archive_path.read_text(encoding="utf-8")
    assert original.id in archive_text
    assert turns[1].id in archive_text
    assert "replacement answer" in archive_text
