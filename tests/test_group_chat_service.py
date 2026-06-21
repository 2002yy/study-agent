from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.application.group_chat_service import GroupChatService
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
    service.append_external_message(
        thread_id=thread.id,
        speaker="用户",
        content="RAG question",
        message_type="chat",
        unread=False,
    )
    service.append_external_message(
        thread_id=thread.id,
        speaker="纳西妲",
        content="RAG answer",
        message_type="chat",
        unread=True,
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


def test_failed_exchange_is_hidden_before_and_after_refresh(tmp_path):
    service, repository, _, _, _ = _service(tmp_path)
    thread = service.create_thread(title="Failure")
    prepared = service.prepare_message(
        "question that fails",
        thread_id=thread.id,
        model_profile="flash",
        relationship_mode="standard",
        performance_mode="fast",
        rag_enabled=False,
        rag_top_k=3,
        rag_retrieval_mode="hybrid",
        rag_min_score=0.0,
    )

    service.fail(prepared, "provider unavailable")

    assert service.get_state(thread.id)["content"] == ""
    reloaded, _, _, _, _ = _service(tmp_path)
    assert reloaded.get_state(thread.id)["content"] == ""
    messages = repository.list_messages(thread.id)
    assert [message.status for message in messages] == ["failed", "failed"]
    assert repository.get_thread(thread.id).active_operation_id is None


def test_four_role_reply_uses_rows_and_read_cursor(tmp_path):
    service, repository, _, _, _ = _service(tmp_path)
    thread = service.create_thread(title="Unread")
    service.append_external_message(
        thread_id=thread.id,
        speaker="纳西妲",
        content="old reply",
        message_type="chat",
        unread=True,
    )
    service.mark_read(thread.id)
    service.append_external_message(
        thread_id=thread.id,
        speaker="系统",
        content="news source metadata",
        message_type="news_source",
        unread=False,
    )
    prepared = service.prepare_message(
        "new question",
        thread_id=thread.id,
        model_profile="flash",
        relationship_mode="standard",
        performance_mode="fast",
        rag_enabled=False,
        rag_top_k=3,
        rag_retrieval_mode="hybrid",
        rag_min_score=0.0,
    )
    service.complete(
        prepared,
        "【纳西妲】\nA\n\n【三月七】\nB\n\n【晴】\nC\n\n【流萤】\nD",
    )

    state = service.get_state(thread.id)
    stored = repository.list_messages(thread.id)
    assert state["unread_count"] == 4
    assert state["unread"].count("【") == 4
    assert "old reply" not in state["unread"]
    assert "news source metadata" not in state["unread"]
    assert {message.speaker for message in stored[-4:]} == {
        "纳西妲",
        "三月七",
        "刻晴",
        "流萤",
    }


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
