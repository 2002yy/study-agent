from __future__ import annotations

import sqlite3

import pytest

from src.domain.runtime_entities import GroupMessage, GroupThread
from src.infrastructure.sqlite.database import MIGRATIONS, RuntimeDatabase
from src.repositories.group_repository import GroupRepository


def _repository(tmp_path) -> GroupRepository:
    return GroupRepository(RuntimeDatabase(tmp_path / "runtime.db"))


def test_v4_migration_backfills_group_runtime_columns(tmp_path):
    db_path = tmp_path / "runtime.db"
    with sqlite3.connect(db_path) as connection:
        for _, migration in MIGRATIONS[:3]:
            connection.executescript(migration)
        connection.execute(
            "INSERT INTO runtime_meta(key, value) VALUES('schema_version', '3')"
        )
        connection.execute(
            """
            INSERT INTO group_threads(id, status, title, created_at, version)
            VALUES ('group-old', 'active', 'Old', 'created', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO group_messages(id, thread_id, speaker, content, status, created_at)
            VALUES ('message-old', 'group-old', 'user', 'hello', 'committed', 'message-created')
            """
        )

    RuntimeDatabase(db_path).initialize()

    with sqlite3.connect(db_path) as connection:
        thread = connection.execute(
            "SELECT updated_at, settings_snapshot, unread_count FROM group_threads"
        ).fetchone()
        message = connection.execute(
            "SELECT updated_at, message_type, error FROM group_messages"
        ).fetchone()

    assert thread == ("created", "{}", 0)
    assert message == ("message-created", "chat", "")


def test_group_threads_keep_messages_isolated(tmp_path):
    repository = _repository(tmp_path)
    first = repository.create_thread(GroupThread(id="group-a", title="A"))
    second = repository.create_thread(GroupThread(id="group-b", title="B"))
    repository.add_message(
        GroupMessage(thread_id=first.id, speaker="user", content="only A")
    )
    repository.add_message(
        GroupMessage(thread_id=second.id, speaker="nahida", content="only B")
    )

    assert [message.content for message in repository.list_messages(first.id)] == [
        "only A"
    ]
    assert [message.content for message in repository.list_messages(second.id)] == [
        "only B"
    ]


def test_group_archive_requires_owner_and_blocks_writes(tmp_path):
    repository = _repository(tmp_path)
    thread = repository.create_thread(GroupThread(id="group-archive"))
    repository.add_message(
        GroupMessage(thread_id=thread.id, speaker="user", content="archive me")
    )

    locked = repository.begin_archive(thread.id, "archive-owner")

    assert locked.status == "archiving"
    with pytest.raises(ValueError, match="not writable"):
        repository.add_message(
            GroupMessage(thread_id=thread.id, speaker="user", content="late")
        )
    with pytest.raises(ValueError, match="ownership lost"):
        repository.finish_archive(thread.id, "stale-owner", tmp_path / "stale.md")

    archived = repository.finish_archive(
        thread.id, "archive-owner", tmp_path / "group.md"
    )
    assert archived.status == "archived"
    assert archived.archive_operation_id is None
