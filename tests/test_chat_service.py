from __future__ import annotations

import pytest

from src.application.chat_service import ChatCommand, ChatDependencies, ChatService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.mode_manager import RuntimeModes
from src.repositories.runtime_repository import RuntimeRepository


class FakeRagResult:
    context = "local context"

    def to_dict(self):
        return {
            "status": "found",
            "context": self.context,
            "result_count": 1,
            "results": [],
        }


def _service(tmp_path) -> tuple[ChatService, RuntimeRepository]:
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    dependencies = ChatDependencies(
        load_runtime_modes=lambda: RuntimeModes(
            memory_mode="preview",
            performance_mode="standard",
        ),
        read_memory_bundle=lambda context_mode: {},
        build_role_prompt=lambda role, **kwargs: f"role:{role}",
        route_request=lambda **kwargs: {
            "role": "nahida",
            "mode": "普通",
            "model_profile": "flash",
            "reason": "test",
        },
        retrieve_local_knowledge=lambda *args, **kwargs: FakeRagResult(),
        build_messages=lambda **kwargs: [
            {"role": "system", "content": kwargs["role_prompt"]},
            {"role": "user", "content": kwargs["user_input"]},
        ],
        chat=lambda *args, **kwargs: "complete reply",
        stream_chat=lambda *args, **kwargs: iter(["part", " two"]),
        chat_max_tokens=lambda performance_mode: 1000,
    )
    return ChatService(repository, dependencies), repository


def test_chat_service_persists_pending_streaming_and_completed_turn(tmp_path):
    service, repository = _service(tmp_path)

    prepared = service.start_turn(
        ChatCommand(
            user_input="Explain RAG",
            selected_role="nahida",
            thread_id="chat_test",
            rag_enabled=True,
        )
    )
    streaming = repository.get_chat_turn(prepared.turn.id)
    reply = service.generate(prepared)
    completed = repository.get_chat_turn(prepared.turn.id)

    assert streaming is not None
    assert streaming.status == "streaming"
    assert streaming.operation_id
    assert reply == "complete reply"
    assert completed is not None
    assert completed.status == "completed"
    assert completed.assistant_message == "complete reply"
    assert len(repository.list_chat_turns("chat_test")) == 1


def test_chat_service_continuation_updates_the_same_interrupted_turn(tmp_path):
    service, repository = _service(tmp_path)
    first = service.start_turn(
        ChatCommand(user_input="question", thread_id="chat_continue")
    )
    interrupted = service.interrupt_turn(first, "partial ")

    continuation = service.start_turn(
        ChatCommand(
            user_input="question",
            thread_id="chat_continue",
            continuation_of_turn_id=first.turn.id,
            turn_id=first.turn.id,
            partial_reply="partial ",
        )
    )
    completed = service.complete_turn(continuation, "suffix")

    turns = repository.list_chat_turns("chat_continue")
    assert interrupted.status == "interrupted"
    assert completed.id == first.turn.id
    assert completed.assistant_message == "partial suffix"
    assert completed.status == "completed"
    assert len(turns) == 1


def test_chat_service_rejects_duplicate_or_completed_turn_reuse(tmp_path):
    service, _ = _service(tmp_path)
    prepared = service.start_turn(
        ChatCommand(user_input="question", thread_id="chat_reuse", turn_id="turn_fixed")
    )
    service.complete_turn(prepared, "done")

    with pytest.raises(ValueError, match="already exists"):
        service.start_turn(
            ChatCommand(user_input="new question", thread_id="chat_reuse", turn_id="turn_fixed")
        )
    with pytest.raises(ValueError, match="cannot be continued"):
        service.start_turn(
            ChatCommand(
                user_input="question",
                thread_id="chat_reuse",
                turn_id="turn_fixed",
                continuation_of_turn_id="turn_fixed",
                partial_reply="done",
            )
        )


def test_chat_service_partial_commit_is_idempotent_by_turn_id(tmp_path):
    service, repository = _service(tmp_path)

    first, first_changed = service.commit_partial_turn(
        thread_id="chat_partial",
        turn_id="turn_partial",
        user_input="question",
        assistant_message="partial",
        role="nahida",
        mode="普通",
        model="flash",
        route_snapshot={},
        rag_snapshot={},
        conversation_instruction="",
    )
    updated, updated_changed = service.commit_partial_turn(
        thread_id="chat_partial",
        turn_id="turn_partial",
        user_input="question",
        assistant_message="partial plus",
        role="nahida",
        mode="普通",
        model="flash",
        route_snapshot={},
        rag_snapshot={},
        conversation_instruction="",
    )
    duplicate, duplicate_changed = service.commit_partial_turn(
        thread_id="chat_partial",
        turn_id="turn_partial",
        user_input="question",
        assistant_message="partial plus",
        role="nahida",
        mode="普通",
        model="flash",
        route_snapshot={},
        rag_snapshot={},
        conversation_instruction="",
    )

    assert first_changed is True
    assert updated_changed is True
    assert duplicate_changed is False
    assert first.id == updated.id == duplicate.id
    assert updated.assistant_message == "partial plus"
    assert len(repository.list_chat_turns("chat_partial")) == 1


def test_chat_service_rejects_cross_thread_turn_reuse(tmp_path):
    service, repository = _service(tmp_path)
    prepared = service.start_turn(
        ChatCommand(user_input="question", thread_id="chat-owner-a", turn_id="turn-owned")
    )
    service.interrupt_turn(prepared, "partial")

    with pytest.raises(ValueError, match="different thread"):
        service.start_turn(
            ChatCommand(
                user_input="question",
                thread_id="chat-owner-b",
                turn_id="turn-owned",
                continuation_of_turn_id="turn-owned",
                partial_reply="partial",
            )
        )
    assert repository.get_chat_thread("chat-owner-b") is None
