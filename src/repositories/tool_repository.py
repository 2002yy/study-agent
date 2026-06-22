"""SQLite repository for server-owned ToolRun execution state."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from src.domain.runtime_entities import ToolRun, utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class ToolRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()
        self.recover_stale_operations()

    def create(self, run: ToolRun) -> ToolRun:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO tool_runs(
                    id, tool_name, args, args_hash, status, preview, result,
                    reason, elapsed_ms, version, active_operation_id,
                    active_operation_started_at, previewed_at, completed_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.tool_name,
                    _dump(run.args),
                    run.args_hash,
                    run.status,
                    _dump(run.preview),
                    _dump(run.result),
                    run.reason,
                    run.elapsed_ms,
                    run.version,
                    run.active_operation_id,
                    run.active_operation_started_at,
                    run.previewed_at,
                    run.completed_at,
                    run.created_at,
                    run.updated_at,
                ),
            )
        return run

    def get(self, run_id: str) -> ToolRun | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tool_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return _from_row(row) if row is not None else None

    def list(self, *, limit: int = 20) -> list[ToolRun]:
        safe_limit = max(1, min(limit, 100))
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tool_runs ORDER BY updated_at DESC, id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def acquire_call(self, run_id: str, operation_id: str) -> ToolRun:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tool_runs
                SET status = 'running', active_operation_id = ?,
                    active_operation_started_at = ?, reason = '', updated_at = ?,
                    version = version + 1
                WHERE id = ? AND status = 'previewed'
                  AND active_operation_id IS NULL
                """,
                (operation_id, now, now, run_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"ToolRun status or operation ownership conflict: {run_id}")
        return self._required(run_id)

    def complete_call(
        self,
        run_id: str,
        operation_id: str,
        *,
        status: str,
        result: dict[str, Any],
        reason: str,
        elapsed_ms: int,
    ) -> ToolRun:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tool_runs
                SET status = ?, result = ?, reason = ?, elapsed_ms = ?,
                    active_operation_id = NULL,
                    active_operation_started_at = NULL,
                    completed_at = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND active_operation_id = ?
                """,
                (
                    status,
                    _dump(result),
                    reason,
                    elapsed_ms,
                    now,
                    now,
                    run_id,
                    operation_id,
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"ToolRun operation ownership lost: {operation_id}")
        return self._required(run_id)

    def fail_call(
        self, run_id: str, operation_id: str, reason: str, elapsed_ms: int = 0
    ) -> ToolRun:
        return self.complete_call(
            run_id,
            operation_id,
            status="failed",
            result={},
            reason=reason,
            elapsed_ms=elapsed_ms,
        )

    def recover_stale_operations(self, *, stale_after_seconds: int = 300) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        ).isoformat()
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tool_runs
                SET status = 'failed', reason = 'stale operation recovered',
                    active_operation_id = NULL,
                    active_operation_started_at = NULL,
                    completed_at = ?, updated_at = ?, version = version + 1
                WHERE active_operation_id IS NOT NULL
                  AND active_operation_started_at IS NOT NULL
                  AND active_operation_started_at < ?
                """,
                (now, now, cutoff),
            )
        return cursor.rowcount

    def _required(self, run_id: str) -> ToolRun:
        run = self.get(run_id)
        if run is None:
            raise ValueError(f"ToolRun not found: {run_id}")
        return run


def _from_row(row) -> ToolRun:
    return ToolRun(
        id=row["id"],
        tool_name=row["tool_name"],
        args=dict(json.loads(row["args"] or "{}")),
        args_hash=row["args_hash"],
        status=row["status"],
        preview=dict(json.loads(row["preview"] or "{}")),
        result=dict(json.loads(row["result"] or "{}")),
        reason=row["reason"],
        elapsed_ms=row["elapsed_ms"],
        active_operation_id=row["active_operation_id"],
        active_operation_started_at=row["active_operation_started_at"],
        previewed_at=row["previewed_at"],
        completed_at=row["completed_at"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
