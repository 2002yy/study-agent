from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.application.group_chat_service import GroupChatService
from src.domain.runtime_entities import GroupMessage
from src.infrastructure.markdown.group_archive import LEGACY_GROUP_THREAD_ID
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.group_repository import GroupRepository


def _service(tmp_path):
    group_file = tmp_path / "chat" / "wechat_group.md"
    unread_file = tmp_path / "chat" / "wechat_unread.md"
    state_file = tmp_path / "chat" / "wechat_state.md"
    repository = GroupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    service = GroupChatService(
        repository,
        group_file=group_file,
        unread_file=unread_file,
        state_file=state_file,
        archive_dir=tmp_path / "archive",
    )
    return service, repository, group_file, unread_file, state_file


def test_legacy_group_files_import_once_into_sqlite(tmp_path):
    service, repository, group_file, unread_file, state_file = _service(tmp_path)
    group_file.parent.mkdir(parents=True)
    group_file.write_text(
        "【用户】\n问题\n\n【纳西妲】\n回答\n",
        encoding="utf-8",
    )
    unread_file.write_text("【纳西妲】\n回答\n", encoding="utf-8")
    state_file.write_text(
        "- user_has_joined_group: true\n- mode: interactive_group\n",
        encoding="utf-8",
    )

    first = service.list_threads()
    group_file.write_text("【用户】\n不应重复导入\n", encoding="utf-8")
    second = service.list_threads()
    detail = service.get_thread(LEGACY_GROUP_THREAD_ID)

    assert [thread.id for thread in first] == [LEGACY_GROUP_THREAD_ID]
    assert [thread.id for thread in second] == [LEGACY_GROUP_THREAD_ID]
    assert detail is not None
    assert [message.content for message in detail["messages"]] == ["问题", "回答"]
    thread = repository.get_thread(LEGACY_GROUP_THREAD_ID)
    assert thread is not None
    assert thread.unread_count == 1
    assert thread.settings_snapshot == {
        "mode": "interactive_group",
        "user_has_joined_group": True,
    }


def test_create_get_list_and_archive_group_thread(tmp_path):
    service, _, _, _, _ = _service(tmp_path)
    thread = service.create_thread(
        title="Study Group", settings_snapshot={"relationship": "warm"}
    )

    detail = service.get_thread(thread.id)
    archived = service.archive_thread(thread.id)

    assert detail is not None and detail["messages"] == []
    assert [item.id for item in service.list_threads()] == [thread.id]
    assert archived.status == "archived"
    assert Path(archived.export_path).is_file()
    assert f"group_thread_id: {thread.id}" in Path(archived.export_path).read_text(
        encoding="utf-8"
    )


def test_archive_export_failure_restores_active_group_thread(tmp_path, monkeypatch):
    service, repository, _, _, _ = _service(tmp_path)
    thread = service.create_thread(title="Failure")

    def fail_export(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(service.exporter, "export_archive", fail_export)

    with pytest.raises(OSError, match="disk full"):
        service.archive_thread(thread.id)

    restored = repository.get_thread(thread.id)
    assert restored is not None
    assert restored.status == "active"
    assert restored.archive_operation_id is None


def test_group_unread_search_and_reset_are_thread_scoped(tmp_path):
    service, repository, _, _, _ = _service(tmp_path)
    thread = service.create_thread(title="First")
    operation_id = "operation-message"
    repository.acquire_operation(thread.id, operation_id)
    pending = GroupMessage(
        thread_id=thread.id,
        speaker="群聊",
        status="streaming",
        operation_id=operation_id,
    )
    repository.start_exchange(
        GroupMessage(thread_id=thread.id, speaker="用户", content="RAG question"),
        pending,
    )
    repository.settle_message(
        pending.id,
        operation_id=operation_id,
        content="【纳西妲】\nRAG answer",
        status="committed",
        unread_delta=1,
    )

    assert service.get_state(thread.id)["unread_count"] == 1
    assert service.search(thread.id, "RAG", 10) == [
        {"speaker": "用户", "text": "RAG question"},
        {"speaker": "纳西妲", "text": "RAG answer"},
    ]
    service.mark_read(thread.id)
    assert service.get_state(thread.id)["unread_count"] == 0

    created = service.reset(thread.id)
    archived = repository.get_thread(thread.id)
    assert archived is not None and archived.status == "archived"
    assert created.id != thread.id and created.status == "active"
    assert service.get_state(created.id)["content"] == ""


def test_failed_opening_can_retry_without_showing_failed_message(tmp_path):
    service, repository, _, _, _ = _service(tmp_path)
    thread = service.create_thread(title="Opening retry")

    def fail_opening(**kwargs):
        raise RuntimeError("provider unavailable")

    service.dependencies = replace(
        service.dependencies,
        generate_opening=fail_opening,
    )
    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.create_opening(
            thread_id=thread.id,
            role_hint="auto",
            relationship_mode="standard",
            performance_mode="fast",
            selected_model="flash",
        )

    assert service.get_state(thread.id)["content"] == ""
    service.dependencies = replace(
        service.dependencies,
        generate_opening=lambda **kwargs: "【纳西妲】\nretry works",
    )
    service.create_opening(
        thread_id=thread.id,
        role_hint="auto",
        relationship_mode="standard",
        performance_mode="fast",
        selected_model="flash",
    )

    messages = repository.list_messages(thread.id)
    assert [message.status for message in messages] == ["failed", "committed"]
    assert "retry works" in service.get_state(thread.id)["content"]
