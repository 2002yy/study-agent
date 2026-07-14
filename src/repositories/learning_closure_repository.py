"""SQLite repository for durable LearningClosureRun state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3
from typing import Any

from src.domain.learning_closure import LearningClosureRun
from src.domain.runtime_entities import utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase

_COMPONENT_NAME = "learning_closure"
_COMPONENT_SCHEMA_VERSION = 1
_RUNNING_STATUSES = {"collecting", "generating", "committing"}


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_stale(run: LearningClosureRun, seconds: int) -> bool:
    started = _parse_timestamp(run.active_operation_started_at)
    if started is None:
        return True
    return started < datetime.now(timezone.utc) - timedelta(seconds=max(1, seconds))


class LearningClosureRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()
        self._ensure_schema()
        self.recover_stale_operations()

    def _ensure_schema(self) -> None:
        """Apply the component migration without changing legacy migration order."""

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
                    CREATE TABLE learning_closure_runs (
                        id TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL REFERENCES chat_threads(id),
                        source_thread_version INTEGER NOT NULL,
                        last_completed_turn_id TEXT NOT NULL,
                        source_hash TEXT NOT NULL UNIQUE,
                        closure_eligibility TEXT NOT NULL,
                        status TEXT NOT NULL,
                        committed_snapshot TEXT NOT NULL DEFAULT '{}',
                        generated_result TEXT NOT NULL DEFAULT '{}',
                        memory_run_id TEXT REFERENCES memory_runs(id),
                        error TEXT NOT NULL DEFAULT '',
                        reason TEXT NOT NULL DEFAULT '',
                        active_operation_id TEXT,
                        active_operation_started_at TEXT,
                        cancel_requested_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        completed_at TEXT,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX idx_learning_closure_thread_updated
                    ON learning_closure_runs(thread_id, updated_at DESC)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX idx_learning_closure_status_updated
                    ON learning_closure_runs(status, updated_at DESC)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX idx_learning_closure_active_operation
                    ON learning_closure_runs(active_operation_id)
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

    def create(self, run: LearningClosureRun) -> LearningClosureRun:
        try:
            with self.database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO learning_closure_runs(
                        id, thread_id, source_thread_version,
                        last_completed_turn_id, source_hash,
                        closure_eligibility, status, committed_snapshot,
                        generated_result, memory_run_id, error, reason,
                        active_operation_id, active_operation_started_at,
                        cancel_requested_at, created_at, updated_at,
                        completed_at, version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.id,
                        run.thread_id,
                        run.source_thread_version,
                        run.last_completed_turn_id,
                        run.source_hash,
                        run.closure_eligibility,
                        run.status,
                        _dump(run.committed_snapshot),
                        _dump(run.generated_result),
                        run.memory_run_id,
                        run.error,
                        run.reason,
                        run.active_operation_id,
                        run.active_operation_started_at,
                        run.cancel_requested_at,
                        run.created_at,
                        run.updated_at,
                        run.completed_at,
                        run.version,
                    ),
                )
        except sqlite3.IntegrityError:
            existing = self.find_by_source_hash(run.source_hash)
            if existing is not None:
                return existing
            raise
        return self._required(run.id)

    def get(self, run_id: str) -> LearningClosureRun | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM learning_closure_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return _from_row(row) if row is not None else None

    def find_by_source_hash(self, source_hash: str) -> LearningClosureRun | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM learning_closure_runs WHERE source_hash = ?",
                (source_hash,),
            ).fetchone()
        return _from_row(row) if row is not None else None

    def list(self, *, limit: int = 20) -> list[LearningClosureRun]:
        safe_limit = max(1, min(limit, 100))
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM learning_closure_runs
                ORDER BY updated_at DESC, id DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def begin_operation(
        self,
        run_id: str,
        *,
        operation_id: str,
        status: str,
        stale_after_seconds: int = 300,
    ) -> LearningClosureRun:
        if status not in {"collecting", "generating"}:
            raise ValueError(f"Invalid closure operation status: {status}")
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM learning_closure_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise ValueError(f"LearningClosureRun not found: {run_id}")
            run = _from_row(row)
            recoverable_running = run.status in {"collecting", "generating"} and _is_stale(
                run, stale_after_seconds
            )
            if run.status not in {"created", "failed", "cancelled"} and not recoverable_running:
                connection.rollback()
                raise ValueError(f"LearningClosureRun is not resumable: {run_id}")
            cursor = connection.execute(
                """
                UPDATE learning_closure_runs
                SET status = ?, active_operation_id = ?,
                    active_operation_started_at = ?, cancel_requested_at = NULL,
                    error = '', reason = '', completed_at = NULL,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND version = ?
                """,
                (status, operation_id, now, now, run_id, run.version),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise ValueError(f"LearningClosureRun acquisition conflicted: {run_id}")
            connection.commit()
        return self._required(run_id)

    def transition_to_generating(
        self, run_id: str, *, operation_id: str
    ) -> LearningClosureRun:
        run = self._required(run_id)
        self._assert_owner(run, operation_id, expected_status="collecting")
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE learning_closure_runs
                SET status = 'generating', updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'collecting' AND version = ?
                """,
                (now, run_id, run.version),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"LearningClosureRun stage transition conflicted: {run_id}")
        return self._required(run_id)

    def checkpoint_generated(
        self,
        run_id: str,
        *,
        operation_id: str,
        generated_result: dict[str, Any],
    ) -> LearningClosureRun:
        run = self._required(run_id)
        self._assert_owner(run, operation_id, expected_status="generating")
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE learning_closure_runs
                SET generated_result = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'generating' AND version = ?
                """,
                (_dump(generated_result), now, run_id, run.version),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"LearningClosureRun generation checkpoint conflicted: {run_id}")
        return self._required(run_id)

    def set_preview_ready(
        self,
        run_id: str,
        *,
        operation_id: str,
        memory_run_id: str,
    ) -> LearningClosureRun:
        run = self._required(run_id)
        self._assert_owner(run, operation_id, expected_status="generating")
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE learning_closure_runs
                SET status = 'preview_ready', memory_run_id = ?,
                    active_operation_id = NULL,
                    active_operation_started_at = NULL,
                    cancel_requested_at = NULL, error = '', reason = '',
                    updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'generating' AND version = ?
                """,
                (memory_run_id, now, run_id, run.version),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"LearningClosureRun preview transition conflicted: {run_id}")
        return self._required(run_id)

    def fail(
        self,
        run_id: str,
        *,
        operation_id: str,
        error: str,
        reason: str,
    ) -> LearningClosureRun:
        run = self._required(run_id)
        self._assert_owner(run, operation_id)
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE learning_closure_runs
                SET status = 'failed', error = ?, reason = ?,
                    active_operation_id = NULL,
                    active_operation_started_at = NULL,
                    completed_at = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND version = ?
                """,
                (error, reason, now, now, run_id, run.version),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"LearningClosureRun failure conflicted: {run_id}")
        return self._required(run_id)

    def request_cancel(self, run_id: str) -> LearningClosureRun:
        run = self._required(run_id)
        if run.status == "cancelled":
            return run
        if run.status in {"completed", "committing"}:
            raise ValueError(f"LearningClosureRun is not cancellable: {run_id}")
        now = utc_now()
        running = run.status in {"collecting", "generating"}
        next_status = run.status if running else "cancelled"
        completed_at = run.completed_at if running else now
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE learning_closure_runs
                SET status = ?, cancel_requested_at = ?, reason = 'user_cancelled',
                    completed_at = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND version = ?
                """,
                (next_status, now, completed_at, now, run_id, run.version),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"LearningClosureRun cancellation conflicted: {run_id}")
        return self._required(run_id)

    def cancel_requested(self, run_id: str, *, operation_id: str) -> bool:
        run = self._required(run_id)
        self._assert_owner(run, operation_id)
        return bool(run.cancel_requested_at)

    def finish_cancel(
        self, run_id: str, *, operation_id: str
    ) -> LearningClosureRun:
        run = self._required(run_id)
        self._assert_owner(run, operation_id)
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE learning_closure_runs
                SET status = 'cancelled', reason = 'user_cancelled',
                    active_operation_id = NULL,
                    active_operation_started_at = NULL,
                    completed_at = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND version = ?
                """,
                (now, now, run_id, run.version),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"LearningClosureRun cancel finalization conflicted: {run_id}")
        return self._required(run_id)

    def begin_commit(
        self, run_id: str, *, operation_id: str
    ) -> LearningClosureRun:
        run = self._required(run_id)
        if run.status == "completed":
            return run
        if run.status != "preview_ready" or not run.memory_run_id:
            raise ValueError(f"LearningClosureRun is not commit-ready: {run_id}")
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE learning_closure_runs
                SET status = 'committing', active_operation_id = ?,
                    active_operation_started_at = ?, error = '', reason = '',
                    updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'preview_ready' AND version = ?
                """,
                (operation_id, now, now, run_id, run.version),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"LearningClosureRun commit acquisition conflicted: {run_id}")
        return self._required(run_id)

    def complete_commit(
        self,
        run_id: str,
        *,
        operation_id: str,
        completed: bool,
        error: str = "",
        reason: str = "",
    ) -> LearningClosureRun:
        run = self._required(run_id)
        self._assert_owner(run, operation_id, expected_status="committing")
        now = utc_now()
        status = "completed" if completed else "failed"
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE learning_closure_runs
                SET status = ?, error = ?, reason = ?,
                    active_operation_id = NULL,
                    active_operation_started_at = NULL,
                    completed_at = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'committing' AND version = ?
                """,
                (status, error, reason, now, now, run_id, run.version),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"LearningClosureRun commit completion conflicted: {run_id}")
        return self._required(run_id)

    def recover_stale_operations(self, *, stale_after_seconds: int = 300) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=max(1, stale_after_seconds))
        ).isoformat()
        now = utc_now()
        placeholders = ", ".join("?" for _ in _RUNNING_STATUSES)
        with self.database.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE learning_closure_runs
                SET status = 'failed', reason = 'stale_operation_recovered',
                    error = CASE WHEN error = '' THEN 'Closure operation was interrupted' ELSE error END,
                    active_operation_id = NULL,
                    active_operation_started_at = NULL,
                    completed_at = ?, updated_at = ?, version = version + 1
                WHERE status IN ({placeholders})
                  AND active_operation_started_at IS NOT NULL
                  AND active_operation_started_at < ?
                """,
                (now, now, *_RUNNING_STATUSES, cutoff),
            )
        return cursor.rowcount

    def _required(self, run_id: str) -> LearningClosureRun:
        run = self.get(run_id)
        if run is None:
            raise ValueError(f"LearningClosureRun not found: {run_id}")
        return run

    @staticmethod
    def _assert_owner(
        run: LearningClosureRun,
        operation_id: str,
        *,
        expected_status: str | None = None,
    ) -> None:
        if run.active_operation_id != operation_id:
            raise ValueError(f"LearningClosureRun operation ownership lost: {operation_id}")
        if expected_status is not None and run.status != expected_status:
            raise ValueError(
                f"LearningClosureRun status conflict: {run.id} "
                f"({run.status} != {expected_status})"
            )


def _from_row(row) -> LearningClosureRun:
    return LearningClosureRun(
        id=row["id"],
        thread_id=row["thread_id"],
        source_thread_version=int(row["source_thread_version"]),
        last_completed_turn_id=row["last_completed_turn_id"],
        source_hash=row["source_hash"],
        closure_eligibility=row["closure_eligibility"],
        status=row["status"],
        committed_snapshot=dict(json.loads(row["committed_snapshot"] or "{}")),
        generated_result=dict(json.loads(row["generated_result"] or "{}")),
        memory_run_id=row["memory_run_id"],
        error=row["error"],
        reason=row["reason"],
        active_operation_id=row["active_operation_id"],
        active_operation_started_at=row["active_operation_started_at"],
        cancel_requested_at=row["cancel_requested_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        version=int(row["version"]),
    )
