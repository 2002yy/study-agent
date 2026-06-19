"""SQLite repositories for runtime entities."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from typing import Any

from src.domain.runtime_entities import ChatThread, ChatTurn, NewsRun, utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_object(raw: str) -> dict[str, Any]:
    loaded = json.loads(raw or "{}")
    return loaded if isinstance(loaded, dict) else {}


def _load_list(raw: str) -> list[dict[str, Any]]:
    loaded = json.loads(raw or "[]")
    return loaded if isinstance(loaded, list) else []


class RuntimeRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()

    def create_chat_thread(self, thread: ChatThread) -> ChatThread:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO chat_threads(
                    id, status, settings_snapshot, created_at, updated_at,
                    archived_at, export_path, version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread.id,
                    thread.status,
                    _dump(thread.settings_snapshot),
                    thread.created_at,
                    thread.updated_at,
                    thread.archived_at,
                    thread.export_path,
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
                WHERE id = ? AND status = 'active'
                """,
                (_dump(settings_snapshot), updated_at, thread_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"Chat thread is not writable: {thread_id}")
        thread = self.get_chat_thread(thread_id)
        if thread is None:
            raise ValueError(f"Chat thread not found: {thread_id}")
        return thread

    def archive_chat_thread(self, thread_id: str, *, export_path: str = "") -> ChatThread:
        updated_at = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE chat_threads
                SET status = 'archived', archived_at = ?, export_path = ?,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'active'
                """,
                (updated_at, export_path, updated_at, thread_id),
            )
        if cursor.rowcount != 1:
            current = self.get_chat_thread(thread_id)
            if current is not None and current.status == "archived":
                return current
            raise ValueError(f"Chat thread not found or not writable: {thread_id}")
        thread = self.get_chat_thread(thread_id)
        if thread is None:
            raise ValueError(f"Chat thread not found: {thread_id}")
        return thread

    def add_chat_turn(self, turn: ChatTurn) -> ChatTurn:
        with self.database.connect() as connection:
            _require_active_thread(connection, turn.thread_id)
            connection.execute(
                """
                INSERT INTO chat_turns(
                    id, thread_id, user_message, assistant_message, status, role, mode, model,
                    route_snapshot, rag_snapshot, parent_turn_id, operation_id,
                    conversation_instruction, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    route_snapshot, rag_snapshot, parent_turn_id, operation_id,
                    conversation_instruction, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    assistant_message = excluded.assistant_message,
                    status = excluded.status,
                    role = excluded.role,
                    mode = excluded.mode,
                    model = excluded.model,
                    route_snapshot = excluded.route_snapshot,
                    rag_snapshot = excluded.rag_snapshot,
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
        operation_id: str | None = None,
    ) -> ChatTurn | None:
        current = self.get_chat_turn(turn_id)
        if current is None:
            return None
        thread = self.get_chat_thread(current.thread_id)
        if thread is None or thread.status != "active":
            raise ValueError(f"Chat thread is not writable: {current.thread_id}")
        updated_at = utc_now()
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE chat_turns
                SET assistant_message = ?, status = ?, role = ?, mode = ?, model = ?,
                    route_snapshot = ?, rag_snapshot = ?, operation_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    assistant_message,
                    status,
                    current.role if role is None else role,
                    current.mode if mode is None else mode,
                    current.model if model is None else model,
                    _dump(current.route_snapshot if route_snapshot is None else route_snapshot),
                    _dump(current.rag_snapshot if rag_snapshot is None else rag_snapshot),
                    current.operation_id if operation_id is None else operation_id,
                    updated_at,
                    turn_id,
                ),
            )
            connection.execute(
                """
                UPDATE chat_threads
                SET updated_at = ?, version = version + 1
                WHERE id = ?
                """,
                (updated_at, current.thread_id),
            )
        return self.get_chat_turn(turn_id)

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

    def create_news_run(self, run: NewsRun) -> NewsRun:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO news_runs(
                    id, query, stage, status, safe_mode, items, digest, warnings,
                    group_thread_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.query,
                    run.stage,
                    run.status,
                    1 if run.safe_mode else 0,
                    _dump(run.items),
                    run.digest,
                    _dump(run.warnings),
                    run.group_thread_id,
                    run.created_at,
                    run.updated_at,
                ),
            )
        return run

    def update_news_run(
        self,
        run_id: str,
        *,
        stage: str,
        status: str,
        items: list[dict[str, Any]] | None = None,
        digest: str | None = None,
        warnings: list[str] | None = None,
        group_thread_id: str | None = None,
    ) -> NewsRun | None:
        current = self.get_news_run(run_id)
        if current is None:
            return None
        next_run = replace(
            current,
            stage=stage,
            status=status,
            items=current.items if items is None else items,
            digest=current.digest if digest is None else digest,
            warnings=current.warnings if warnings is None else warnings,
            group_thread_id=current.group_thread_id if group_thread_id is None else group_thread_id,
            updated_at=utc_now(),
        )
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE news_runs
                SET stage = ?, status = ?, items = ?, digest = ?, warnings = ?,
                    group_thread_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    next_run.stage,
                    next_run.status,
                    _dump(next_run.items),
                    next_run.digest,
                    _dump(next_run.warnings),
                    next_run.group_thread_id,
                    next_run.updated_at,
                    run_id,
                ),
            )
        return next_run

    def get_news_run(self, run_id: str) -> NewsRun | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM news_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return NewsRun(
            id=row["id"],
            query=row["query"],
            stage=row["stage"],
            status=row["status"],
            safe_mode=bool(row["safe_mode"]),
            items=_load_list(row["items"]),
            digest=row["digest"],
            warnings=list(json.loads(row["warnings"] or "[]")),
            group_thread_id=row["group_thread_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


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
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived_at=row["archived_at"],
        export_path=row["export_path"],
        version=row["version"],
    )


def _require_active_thread(connection: sqlite3.Connection, thread_id: str) -> None:
    row = connection.execute(
        "SELECT status FROM chat_threads WHERE id = ?",
        (thread_id,),
    ).fetchone()
    if row is None or row["status"] != "active":
        raise ValueError(f"Chat thread is not writable: {thread_id}")
