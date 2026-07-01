"""SQLite repositories for runtime entities."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.domain.runtime_entities import ChatThread, ChatTurn, utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_object(raw: str) -> dict[str, Any]:
    loaded = json.loads(raw or "{}")
    return loaded if isinstance(loaded, dict) else {}


class RuntimeRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()
        self.recover_stale_archives()
        self.recover_stale_chat_operations()

    def create_chat_thread(self, thread: ChatThread) -> ChatThread:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO chat_threads(
                    id, status, settings_snapshot, learning_state, created_at, updated_at,
                    archived_at, export_path, active_operation_id,
                    active_operation_started_at,
                    archive_operation_id, archive_started_at, version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread.id,
                    thread.status,
                    _dump(thread.settings_snapshot),
                    _dump(thread.learning_state),
                    thread.created_at,
                    thread.updated_at,
                    thread.archived_at,
                    thread.export_path,
                    thread.active_operation_id,
                    thread.active_operation_started_at,
                    thread.archive_operation_id,
                    thread.archive_started_at,
                    thread.version,
                ),
            )
        return thread

    def ensure_chat_thread(
        self,
        thread_id: str,
        *,
        settings_snapshot: dict[str, Any] | None = None,
    ) -> ChatThread:
        current = self.get_chat_thread(thread_id)
        if current is not None:
            if current.status != "active":
                raise ValueError(f"Chat thread is not writable: {thread_id}")
            if settings_snapshot is not None and settings_snapshot != current.settings_snapshot:
                return self.update_chat_thread_settings(thread_id, settings_snapshot)
            return current
        return self.create_chat_thread(
            ChatThread(id=thread_id, settings_snapshot=settings_snapshot or {})
        )

    def get_chat_thread(self, thread_id: str) -> ChatThread | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM chat_threads WHERE id = ?", (thread_id,)).fetchone()
        if row is None:
            return None
        return _chat_thread_from_row(row)

    def list_chat_threads(self, *, limit: int = 20) -> list[ChatThread]:
        safe_limit = max(1, min(limit, 100))
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chat_threads ORDER BY updated_at DESC, id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [_chat_thread_from_row(row) for row in rows]

    def update_chat_thread_settings(
        self,
        thread_id: str,
        settings_snapshot: dict[str, Any],
    ) -> ChatThread:
        updated_at = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE chat_threads
                SET settings_snapshot = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'active' AND active_operation_id IS NULL
                """,
                (_dump(settings_snapshot), updated_at, thread_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"Chat thread is not writable: {thread_id}")
        thread = self.get_chat_thread(thread_id)
        if thread is None:
            raise ValueError(f"Chat thread not found: {thread_id}")
        return thread

    def update_chat_thread_learning_state(
        self,
        thread_id: str,
        learning_state: dict[str, Any],
        *,
        operation_id: str,
    ) -> ChatThread:
        updated_at = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE chat_threads
                SET learning_state = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'active' AND active_operation_id = ?
                """,
                (_dump(learning_state), updated_at, thread_id, operation_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"Chat operation ownership lost: {operation_id}")
        thread = self.get_chat_thread(thread_id)
        if thread is None:
            raise ValueError(f"Chat thread not found: {thread_id}")
        return thread

    def archive_chat_thread(self, thread_id: str, *, export_path: str = "") -> ChatThread:
        operation_id = f"archive_{thread_id}"
        self.begin_archive_chat_thread(thread_id, operation_id=operation_id)
        return self.finish_archive_chat_thread(
            thread_id,
            operation_id=operation_id,
            export_path=export_path,
        )

    def begin_archive_chat_thread(self, thread_id: str, *, operation_id: str) -> ChatThread:
        updated_at = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE chat_threads
                SET status = 'archiving', archive_operation_id = ?,
                    archive_started_at = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'active' AND active_operation_id IS NULL
                """,
                (operation_id, updated_at, updated_at, thread_id),
            )
        if cursor.rowcount != 1:
            current = self.get_chat_thread(thread_id)
            if current is not None and current.status == "archived":
                return current
            if current is not None and current.status == "archiving":
                raise ValueError(f"Chat thread is already being archived: {thread_id}")
            if current is not None and current.active_operation_id:
                raise ValueError(f"Chat thread has an active operation: {thread_id}")
            raise ValueError(f"Chat thread not found or not writable: {thread_id}")
        thread = self.get_chat_thread(thread_id)
        if thread is None:
            raise ValueError(f"Chat thread not found: {thread_id}")
        return thread

    def finish_archive_chat_thread(
        self,
        thread_id: str,
        *,
        operation_id: str,
        export_path: str,
    ) -> ChatThread:
        updated_at = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE chat_threads
                SET status = 'archived', archived_at = ?, export_path = ?,
                    archive_operation_id = NULL, archive_started_at = NULL,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'archiving' AND archive_operation_id = ?
                """,
                (updated_at, export_path, updated_at, thread_id, operation_id),
            )
        if cursor.rowcount != 1:
            current = self.get_chat_thread(thread_id)
            if current is not None and current.status == "archived":
                return current
            raise ValueError(f"Chat thread is not being archived: {thread_id}")
        thread = self.get_chat_thread(thread_id)
        if thread is None:
            raise ValueError(f"Chat thread not found: {thread_id}")
        return thread

    def cancel_archive_chat_thread(self, thread_id: str, *, operation_id: str) -> ChatThread:
        updated_at = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE chat_threads
                SET status = 'active', archive_operation_id = NULL,
                    archive_started_at = NULL, export_path = '',
                    updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'archiving' AND archive_operation_id = ?
                """,
                (updated_at, thread_id, operation_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"Chat thread is not being archived: {thread_id}")
        thread = self.get_chat_thread(thread_id)
        if thread is None:
            raise ValueError(f"Chat thread not found: {thread_id}")
        return thread

    def reserve_archive_path(
        self,
        thread_id: str,
        *,
        operation_id: str,
        export_path: str,
    ) -> None:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE chat_threads
                SET export_path = ?
                WHERE id = ? AND status = 'archiving' AND archive_operation_id = ?
                """,
                (export_path, thread_id, operation_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"Archive operation ownership lost: {operation_id}")

    def recover_stale_archives(self, *, stale_after_seconds: int = 300) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        ).isoformat()
        updated_at = utc_now()
        recovered = 0
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, export_path FROM chat_threads
                WHERE status = 'archiving'
                  AND archive_started_at IS NOT NULL
                  AND archive_started_at < ?
                """,
                (cutoff,),
            ).fetchall()
            for row in rows:
                export_path = str(row["export_path"] or "")
                archive_exists = bool(export_path and Path(export_path).is_file())
                if archive_exists:
                    connection.execute(
                        """
                        UPDATE chat_threads
                        SET status = 'archived', archived_at = ?,
                            archive_operation_id = NULL, archive_started_at = NULL,
                            updated_at = ?, version = version + 1
                        WHERE id = ? AND status = 'archiving'
                        """,
                        (updated_at, updated_at, row["id"]),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE chat_threads
                        SET status = 'active', export_path = '',
                            archive_operation_id = NULL, archive_started_at = NULL,
                            updated_at = ?, version = version + 1
                        WHERE id = ? AND status = 'archiving'
                        """,
                        (updated_at, row["id"]),
                    )
                recovered += 1
        return recovered

    def acquire_chat_operation(
        self,
        thread_id: str,
        operation_id: str,
        *,
        settings_snapshot: dict[str, Any] | None = None,
    ) -> ChatThread:
        updated_at = utc_now()
        serialized_settings = (
            _dump(settings_snapshot) if settings_snapshot is not None else None
        )
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE chat_threads
                SET active_operation_id = ?, active_operation_started_at = ?,
                    settings_snapshot = CASE
                        WHEN ? IS NULL THEN settings_snapshot ELSE ?
                    END,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'active' AND active_operation_id IS NULL
                """,
                (
                    operation_id,
                    updated_at,
                    serialized_settings,
                    serialized_settings,
                    updated_at,
                    thread_id,
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"Chat thread already has an active operation: {thread_id}")
        thread = self.get_chat_thread(thread_id)
        if thread is None:
            raise ValueError(f"Chat thread not found: {thread_id}")
        return thread

    def release_chat_operation(self, thread_id: str, operation_id: str) -> None:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE chat_threads
                SET active_operation_id = NULL, active_operation_started_at = NULL
                WHERE id = ? AND active_operation_id = ?
                """,
                (thread_id, operation_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"Chat operation ownership lost: {operation_id}")

    def recover_stale_chat_operations(self, *, stale_after_seconds: int = 300) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        ).isoformat()
        updated_at = utc_now()
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, active_operation_id FROM chat_threads
                WHERE status = 'active'
                  AND active_operation_id IS NOT NULL
                  AND active_operation_started_at IS NOT NULL
                  AND active_operation_started_at < ?
                """,
                (cutoff,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE chat_turns
                    SET status = 'interrupted', updated_at = ?
                    WHERE thread_id = ? AND operation_id = ?
                      AND status IN ('pending', 'streaming')
                    """,
                    (updated_at, row["id"], row["active_operation_id"]),
                )
                connection.execute(
                    """
                    UPDATE chat_threads
                    SET active_operation_id = NULL,
                        active_operation_started_at = NULL,
                        updated_at = ?, version = version + 1
                    WHERE id = ? AND active_operation_id = ?
                    """,
                    (updated_at, row["id"], row["active_operation_id"]),
                )
        return len(rows)

    def add_chat_turn(self, turn: ChatTurn) -> ChatTurn:
        with self.database.connect() as connection:
            _require_active_thread(connection, turn.thread_id)
            if turn.status in {"pending", "streaming"}:
                owner = connection.execute(
                    "SELECT active_operation_id FROM chat_threads WHERE id = ?",
                    (turn.thread_id,),
                ).fetchone()
                if owner is None or owner["active_operation_id"] != turn.operation_id:
                    raise ValueError(f"Chat operation ownership lost: {turn.operation_id}")
            connection.execute(
                """
                INSERT INTO chat_turns(
                    id, thread_id, user_message, assistant_message, status, role, mode, model,
                    route_snapshot, rag_snapshot, pedagogy_snapshot, parent_turn_id, operation_id,
                    conversation_instruction, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn.id,
                    turn.thread_id,
                    turn.user_message,
                    turn.assistant_message,
                    turn.status,
                    turn.role,
                    turn.mode,
                    turn.model,
                    _dump(turn.route_snapshot),
                    _dump(turn.rag_snapshot),
                    _dump(turn.pedagogy_snapshot),
                    turn.parent_turn_id,
                    turn.operation_id,
                    turn.conversation_instruction,
                    turn.created_at,
                    turn.updated_at,
                ),
            )
            connection.execute(
                """
                UPDATE chat_threads
                SET updated_at = ?, version = version + 1
                WHERE id = ?
                """,
                (turn.updated_at, turn.thread_id),
            )
        return turn

    def upsert_chat_turn(self, turn: ChatTurn) -> ChatTurn:
        with self.database.connect() as connection:
            _require_active_thread(connection, turn.thread_id)
            connection.execute(
                """
                INSERT INTO chat_turns(
                    id, thread_id, user_message, assistant_message, status, role, mode, model,
                    route_snapshot, rag_snapshot, pedagogy_snapshot, parent_turn_id, operation_id,
                    conversation_instruction, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    assistant_message = excluded.assistant_message,
                    status = excluded.status,
                    role = excluded.role,
                    mode = excluded.mode,
                    model = excluded.model,
                    route_snapshot = excluded.route_snapshot,
                    rag_snapshot = excluded.rag_snapshot,
                    pedagogy_snapshot = excluded.pedagogy_snapshot,
                    operation_id = excluded.operation_id,
                    conversation_instruction = excluded.conversation_instruction,
                    updated_at = excluded.updated_at
                """,
                (
                    turn.id,
                    turn.thread_id,
                    turn.user_message,
                    turn.assistant_message,
                    turn.status,
                    turn.role,
                    turn.mode,
                    turn.model,
                    _dump(turn.route_snapshot),
                    _dump(turn.rag_snapshot),
                    _dump(turn.pedagogy_snapshot),
                    turn.parent_turn_id,
                    turn.operation_id,
                    turn.conversation_instruction,
                    turn.created_at,
                    turn.updated_at,
                ),
            )
            connection.execute(
                """
                UPDATE chat_threads
                SET updated_at = ?, version = version + 1
                WHERE id = ?
                """,
                (turn.updated_at, turn.thread_id),
            )
        stored = self.get_chat_turn(turn.id)
        if stored is None:
            raise ValueError(f"Chat turn was not persisted: {turn.id}")
        return stored

    def update_chat_turn(
        self,
        turn_id: str,
        *,
        assistant_message: str,
        status: str,
        role: str | None = None,
        mode: str | None = None,
        model: str | None = None,
        route_snapshot: dict[str, Any] | None = None,
        rag_snapshot: dict[str, Any] | None = None,
        pedagogy_snapshot: dict[str, Any] | None = None,
        operation_id: str | None = None,
        expected_operation_id: str | None = None,
        enforce_operation_owner: bool = False,
        expected_status: str | None = None,
        release_operation: bool = False,
        supersede_parent_turn_id: str | None = None,
    ) -> ChatTurn | None:
        current = self.get_chat_turn(turn_id)
        if current is None:
            return None
        updated_at = utc_now()
        conditions = [
            "id = ?",
            "EXISTS (SELECT 1 FROM chat_threads "
            "WHERE chat_threads.id = chat_turns.thread_id "
            "AND chat_threads.status = 'active')",
        ]
        condition_values: list[Any] = [turn_id]
        if enforce_operation_owner:
            conditions.append("operation_id IS ?")
            condition_values.append(expected_operation_id)
        if expected_status is not None:
            conditions.append("status = ?")
            condition_values.append(expected_status)
        with self.database.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE chat_turns
                SET assistant_message = ?, status = ?, role = ?, mode = ?, model = ?,
                    route_snapshot = ?, rag_snapshot = ?, pedagogy_snapshot = ?,
                    operation_id = ?, updated_at = ?
                WHERE {' AND '.join(conditions)}
                """,
                (
                    assistant_message,
                    status,
                    current.role if role is None else role,
                    current.mode if mode is None else mode,
                    current.model if model is None else model,
                    _dump(current.route_snapshot if route_snapshot is None else route_snapshot),
                    _dump(current.rag_snapshot if rag_snapshot is None else rag_snapshot),
                    _dump(
                        current.pedagogy_snapshot
                        if pedagogy_snapshot is None
                        else pedagogy_snapshot
                    ),
                    current.operation_id if operation_id is None else operation_id,
                    updated_at,
                    *condition_values,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Chat turn operation ownership lost: {turn_id}")
            if supersede_parent_turn_id is not None:
                superseded = connection.execute(
                    """
                    UPDATE chat_turns
                    SET status = 'superseded', updated_at = ?
                    WHERE id = ? AND thread_id = ?
                      AND status IN ('interrupted', 'failed')
                    """,
                    (updated_at, supersede_parent_turn_id, current.thread_id),
                )
                if superseded.rowcount != 1:
                    raise ValueError(
                        f"Retry parent is not supersedable: {supersede_parent_turn_id}"
                    )
            connection.execute(
                """
                UPDATE chat_threads
                SET updated_at = ?, version = version + 1
                WHERE id = ?
                """,
                (updated_at, current.thread_id),
            )
            if release_operation:
                released = connection.execute(
                    """
                    UPDATE chat_threads
                    SET active_operation_id = NULL, active_operation_started_at = NULL
                    WHERE id = ? AND active_operation_id = ?
                    """,
                    (current.thread_id, expected_operation_id),
                )
                if released.rowcount != 1:
                    raise ValueError(
                        f"Chat operation ownership lost: {expected_operation_id}"
                    )
        return self.get_chat_turn(turn_id)

    def update_chat_turn_status(self, turn_id: str, *, status: str) -> ChatTurn:
        current = self.get_chat_turn(turn_id)
        if current is None:
            raise ValueError(f"Chat turn not found: {turn_id}")
        updated = self.update_chat_turn(
            turn_id,
            assistant_message=current.assistant_message,
            status=status,
        )
        if updated is None:
            raise ValueError(f"Chat turn not found: {turn_id}")
        return updated

    def complete_chat_turn_with_pedagogy(
        self,
        turn_id: str,
        *,
        assistant_message: str,
        learning_state: dict[str, Any],
        pedagogy_snapshot: dict[str, Any],
        route_snapshot: dict[str, Any],
        rag_snapshot: dict[str, Any],
        operation_id: str,
        supersede_parent_turn_id: str | None = None,
    ) -> ChatTurn:
        current = self.get_chat_turn(turn_id)
        if current is None:
            raise ValueError(f"Chat turn not found: {turn_id}")
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE chat_turns
                SET assistant_message = ?, status = 'completed',
                    route_snapshot = ?, rag_snapshot = ?,
                    pedagogy_snapshot = ?, updated_at = ?
                WHERE id = ? AND status = 'streaming' AND operation_id = ?
                """,
                (
                    assistant_message,
                    _dump(route_snapshot),
                    _dump(rag_snapshot),
                    _dump(pedagogy_snapshot),
                    now,
                    turn_id,
                    operation_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Chat turn operation ownership lost: {turn_id}")
            thread_cursor = connection.execute(
                """
                UPDATE chat_threads
                SET learning_state = ?, active_operation_id = NULL,
                    active_operation_started_at = NULL, updated_at = ?,
                    version = version + 1
                WHERE id = ? AND status = 'active' AND active_operation_id = ?
                """,
                (_dump(learning_state), now, current.thread_id, operation_id),
            )
            if thread_cursor.rowcount != 1:
                raise ValueError(f"Chat operation ownership lost: {operation_id}")
            if supersede_parent_turn_id is not None:
                superseded = connection.execute(
                    """
                    UPDATE chat_turns
                    SET status = 'superseded', updated_at = ?
                    WHERE id = ? AND thread_id = ?
                      AND status IN ('interrupted', 'failed')
                    """,
                    (now, supersede_parent_turn_id, current.thread_id),
                )
                if superseded.rowcount != 1:
                    raise ValueError(
                        f"Retry parent is not supersedable: {supersede_parent_turn_id}"
                    )
        completed = self.get_chat_turn(turn_id)
        if completed is None:
            raise ValueError(f"Chat turn not found after completion: {turn_id}")
        return completed

    def get_chat_turn(self, turn_id: str) -> ChatTurn | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM chat_turns WHERE id = ?", (turn_id,)).fetchone()
        if row is None:
            return None
        return _chat_turn_from_row(row)

    def list_chat_turns(self, thread_id: str) -> list[ChatTurn]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chat_turns WHERE thread_id = ? ORDER BY created_at, id",
                (thread_id,),
            ).fetchall()
        return [_chat_turn_from_row(row) for row in rows]

def _chat_turn_from_row(row: sqlite3.Row) -> ChatTurn:
    return ChatTurn(
        id=row["id"],
        thread_id=row["thread_id"],
        user_message=row["user_message"],
        assistant_message=row["assistant_message"],
        status=row["status"],
        role=row["role"],
        mode=row["mode"],
        model=row["model"],
        route_snapshot=_load_object(row["route_snapshot"]),
        rag_snapshot=_load_object(row["rag_snapshot"]),
        pedagogy_snapshot=_load_object(row["pedagogy_snapshot"]),
        parent_turn_id=row["parent_turn_id"],
        operation_id=row["operation_id"],
        conversation_instruction=row["conversation_instruction"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _chat_thread_from_row(row: sqlite3.Row) -> ChatThread:
    return ChatThread(
        id=row["id"],
        status=row["status"],
        settings_snapshot=_load_object(row["settings_snapshot"]),
        learning_state=_load_object(row["learning_state"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived_at=row["archived_at"],
        export_path=row["export_path"],
        active_operation_id=row["active_operation_id"],
        active_operation_started_at=row["active_operation_started_at"],
        archive_operation_id=row["archive_operation_id"],
        archive_started_at=row["archive_started_at"],
        version=row["version"],
    )


def _require_active_thread(connection: sqlite3.Connection, thread_id: str) -> None:
    row = connection.execute(
        "SELECT status FROM chat_threads WHERE id = ?",
        (thread_id,),
    ).fetchone()
    if row is None or row["status"] != "active":
        raise ValueError(f"Chat thread is not writable: {thread_id}")
