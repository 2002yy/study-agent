"""SQLite repository for durable WebLookupRun results."""

from __future__ import annotations

import json
from typing import Any

from src.domain.runtime_entities import WebLookupRun, utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class WebLookupRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()

    def create(self, run: WebLookupRun) -> WebLookupRun:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO web_lookup_runs(
                    id, query, status, items, source_block, warnings, error,
                    version, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.query,
                    run.status,
                    _dump(run.items),
                    run.source_block,
                    _dump(run.warnings),
                    run.error,
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

    def complete(
        self,
        run_id: str,
        *,
        items: list[dict[str, Any]],
        source_block: str,
        warnings: list[str],
    ) -> WebLookupRun:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET status = 'completed', items = ?, source_block = ?,
                    warnings = ?, error = '', completed_at = ?,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'running'
                """,
                (_dump(items), source_block, _dump(warnings), now, now, run_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"WebLookupRun is not completable: {run_id}")
        return self._required(run_id)

    def fail(self, run_id: str, error: str) -> WebLookupRun:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET status = 'failed', error = ?, completed_at = ?,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'running'
                """,
                (error, now, now, run_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"WebLookupRun is not fail-able: {run_id}")
        return self._required(run_id)

    def _required(self, run_id: str) -> WebLookupRun:
        run = self.get(run_id)
        if run is None:
            raise ValueError(f"WebLookupRun not found: {run_id}")
        return run


def _from_row(row) -> WebLookupRun:
    return WebLookupRun(
        id=row["id"],
        query=row["query"],
        status=row["status"],
        items=json.loads(row["items"] or "[]"),
        source_block=row["source_block"],
        warnings=json.loads(row["warnings"] or "[]"),
        error=row["error"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )
