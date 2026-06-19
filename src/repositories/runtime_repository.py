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
                INSERT INTO chat_threads(id, status, settings_snapshot, created_at, updated_at, version)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    thread.id,
                    thread.status,
                    _dump(thread.settings_snapshot),
                    thread.created_at,
                    thread.updated_at,
                    thread.version,
                ),
            )
        return thread

    def get_chat_thread(self, thread_id: str) -> ChatThread | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM chat_threads WHERE id = ?", (thread_id,)).fetchone()
        if row is None:
            return None
        return ChatThread(
            id=row["id"],
            status=row["status"],
            settings_snapshot=_load_object(row["settings_snapshot"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            version=row["version"],
        )

    def add_chat_turn(self, turn: ChatTurn) -> ChatTurn:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO chat_turns(
                    id, thread_id, user_message, assistant_message, status, role, mode, model,
                    route_snapshot, rag_snapshot, parent_turn_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    turn.created_at,
                    turn.updated_at,
                ),
            )
        return turn

    def update_chat_turn(self, turn_id: str, *, assistant_message: str, status: str) -> ChatTurn | None:
        updated_at = utc_now()
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE chat_turns
                SET assistant_message = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (assistant_message, status, updated_at, turn_id),
            )
        turn = self.get_chat_turn(turn_id)
        if turn is None:
            return None
        return replace(turn, assistant_message=assistant_message, status=status, updated_at=updated_at)

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
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
