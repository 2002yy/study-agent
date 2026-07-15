"""Durable thread-level summary status and source coverage."""

from __future__ import annotations

import sqlite3

from src.domain.runtime_entities import utc_now
from src.domain.thread_summary import ThreadSummaryState
from src.infrastructure.sqlite.database import RuntimeDatabase

_COMPONENT_NAME = "thread_summary"
_COMPONENT_SCHEMA_VERSION = 1


class ThreadSummaryRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_component_migrations (
                    component TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            row = connection.execute(
                "SELECT version FROM runtime_component_migrations WHERE component = ?",
                (_COMPONENT_NAME,),
            ).fetchone()
            current = int(row["version"]) if row else 0
            if current < 1:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS thread_summary_states (
                        thread_id TEXT PRIMARY KEY REFERENCES chat_threads(id),
                        status TEXT NOT NULL DEFAULT 'not_summarized',
                        source_thread_version INTEGER,
                        last_completed_turn_id TEXT,
                        closure_run_id TEXT,
                        summarized_at TEXT,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_thread_summary_status_updated
                    ON thread_summary_states(status, updated_at DESC)
                    """
                )
            connection.execute(
                """
                INSERT OR REPLACE INTO runtime_component_migrations(
                    component, version, applied_at
                ) VALUES (?, ?, ?)
                """,
                (_COMPONENT_NAME, _COMPONENT_SCHEMA_VERSION, utc_now()),
            )
            connection.commit()

    def get_effective(self, thread_id: str) -> ThreadSummaryState:
        legacy_completion: tuple[int, str] | None = None
        with self.database.connect() as connection:
            thread = connection.execute(
                "SELECT id FROM chat_threads WHERE id = ?", (thread_id,)
            ).fetchone()
            if thread is None:
                raise ValueError(f"Chat thread not found: {thread_id}")
            row = connection.execute(
                "SELECT * FROM thread_summary_states WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            latest_turn_id = self._latest_completed_turn_id(connection, thread_id)
            if row is None and latest_turn_id:
                legacy_completion = self._completed_closure_for_turn(
                    connection,
                    thread_id=thread_id,
                    last_completed_turn_id=latest_turn_id,
                )
        if row is None and legacy_completion is not None and latest_turn_id:
            source_version, closure_run_id = legacy_completion
            return self.mark_summarized(
                thread_id,
                source_thread_version=source_version,
                last_completed_turn_id=latest_turn_id,
                closure_run_id=closure_run_id,
            )
        if row is None:
            return ThreadSummaryState(
                thread_id=thread_id,
                current_last_completed_turn_id=latest_turn_id,
            )
        stored_status = str(row["status"])
        effective_status = stored_status
        if (
            stored_status == "summarized"
            and latest_turn_id != row["last_completed_turn_id"]
        ):
            effective_status = "needs_update"
        return ThreadSummaryState(
            thread_id=thread_id,
            status=effective_status,
            source_thread_version=row["source_thread_version"],
            last_completed_turn_id=row["last_completed_turn_id"],
            current_last_completed_turn_id=latest_turn_id,
            closure_run_id=row["closure_run_id"],
            summarized_at=row["summarized_at"],
            updated_at=row["updated_at"],
            version=int(row["version"]),
        )

    def assert_source_current(
        self,
        thread_id: str,
        *,
        last_completed_turn_id: str,
    ) -> None:
        with self.database.connect() as connection:
            thread = connection.execute(
                "SELECT status FROM chat_threads WHERE id = ?", (thread_id,)
            ).fetchone()
            if thread is None:
                raise ValueError(f"Chat thread not found: {thread_id}")
            if thread["status"] != "active":
                raise ValueError(f"Chat thread is not active: {thread_id}")
            latest = self._latest_completed_turn_id(connection, thread_id)
        if latest != last_completed_turn_id:
            raise ValueError(
                "Learning closure source changed; create a new closure run"
            )

    def mark_summarized(
        self,
        thread_id: str,
        *,
        source_thread_version: int,
        last_completed_turn_id: str,
        closure_run_id: str,
    ) -> ThreadSummaryState:
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            thread = connection.execute(
                "SELECT status FROM chat_threads WHERE id = ?", (thread_id,)
            ).fetchone()
            if thread is None:
                connection.rollback()
                raise ValueError(f"Chat thread not found: {thread_id}")
            if thread["status"] != "active":
                connection.rollback()
                raise ValueError(f"Chat thread is not active: {thread_id}")
            latest = self._latest_completed_turn_id(connection, thread_id)
            status = (
                "summarized"
                if latest == last_completed_turn_id
                else "needs_update"
            )
            existing = connection.execute(
                "SELECT version FROM thread_summary_states WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            next_version = int(existing["version"]) + 1 if existing else 1
            connection.execute(
                """
                INSERT INTO thread_summary_states(
                    thread_id, status, source_thread_version,
                    last_completed_turn_id, closure_run_id,
                    summarized_at, updated_at, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    status = excluded.status,
                    source_thread_version = excluded.source_thread_version,
                    last_completed_turn_id = excluded.last_completed_turn_id,
                    closure_run_id = excluded.closure_run_id,
                    summarized_at = excluded.summarized_at,
                    updated_at = excluded.updated_at,
                    version = excluded.version
                """,
                (
                    thread_id,
                    status,
                    source_thread_version,
                    last_completed_turn_id,
                    closure_run_id,
                    now,
                    now,
                    next_version,
                ),
            )
            connection.commit()
        return self.get_effective(thread_id)

    @staticmethod
    def _latest_completed_turn_id(
        connection: sqlite3.Connection,
        thread_id: str,
    ) -> str | None:
        row = connection.execute(
            """
            SELECT id FROM chat_turns
            WHERE thread_id = ? AND status = 'completed'
            ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (thread_id,),
        ).fetchone()
        return str(row["id"]) if row is not None else None

    @staticmethod
    def _completed_closure_for_turn(
        connection: sqlite3.Connection,
        *,
        thread_id: str,
        last_completed_turn_id: str,
    ) -> tuple[int, str] | None:
        table = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'learning_closure_runs'
            """
        ).fetchone()
        if table is None:
            return None
        row = connection.execute(
            """
            SELECT source_thread_version, id
            FROM learning_closure_runs
            WHERE thread_id = ? AND last_completed_turn_id = ?
              AND status = 'completed'
            ORDER BY completed_at DESC, updated_at DESC, id DESC
            LIMIT 1
            """,
            (thread_id, last_completed_turn_id),
        ).fetchone()
        if row is None:
            return None
        return int(row["source_thread_version"]), str(row["id"])
