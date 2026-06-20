from __future__ import annotations

from dataclasses import replace

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


def test_chat_service_rejects_missing_or_conflicting_continuation_target(tmp_path):
    service, repository = _service(tmp_path)

    with pytest.raises(ValueError, match="does not exist"):
        service.start_turn(
            ChatCommand(
                user_input="question",
                thread_id="chat_missing",
                continuation_of_turn_id="turn_missing",
            )
        )
    assert repository.get_chat_thread("chat_missing") is None

    with pytest.raises(ValueError, match="must match"):
        service.start_turn(
            ChatCommand(
                user_input="question",
                continuation_of_turn_id="turn_a",
                turn_id="turn_b",
            )
        )


def test_chat_service_non_stream_failure_moves_turn_to_failed(tmp_path):
    service, repository = _service(tmp_path)

    def fail_chat(*args, **kwargs):
        raise RuntimeError("provider timeout")

    service.dependencies = replace(service.dependencies, chat=fail_chat)
    prepared = service.start_turn(
        ChatCommand(user_input="question", thread_id="chat_failure")
    )

    with pytest.raises(RuntimeError, match="provider timeout"):
        service.generate(prepared)

    failed = repository.get_chat_turn(prepared.turn.id)
    assert failed is not None
    assert failed.status == "failed"


def test_chat_service_retry_records_parent_and_supersedes_it_on_success(tmp_path):
    service, repository = _service(tmp_path)
    first = service.start_turn(
        ChatCommand(user_input="question", thread_id="chat_retry")
    )
    service.interrupt_turn(first, "partial")

    retry = service.start_turn(
        ChatCommand(
            user_input="client copy is ignored",
            thread_id="chat_retry",
            retry_of_turn_id=first.turn.id,
        )
    )
    completed = service.complete_turn(retry, "replacement")

    original = repository.get_chat_turn(first.turn.id)
    assert retry.turn.parent_turn_id == first.turn.id
    assert retry.turn.user_message == "question"
    assert completed.status == "completed"
    assert original is not None
    assert original.status == "superseded"
    assert len(repository.list_chat_turns("chat_retry")) == 2


def test_chat_service_rejects_divergent_partial_instead_of_appending_suffix_twice(tmp_path):
    service, repository = _service(tmp_path)
    prepared = service.start_turn(
        ChatCommand(user_input="question", thread_id="chat_partial_conflict")
    )
    service.interrupt_turn(prepared, "stored partial")

    with pytest.raises(ValueError, match="conflicts"):
        service.start_turn(
            ChatCommand(
                user_input="question",
                thread_id="chat_partial_conflict",
                continuation_of_turn_id=prepared.turn.id,
                partial_reply="suffix only",
            )
        )

    stored = repository.get_chat_turn(prepared.turn.id)
    assert stored is not None
    assert stored.assistant_message == "stored partial"
    assert stored.status == "interrupted"


def test_chat_service_allows_only_one_active_turn_per_thread(tmp_path):
    service, repository = _service(tmp_path)
    first = service.start_turn(
        ChatCommand(user_input="first", thread_id="chat_single_active")
    )

    with pytest.raises(ValueError, match="active operation"):
        service.start_turn(
            ChatCommand(user_input="second", thread_id="chat_single_active")
        )

    service.interrupt_turn(first, "partial")
    second = service.start_turn(
        ChatCommand(user_input="second", thread_id="chat_single_active")
    )
    service.complete_turn(second, "answer")

    assert [turn.status for turn in repository.list_chat_turns("chat_single_active")] == [
        "interrupted",
        "completed",
    ]


def test_stale_operation_cannot_overwrite_continuation_owner(tmp_path):
    service, repository = _service(tmp_path)
    first = service.start_turn(
        ChatCommand(user_input="question", thread_id="chat_cas")
    )
    service.interrupt_turn(first, "partial")
    continuation = service.start_turn(
        ChatCommand(
            user_input="question",
            thread_id="chat_cas",
            continuation_of_turn_id=first.turn.id,
            partial_reply="partial",
        )
    )

    with pytest.raises(ValueError, match="ownership lost"):
        service.complete_turn(first, "stale suffix")

    completed = service.complete_turn(continuation, " fresh suffix")
    assert completed.assistant_message == "partial fresh suffix"
    assert repository.get_chat_thread("chat_cas").active_operation_id is None


def test_partial_commit_cannot_revive_superseded_turn(tmp_path):
    service, repository = _service(tmp_path)
    first = service.start_turn(
        ChatCommand(user_input="question", thread_id="chat_terminal_partial")
    )
    service.interrupt_turn(first, "old partial")
    retry = service.start_turn(
        ChatCommand(
            user_input="question",
            thread_id="chat_terminal_partial",
            retry_of_turn_id=first.turn.id,
        )
    )
    service.complete_turn(retry, "replacement")

    stored, changed = service.commit_partial_turn(
        thread_id="chat_terminal_partial",
        turn_id=first.turn.id,
        user_input="question",
        assistant_message="late partial",
        role="nahida",
        mode="普通",
        model="flash",
        route_snapshot={},
        rag_snapshot={},
        conversation_instruction="",
    )

    assert changed is False
    assert stored.status == "superseded"
    assert repository.get_chat_turn(first.turn.id).status == "superseded"
