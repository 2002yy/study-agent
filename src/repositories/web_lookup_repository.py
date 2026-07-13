"""SQLite repository for durable, recoverable WebLookupRun results."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

from src.domain.runtime_entities import WebLookupRun, utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _stale_before(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=max(1, seconds))).isoformat()


class WebLookupRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()

    def create(self, run: WebLookupRun) -> WebLookupRun:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO web_lookup_runs(
                    id, query, stage, status, query_plan, attempts,
                    items, source_block, warnings, empty_reason, error,
                    max_items, active_operation_id, active_operation_started_at,
                    stage_started_at, version, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.query,
                    run.stage,
                    run.status,
                    _dump(run.query_plan),
                    _dump(run.attempts),
                    _dump(run.items),
                    run.source_block,
                    _dump(run.warnings),
                    run.empty_reason,
                    run.error,
                    run.max_items,
                    run.active_operation_id,
                    run.active_operation_started_at,
                    run.stage_started_at,
                    run.version,
                    run.created_at,
                    run.updated_at,
                    run.completed_at,
                ),
            )
        return run

    def get(self, run_id: str) -> WebLookupRun | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM web_lookup_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return _from_row(row) if row is not None else None

    def list(self, *, limit: int = 20) -> list[WebLookupRun]:
        safe_limit = max(1, min(limit, 100))
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM web_lookup_runs
                ORDER BY updated_at DESC, id DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def begin_search(
        self,
        run_id: str,
        *,
        operation_id: str,
        stale_after_seconds: int = 120,
    ) -> WebLookupRun:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET status = 'running', stage = 'searching',
                    items = '[]', source_block = '', warnings = '[]',
                    empty_reason = '', error = '', completed_at = NULL,
                    active_operation_id = ?, active_operation_started_at = ?,
                    stage_started_at = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND (
                    status IN ('pending', 'failed', 'empty') OR
                    (
                        status = 'running' AND
                        (
                            active_operation_started_at IS NULL OR
                            active_operation_started_at < ?
                        )
                    )
                )
                """,
                (
                    operation_id,
                    now,
                    now,
                    now,
                    run_id,
                    _stale_before(stale_after_seconds),
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"WebLookupRun is not searchable: {run_id}")
        return self._required(run_id)

    def complete_search(
        self,
        run_id: str,
        *,
        operation_id: str,
        items: list[dict[str, Any]],
        source_block: str,
        warnings: list[str],
        attempts: list[dict[str, Any]],
        empty_reason: str = "",
    ) -> WebLookupRun:
        now = utc_now()
        status = "completed" if items else "empty"
        stage = "completed" if items else "empty"
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET status = ?, stage = ?, items = ?, source_block = ?,
                    warnings = ?, attempts = ?, empty_reason = ?, error = '',
                    completed_at = ?, updated_at = ?, version = version + 1,
                    active_operation_id = NULL,
                    active_operation_started_at = NULL,
                    stage_started_at = NULL
                WHERE id = ? AND status = 'running'
                    AND active_operation_id = ?
                """,
                (
                    status,
                    stage,
                    _dump(items),
                    source_block,
                    _dump(warnings),
                    _dump(attempts),
                    empty_reason,
                    now,
                    now,
                    run_id,
                    operation_id,
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"WebLookupRun operation lost ownership: {run_id}")
        return self._required(run_id)

    def fail_search(
        self,
        run_id: str,
        *,
        operation_id: str,
        error: str,
        warnings: list[str],
        attempts: list[dict[str, Any]],
    ) -> WebLookupRun:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET status = 'failed', stage = 'failed', error = ?,
                    warnings = ?, attempts = ?, completed_at = ?,
                    updated_at = ?, version = version + 1,
                    active_operation_id = NULL,
                    active_operation_started_at = NULL,
                    stage_started_at = NULL
                WHERE id = ? AND status = 'running'
                    AND active_operation_id = ?
                """,
                (
                    error,
                    _dump(warnings),
                    _dump(attempts),
                    now,
                    now,
                    run_id,
                    operation_id,
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"WebLookupRun operation lost ownership: {run_id}")
        return self._required(run_id)

    # Compatibility methods for older application code.
    def complete(
        self,
        run_id: str,
        *,
        items: list[dict[str, Any]],
        source_block: str,
        warnings: list[str],
    ) -> WebLookupRun:
        run = self._required(run_id)
        operation_id = run.active_operation_id or "legacy"
        if run.status != "running":
            run = self.begin_search(run_id, operation_id=operation_id)
        return self.complete_search(
            run_id,
            operation_id=operation_id,
            items=items,
            source_block=source_block,
            warnings=warnings,
            attempts=run.attempts,
            empty_reason="" if items else "providers_returned_no_results",
        )

    def fail(self, run_id: str, error: str) -> WebLookupRun:
        run = self._required(run_id)
        operation_id = run.active_operation_id or "legacy"
        if run.status != "running":
            run = self.begin_search(run_id, operation_id=operation_id)
        return self.fail_search(
            run_id,
            operation_id=operation_id,
            error=error,
            warnings=run.warnings,
            attempts=run.attempts,
        )

    def _required(self, run_id: str) -> WebLookupRun:
        run = self.get(run_id)
        if run is None:
            raise ValueError(f"WebLookupRun not found: {run_id}")
        return run


def _from_row(row) -> WebLookupRun:
    keys = set(row.keys())
    return WebLookupRun(
        id=row["id"],
        query=row["query"],
        stage=row["stage"] if "stage" in keys else row["status"],
        status=row["status"],
        query_plan=json.loads(row["query_plan"] or "{}") if "query_plan" in keys else {},
        attempts=json.loads(row["attempts"] or "[]") if "attempts" in keys else [],
        items=json.loads(row["items"] or "[]"),
        source_block=row["source_block"],
        warnings=json.loads(row["warnings"] or "[]"),
        empty_reason=row["empty_reason"] if "empty_reason" in keys else "",
        error=row["error"],
        max_items=int(row["max_items"]) if "max_items" in keys else 8,
        active_operation_id=(row["active_operation_id"] if "active_operation_id" in keys else None),
        active_operation_started_at=(
            row["active_operation_started_at"]
            if "active_operation_started_at" in keys
            else None
        ),
        stage_started_at=row["stage_started_at"] if "stage_started_at" in keys else None,
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )
