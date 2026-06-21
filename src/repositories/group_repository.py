"""SQLite repository for GroupThread and GroupMessage lifecycle state."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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
        self.recover_stale_operations()

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
                WHERE thread_id = ? ORDER BY rowid
                """,
                (thread_id,),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    def get_message(self, message_id: str) -> GroupMessage | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM group_messages WHERE id = ?", (message_id,)
            ).fetchone()
        return _message_from_row(row) if row is not None else None

    def acquire_operation(
        self,
        thread_id: str,
        operation_id: str,
        *,
        settings_snapshot: dict[str, Any] | None = None,
    ) -> GroupThread:
        now = utc_now()
        serialized = _dump(settings_snapshot) if settings_snapshot is not None else None
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE group_threads
                SET active_operation_id = ?, active_operation_started_at = ?,
                    settings_snapshot = CASE WHEN ? IS NULL
                        THEN settings_snapshot ELSE ? END,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'active'
                  AND active_operation_id IS NULL
                """,
                (operation_id, now, serialized, serialized, now, thread_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"Group thread already has an active operation: {thread_id}")
        return self._required_thread(thread_id)

    def start_exchange(
        self,
        user_message: GroupMessage | None,
        assistant_message: GroupMessage,
    ) -> GroupMessage:
        with self.database.connect() as connection:
            owner = connection.execute(
                """
                SELECT active_operation_id FROM group_threads
                WHERE id = ? AND status = 'active'
                """,
                (assistant_message.thread_id,),
            ).fetchone()
            if owner is None or owner["active_operation_id"] != assistant_message.operation_id:
                raise ValueError(
                    f"Group operation ownership lost: {assistant_message.operation_id}"
                )
            if user_message is not None:
                self._insert_message(connection, user_message)
            self._insert_message(connection, assistant_message)
            connection.execute(
                """
                UPDATE group_threads SET updated_at = ?, version = version + 1
                WHERE id = ?
                """,
                (assistant_message.updated_at, assistant_message.thread_id),
            )
        return assistant_message

    def settle_message(
        self,
        message_id: str,
        *,
        operation_id: str,
        content: str,
        status: str,
        error: str = "",
        unread_delta: int = 0,
    ) -> GroupMessage:
        now = utc_now()
        with self.database.connect() as connection:
            current = connection.execute(
                "SELECT thread_id FROM group_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            if current is None:
                raise ValueError(f"Group message not found: {message_id}")
            cursor = connection.execute(
                """
                UPDATE group_messages
                SET content = ?, status = ?, error = ?, updated_at = ?
                WHERE id = ? AND operation_id = ? AND status = 'streaming'
                """,
                (content, status, error, now, message_id, operation_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Group message operation ownership lost: {message_id}")
            released = connection.execute(
                """
                UPDATE group_threads
                SET active_operation_id = NULL,
                    active_operation_started_at = NULL,
                    unread_count = unread_count + ?,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND active_operation_id = ?
                """,
                (max(0, unread_delta), now, current["thread_id"], operation_id),
            )
            if released.rowcount != 1:
                raise ValueError(f"Group operation ownership lost: {operation_id}")
        stored = self.get_message(message_id)
        if stored is None:
            raise ValueError(f"Group message not found: {message_id}")
        return stored

    def mark_read(self, thread_id: str) -> GroupThread:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE group_threads
                SET unread_count = 0, updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'active'
                """,
                (now, thread_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"Group thread is not readable: {thread_id}")
        return self._required_thread(thread_id)

    def release_operation(self, thread_id: str, operation_id: str) -> None:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE group_threads
                SET active_operation_id = NULL, active_operation_started_at = NULL
                WHERE id = ? AND active_operation_id = ?
                """,
                (thread_id, operation_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"Group operation ownership lost: {operation_id}")

    def recover_stale_operations(self, *, stale_after_seconds: int = 300) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        ).isoformat()
        now = utc_now()
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, active_operation_id FROM group_threads
                WHERE status = 'active' AND active_operation_id IS NOT NULL
                  AND active_operation_started_at IS NOT NULL
                  AND active_operation_started_at < ?
                """,
                (cutoff,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE group_messages
                    SET status = 'interrupted', error = 'stale operation recovered',
                        updated_at = ?
                    WHERE thread_id = ? AND operation_id = ? AND status = 'streaming'
                    """,
                    (now, row["id"], row["active_operation_id"]),
                )
                connection.execute(
                    """
                    UPDATE group_threads
                    SET active_operation_id = NULL,
                        active_operation_started_at = NULL,
                        updated_at = ?, version = version + 1
                    WHERE id = ? AND active_operation_id = ?
                    """,
                    (now, row["id"], row["active_operation_id"]),
                )
        return len(rows)

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

    @staticmethod
    def _insert_message(connection, message: GroupMessage) -> None:
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
