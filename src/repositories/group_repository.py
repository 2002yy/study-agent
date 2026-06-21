"""SQLite repository for GroupThread and GroupMessage lifecycle state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.domain.runtime_entities import GroupMessage, GroupThread, utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_object(raw: str) -> dict[str, Any]:
    loaded = json.loads(raw or "{}")
    return loaded if isinstance(loaded, dict) else {}


class GroupRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()

    def create_thread(self, thread: GroupThread) -> GroupThread:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO group_threads(
                    id, status, title, created_at, archived_at, version,
                    updated_at, settings_snapshot, active_operation_id,
                    active_operation_started_at, unread_count,
                    archive_operation_id, archive_started_at, export_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread.id,
                    thread.status,
                    thread.title,
                    thread.created_at,
                    thread.archived_at,
                    thread.version,
                    thread.updated_at,
                    _dump(thread.settings_snapshot),
                    thread.active_operation_id,
                    thread.active_operation_started_at,
                    thread.unread_count,
                    thread.archive_operation_id,
                    thread.archive_started_at,
                    thread.export_path,
                ),
            )
        return thread

    def get_thread(self, thread_id: str) -> GroupThread | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM group_threads WHERE id = ?", (thread_id,)
            ).fetchone()
        return _thread_from_row(row) if row is not None else None

    def list_threads(self, *, limit: int = 20) -> list[GroupThread]:
        safe_limit = max(1, min(limit, 100))
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM group_threads
                ORDER BY updated_at DESC, id DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [_thread_from_row(row) for row in rows]

    def add_message(self, message: GroupMessage) -> GroupMessage:
        with self.database.connect() as connection:
            thread = connection.execute(
                "SELECT status FROM group_threads WHERE id = ?", (message.thread_id,)
            ).fetchone()
            if thread is None or thread["status"] != "active":
                raise ValueError(f"Group thread is not writable: {message.thread_id}")
            connection.execute(
                """
                INSERT INTO group_messages(
                    id, thread_id, speaker, content, status, created_at,
                    updated_at, message_type, operation_id, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id,
                    message.thread_id,
                    message.speaker,
                    message.content,
                    message.status,
                    message.created_at,
                    message.updated_at,
                    message.message_type,
                    message.operation_id,
                    message.error,
                ),
            )
            connection.execute(
                """
                UPDATE group_threads
                SET updated_at = ?, version = version + 1
                WHERE id = ?
                """,
                (message.updated_at, message.thread_id),
            )
        return message

    def list_messages(self, thread_id: str) -> list[GroupMessage]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM group_messages
                WHERE thread_id = ? ORDER BY created_at, id
                """,
                (thread_id,),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    def begin_archive(self, thread_id: str, operation_id: str) -> GroupThread:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE group_threads
                SET status = 'archiving', archive_operation_id = ?,
                    archive_started_at = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'active'
                  AND active_operation_id IS NULL
                """,
                (operation_id, now, now, thread_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"Group thread is not archivable: {thread_id}")
        return self._required_thread(thread_id)

    def finish_archive(
        self, thread_id: str, operation_id: str, export_path: Path | str
    ) -> GroupThread:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE group_threads
                SET status = 'archived', archived_at = ?, export_path = ?,
                    archive_operation_id = NULL, archive_started_at = NULL,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'archiving'
                  AND archive_operation_id = ?
                """,
                (now, str(export_path), now, thread_id, operation_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"Group archive ownership lost: {operation_id}")
        return self._required_thread(thread_id)

    def cancel_archive(self, thread_id: str, operation_id: str) -> GroupThread:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE group_threads
                SET status = 'active', archive_operation_id = NULL,
                    archive_started_at = NULL, updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'archiving'
                  AND archive_operation_id = ?
                """,
                (now, thread_id, operation_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"Group archive ownership lost: {operation_id}")
        return self._required_thread(thread_id)

    def _required_thread(self, thread_id: str) -> GroupThread:
        thread = self.get_thread(thread_id)
        if thread is None:
            raise ValueError(f"Group thread not found: {thread_id}")
        return thread


def _thread_from_row(row) -> GroupThread:
    return GroupThread(
        id=row["id"],
        status=row["status"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived_at=row["archived_at"],
        settings_snapshot=_load_object(row["settings_snapshot"]),
        active_operation_id=row["active_operation_id"],
        active_operation_started_at=row["active_operation_started_at"],
        unread_count=row["unread_count"],
        archive_operation_id=row["archive_operation_id"],
        archive_started_at=row["archive_started_at"],
        export_path=row["export_path"],
        version=row["version"],
    )


def _message_from_row(row) -> GroupMessage:
    return GroupMessage(
        id=row["id"],
        thread_id=row["thread_id"],
        speaker=row["speaker"],
        content=row["content"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        message_type=row["message_type"],
        operation_id=row["operation_id"],
        error=row["error"],
    )
