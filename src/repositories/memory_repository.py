"""SQLite repository for server-owned MemoryRun transactions."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from src.domain.runtime_entities import MemoryRun, utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class MemoryRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()
        self.recover_stale_operations()

    def create(self, run: MemoryRun) -> MemoryRun:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_runs(
                    id, status, updates, updates_hash, preview, result, reason,
                    active_operation_id, active_operation_started_at,
                    previewed_at, completed_at, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id, run.status, _dump(run.updates), run.updates_hash,
                    _dump(run.preview), _dump(run.result), run.reason,
                    run.active_operation_id, run.active_operation_started_at,
                    run.previewed_at, run.completed_at, run.version,
                    run.created_at, run.updated_at,
                ),
            )
        return run

    def get(self, run_id: str) -> MemoryRun | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return _from_row(row) if row is not None else None

    def list(self, *, limit: int = 20) -> list[MemoryRun]:
        safe_limit = max(1, min(limit, 100))
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memory_runs ORDER BY updated_at DESC, id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def acquire_commit(self, run_id: str, operation_id: str) -> MemoryRun:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE memory_runs
                SET status = 'running', active_operation_id = ?,
                    active_operation_started_at = ?, reason = '',
                    updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'previewed'
                  AND active_operation_id IS NULL
                """,
                (operation_id, now, now, run_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"MemoryRun status or operation conflict: {run_id}")
        return self._required(run_id)

    def complete_commit(
        self,
        run_id: str,
        operation_id: str,
        *,
        status: str,
        result: dict[str, Any],
        reason: str = "",
    ) -> MemoryRun:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE memory_runs
                SET status = ?, result = ?, reason = ?,
                    active_operation_id = NULL,
                    active_operation_started_at = NULL,
                    completed_at = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND active_operation_id = ?
                """,
                (status, _dump(result), reason, now, now, run_id, operation_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"MemoryRun operation ownership lost: {operation_id}")
        return self._required(run_id)

    def recover_stale_operations(self, *, stale_after_seconds: int = 300) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        ).isoformat()
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE memory_runs
                SET status = 'failed', reason = 'stale operation recovered',
                    active_operation_id = NULL,
                    active_operation_started_at = NULL,
                    completed_at = ?, updated_at = ?, version = version + 1
                WHERE active_operation_id IS NOT NULL
                  AND active_operation_started_at < ?
                """,
                (now, now, cutoff),
            )
        return cursor.rowcount

    def _required(self, run_id: str) -> MemoryRun:
        run = self.get(run_id)
        if run is None:
            raise ValueError(f"MemoryRun not found: {run_id}")
        return run


def _from_row(row) -> MemoryRun:
    return MemoryRun(
        id=row["id"],
        status=row["status"],
        updates=list(json.loads(row["updates"] or "[]")),
        updates_hash=row["updates_hash"],
        preview=dict(json.loads(row["preview"] or "{}")),
        result=dict(json.loads(row["result"] or "{}")),
        reason=row["reason"],
        active_operation_id=row["active_operation_id"],
        active_operation_started_at=row["active_operation_started_at"],
        previewed_at=row["previewed_at"],
        completed_at=row["completed_at"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
