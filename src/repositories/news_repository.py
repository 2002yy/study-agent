"""SQLite repository for server-owned NewsRun stage lifecycle."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from src.domain.runtime_entities import NewsRun, utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class NewsRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()
        self.recover_stale_operations()

    def create(self, run: NewsRun) -> NewsRun:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO news_runs(
                    id, query, stage, status, safe_mode, items, digest, warnings,
                    group_thread_id, created_at, updated_at, source_block,
                    article_coverage, discussion, error, version,
                    active_operation_id, active_operation_started_at,
                    stage_started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    run.source_block,
                    _dump(run.article_coverage),
                    run.discussion,
                    run.error,
                    run.version,
                    run.active_operation_id,
                    run.active_operation_started_at,
                    run.stage_started_at,
                    run.completed_at,
                ),
            )
        return run

    def get(self, run_id: str) -> NewsRun | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM news_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return _from_row(row) if row is not None else None

    def list(self, *, limit: int = 20) -> list[NewsRun]:
        safe_limit = max(1, min(limit, 100))
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM news_runs ORDER BY updated_at DESC, id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def acquire_operation(
        self,
        run_id: str,
        operation_id: str,
        *,
        expected_stages: Iterable[str],
    ) -> NewsRun:
        stages = tuple(expected_stages)
        if not stages:
            raise ValueError("Expected NewsRun stage is required")
        placeholders = ", ".join("?" for _ in stages)
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE news_runs
                SET active_operation_id = ?, active_operation_started_at = ?,
                    stage_started_at = ?, status = 'running', error = '',
                    updated_at = ?, version = version + 1
                WHERE id = ? AND active_operation_id IS NULL
                  AND stage IN ({placeholders})
                """,
                (operation_id, now, now, now, run_id, *stages),
            )
        if cursor.rowcount != 1:
            raise ValueError(
                f"NewsRun stage or operation ownership conflict: {run_id}"
            )
        return self._required(run_id)

    def complete_operation(
        self,
        run_id: str,
        operation_id: str,
        *,
        stage: str,
        items: list[dict[str, Any]] | None = None,
        digest: str | None = None,
        source_block: str | None = None,
        article_coverage: dict[str, Any] | None = None,
        discussion: str | None = None,
        warnings: list[str] | None = None,
        group_thread_id: str | None = None,
        safe_mode: bool | None = None,
        completed: bool = False,
    ) -> NewsRun:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE news_runs
                SET stage = ?, status = ?,
                    items = COALESCE(?, items), digest = COALESCE(?, digest),
                    source_block = COALESCE(?, source_block),
                    article_coverage = COALESCE(?, article_coverage),
                    discussion = COALESCE(?, discussion),
                    warnings = COALESCE(?, warnings),
                    group_thread_id = COALESCE(?, group_thread_id),
                    safe_mode = COALESCE(?, safe_mode),
                    active_operation_id = NULL,
                    active_operation_started_at = NULL,
                    completed_at = ?, error = '', updated_at = ?, version = version + 1
                WHERE id = ? AND active_operation_id = ?
                """,
                (
                    stage,
                    "completed" if completed else "running",
                    _dump(items) if items is not None else None,
                    digest,
                    source_block,
                    _dump(article_coverage) if article_coverage is not None else None,
                    discussion,
                    _dump(warnings) if warnings is not None else None,
                    group_thread_id,
                    1 if safe_mode else 0 if safe_mode is not None else None,
                    now if completed else None,
                    now,
                    run_id,
                    operation_id,
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"NewsRun operation ownership lost: {operation_id}")
        return self._required(run_id)

    def fail_operation(self, run_id: str, operation_id: str, error: str) -> NewsRun:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE news_runs
                SET status = 'failed', error = ?, active_operation_id = NULL,
                    active_operation_started_at = NULL, updated_at = ?, version = version + 1
                WHERE id = ? AND active_operation_id = ?
                """,
                (error, now, run_id, operation_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"NewsRun operation ownership lost: {operation_id}")
        return self._required(run_id)

    def recover_stale_operations(self, *, stale_after_seconds: int = 300) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        ).isoformat()
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE news_runs
                SET status = 'failed', error = 'stale operation recovered',
                    active_operation_id = NULL, active_operation_started_at = NULL,
                    updated_at = ?, version = version + 1
                WHERE active_operation_id IS NOT NULL
                  AND active_operation_started_at IS NOT NULL
                  AND active_operation_started_at < ?
                """,
                (now, cutoff),
            )
        return cursor.rowcount

    def _required(self, run_id: str) -> NewsRun:
        run = self.get(run_id)
        if run is None:
            raise ValueError(f"NewsRun not found: {run_id}")
        return run


def _from_row(row) -> NewsRun:
    return NewsRun(
        id=row["id"],
        query=row["query"],
        stage=row["stage"],
        status=row["status"],
        safe_mode=bool(row["safe_mode"]),
        items=list(json.loads(row["items"] or "[]")),
        digest=row["digest"],
        source_block=row["source_block"],
        article_coverage=dict(json.loads(row["article_coverage"] or "{}")),
        discussion=row["discussion"],
        warnings=list(json.loads(row["warnings"] or "[]")),
        error=row["error"],
        group_thread_id=row["group_thread_id"],
        active_operation_id=row["active_operation_id"],
        active_operation_started_at=row["active_operation_started_at"],
        stage_started_at=row["stage_started_at"],
        completed_at=row["completed_at"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
