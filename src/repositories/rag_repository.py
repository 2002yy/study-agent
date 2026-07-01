"""SQLite repository for query/upload/rebuild RAG runs."""

from __future__ import annotations

import json
from typing import Any

from src.domain.runtime_entities import RagRun, utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class RagRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()

    def create(self, run: RagRun) -> RagRun:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO rag_runs(
                    id, kind, status, request, result, error, index_version,
                    version, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id, run.kind, run.status, _dump(run.request),
                    _dump(run.result), run.error, run.index_version, run.version,
                    run.created_at, run.updated_at, run.completed_at,
                ),
            )
        return run

    def get(self, run_id: str) -> RagRun | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM rag_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return _from_row(row) if row is not None else None

    def list(self, *, kind: str | None = None, limit: int = 20) -> list[RagRun]:
        safe_limit = max(1, min(limit, 100))
        with self.database.connect() as connection:
            if kind:
                rows = connection.execute(
                    """
                    SELECT * FROM rag_runs WHERE kind = ?
                    ORDER BY updated_at DESC, id DESC LIMIT ?
                    """,
                    (kind, safe_limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM rag_runs
                    ORDER BY updated_at DESC, id DESC LIMIT ?
                    """,
                    (safe_limit,),
                ).fetchall()
        return [_from_row(row) for row in rows]

    def complete(
        self,
        run_id: str,
        *,
        result: dict[str, Any],
        index_version: int,
    ) -> RagRun:
        return self._finish(
            run_id, status="completed", result=result,
            error="", index_version=index_version,
        )

    def fail(self, run_id: str, error: str) -> RagRun:
        return self._finish(
            run_id, status="failed", result={}, error=error, index_version=0,
        )

    def _finish(
        self,
        run_id: str,
        *,
        status: str,
        result: dict[str, Any],
        error: str,
        index_version: int,
    ) -> RagRun:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE rag_runs
                SET status = ?, result = ?, error = ?, index_version = ?,
                    completed_at = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'running'
                """,
                (
                    status, _dump(result), error, index_version,
                    now, now, run_id,
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"RagRun is not completable: {run_id}")
        run = self.get(run_id)
        if run is None:
            raise ValueError(f"RagRun not found: {run_id}")
        return run


def _from_row(row) -> RagRun:
    return RagRun(
        id=row["id"],
        kind=row["kind"],
        status=row["status"],
        request=dict(json.loads(row["request"] or "{}")),
        result=dict(json.loads(row["result"] or "{}")),
        error=row["error"],
        index_version=row["index_version"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )
