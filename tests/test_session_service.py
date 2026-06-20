from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.application.session_service import SessionService
from src.domain.runtime_entities import ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository


def _service(tmp_path):
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    service = SessionService(
        repository,
        current_dir=tmp_path / "current",
        archive_dir=tmp_path / "sessions",
    )
    return service, repository


def test_active_unflushed_thread_is_listed_and_restored_from_sqlite(tmp_path):
    service, repository = _service(tmp_path)
    thread = service.create_session(
        {
            "selectedRole": "nahida",
            "contextMode": "deep",
            "conversationInstruction": "direct answer",
        }
    )
    repository.add_chat_turn(
        ChatTurn(
            id="turn_restore",
            thread_id=thread.id,
            user_message="question",
            assistant_message="answer",
            status="completed",
            role="nahida",
            mode="普通",
            model="flash",
            route_snapshot={"role": "nahida"},
            rag_snapshot={"result_count": 1},
            conversation_instruction="direct answer",
        )
    )

    rows = service.list_sessions()
    detail = service.get_session(thread.id)

    assert rows[0]["session_id"] == thread.id
    assert rows[0]["kind"] == "current"
    assert rows[0]["path"] == ""
    assert detail is not None
    assert detail["messages"] == [
        {
            "role": "user",
            "content": "question",
            "avatarRole": "user",
            "turnId": "turn_restore",
            "turnStatus": "completed",
            "parentTurnId": None,
        },
        {
            "role": "assistant",
            "content": "answer",
            "avatarRole": "nahida",
            "turnId": "turn_restore",
            "turnStatus": "completed",
            "parentTurnId": None,
        },
    ]
    assert detail["turns"][0]["turn_id"] == "turn_restore"
    assert detail["settings"]["contextMode"] == "deep"
    assert detail["conversation_instruction"] == "direct answer"


def test_flush_exports_mirror_and_archive_locks_thread(tmp_path):
    service, repository = _service(tmp_path)
    thread = service.create_session({})
    repository.add_chat_turn(
        ChatTurn(
            thread_id=thread.id,
            user_message="question",
            assistant_message="answer",
            status="completed",
            role="nahida",
        )
    )

    current_path = service.flush_session(thread.id)
    archived = service.archive_session(thread.id)

    assert current_path is not None
    assert not current_path.exists()
    assert archived is not None
    assert archived.status == "archived"
    assert archived.export_path
    assert "turn_id" in Path(archived.export_path).read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="not writable"):
        repository.add_chat_turn(
            ChatTurn(thread_id=thread.id, user_message="late write")
        )


def test_legacy_markdown_is_imported_once_into_sqlite(tmp_path):
    service, repository = _service(tmp_path)
    current_dir = tmp_path / "current"
    current_dir.mkdir()
    snapshot = {
        "turn_id": "turn_legacy_kept",
        "status": "interrupted",
        "messages": [
            {"role": "user", "content": "legacy question", "avatarRole": "user"},
            {"role": "assistant", "content": "legacy partial", "avatarRole": "firefly"},
        ],
        "settings": {"selectedRole": "firefly"},
        "route": {"role": "firefly", "mode": "普通"},
        "rag": {"result_count": 0},
        "conversation_instruction": "stay gentle",
    }
    legacy = current_dir / "legacy123.md"
    legacy.write_text(
        "\n".join(
            [
                "User: legacy question",
                "Agent: legacy partial",
                "```json session_turn",
                json.dumps(snapshot, ensure_ascii=False),
                "```",
            ]
        ),
        encoding="utf-8",
    )

    rows = service.list_sessions()
    rows_again = service.list_sessions()
    detail = service.get_session("legacy123")

    assert [row["session_id"] for row in rows] == ["legacy123"]
    assert [row["session_id"] for row in rows_again] == ["legacy123"]
    assert repository.get_chat_thread("legacy123") is not None
    assert len(repository.list_chat_turns("legacy123")) == 1
    assert detail is not None
    assert detail["turns"][0]["status"] == "interrupted"
    assert detail["turns"][0]["turn_id"] == "turn_legacy_kept"


def test_legacy_archive_wins_when_current_duplicate_exists(tmp_path):
    service, repository = _service(tmp_path)
    current_dir = tmp_path / "current"
    archive_dir = tmp_path / "sessions"
    current_dir.mkdir()
    archive_dir.mkdir()
    (current_dir / "duplicate.md").write_text(
        "User: stale\nAgent: stale answer\n",
        encoding="utf-8",
    )
    (archive_dir / "duplicate-archive.md").write_text(
        "# Session\n\n- session_id: duplicate\n\n**User**\nfinal\n\n**Agent**\nfinal answer\n\n---\n",
        encoding="utf-8",
    )

    service.list_sessions()

    thread = repository.get_chat_thread("duplicate")
    turns = repository.list_chat_turns("duplicate")
    assert thread is not None
    assert thread.status == "archived"
    assert len(turns) == 1
    assert turns[0].user_message == "final"


def test_archive_export_failure_restores_active_thread_and_current_mirror(tmp_path, monkeypatch):
    service, repository = _service(tmp_path)
    thread = service.create_session({})
    repository.add_chat_turn(
        ChatTurn(
            thread_id=thread.id,
            user_message="question",
            assistant_message="answer",
            status="completed",
        )
    )
    current_path = service.flush_session(thread.id)
    assert current_path is not None

    def fail_export(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(service.exporter, "export_archive", fail_export)

    with pytest.raises(OSError, match="disk full"):
        service.archive_session(thread.id)

    restored = repository.get_chat_thread(thread.id)
    assert restored is not None
    assert restored.status == "active"
    assert current_path.exists()


def test_archive_rejects_active_turn_and_releases_archive_lock(tmp_path):
    service, repository = _service(tmp_path)
    thread = service.create_session({})
    repository.acquire_chat_operation(thread.id, "chat-op")
    repository.add_chat_turn(
        ChatTurn(
            thread_id=thread.id,
            user_message="question",
            status="streaming",
            operation_id="chat-op",
        )
    )

    with pytest.raises(ValueError, match="active operation"):
        service.archive_session(thread.id)

    restored = repository.get_chat_thread(thread.id)
    assert restored is not None
    assert restored.status == "active"


def test_current_mirror_cleanup_failure_keeps_committed_archive(tmp_path, monkeypatch):
    service, repository = _service(tmp_path)
    thread = service.create_session({})
    repository.add_chat_turn(
        ChatTurn(
            thread_id=thread.id,
            user_message="question",
            assistant_message="answer",
            status="completed",
        )
    )
    current_path = service.flush_session(thread.id)
    assert current_path is not None
    original_unlink = Path.unlink

    def fail_current_unlink(path, *args, **kwargs):
        if path == current_path:
            raise PermissionError("current mirror is busy")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_current_unlink)

    archived = service.archive_session(thread.id)

    assert archived is not None
    assert archived.status == "archived"
    assert Path(archived.export_path).is_file()
    assert current_path.is_file()
    stored = repository.get_chat_thread(thread.id)
    assert stored is not None
    assert stored.export_path == archived.export_path
