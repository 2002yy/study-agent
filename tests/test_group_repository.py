from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

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
    with pytest.raises(ValueError, match="not archivable"):
        repository.begin_archive(thread.id, "archive-concurrent")
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


def test_group_operation_has_single_winner_and_stale_settle_is_rejected(tmp_path):
    repository = _repository(tmp_path)
    thread = repository.create_thread(GroupThread(id="group-concurrent"))
    barrier = Barrier(2)

    def acquire(operation_id: str) -> str:
        barrier.wait(timeout=5)
        try:
            repository.acquire_operation(thread.id, operation_id)
            return operation_id
        except ValueError:
            return ""

    with ThreadPoolExecutor(max_workers=2) as executor:
        winners = list(executor.map(acquire, ["operation-a", "operation-b"]))
    winner = next(item for item in winners if item)
    pending = GroupMessage(
        id="group-pending",
        thread_id=thread.id,
        speaker="群聊",
        status="streaming",
        operation_id=winner,
    )
    repository.start_exchange(None, pending)

    with pytest.raises(ValueError, match="ownership lost"):
        repository.settle_message(
            pending.id,
            operation_id="operation-stale",
            content="stale",
            status="committed",
        )

    stored = repository.get_message(pending.id)
    current_thread = repository.get_thread(thread.id)
    assert stored is not None and stored.status == "streaming"
    assert current_thread is not None and current_thread.active_operation_id == winner


def test_stale_group_operation_recovers_as_interrupted(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = GroupRepository(database)
    thread = repository.create_thread(GroupThread(id="group-recovery"))
    repository.acquire_operation(thread.id, "operation-old")
    repository.start_exchange(
        None,
        GroupMessage(
            id="message-old",
            thread_id=thread.id,
            speaker="群聊",
            status="streaming",
            operation_id="operation-old",
        ),
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE group_threads SET active_operation_started_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", thread.id),
        )

    recovered = GroupRepository(database)

    stored = recovered.get_message("message-old")
    current_thread = recovered.get_thread(thread.id)
    assert stored is not None and stored.status == "interrupted"
    assert current_thread is not None and current_thread.active_operation_id is None


@pytest.mark.parametrize("archive_exists", [True, False])
def test_stale_group_archive_recovers_from_reserved_path(tmp_path, archive_exists):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = GroupRepository(database)
    thread = repository.create_thread(GroupThread(id=f"group-archive-{archive_exists}"))
    path = tmp_path / "archives" / f"{thread.id}.md"
    repository.begin_archive(thread.id, "archive-old")
    repository.reserve_archive_path(thread.id, "archive-old", path)
    if archive_exists:
        path.parent.mkdir(parents=True)
        path.write_text("archive complete", encoding="utf-8")
    with database.connect() as connection:
        connection.execute(
            "UPDATE group_threads SET archive_started_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", thread.id),
        )

    recovered = GroupRepository(database).get_thread(thread.id)

    assert recovered is not None
    assert recovered.status == ("archived" if archive_exists else "active")
    assert recovered.archive_operation_id is None
    assert recovered.export_path == (str(path) if archive_exists else "")
