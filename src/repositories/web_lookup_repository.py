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
                    id, query, stage, status, research_context, query_attempts,
                    selected_sources, rejected_sources, provider_status,
                    stop_reason, answer_confidence, items, source_block,
                    warnings, error, version, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.query,
                    run.stage,
                    run.status,
                    _dump(run.research_context),
                    _dump(run.query_attempts),
                    _dump(run.selected_sources),
                    _dump(run.rejected_sources),
                    run.provider_status,
                    run.stop_reason,
                    run.answer_confidence,
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

    def transition_stage(
        self,
        run_id: str,
        *,
        expected_stage: str,
        stage: str,
    ) -> WebLookupRun:
        """Compare-and-set a running research stage."""

        if not expected_stage.strip() or not stage.strip():
            raise ValueError("Research stages must be non-empty")
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET stage = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'running' AND stage = ?
                """,
                (stage, now, run_id, expected_stage),
            )
        if cursor.rowcount != 1:
            raise ValueError(
                f"WebLookupRun stage is not transitionable: {run_id} "
                f"({expected_stage} -> {stage})"
            )
        return self._required(run_id)

    def complete(
        self,
        run_id: str,
        *,
        items: list[dict[str, Any]],
        source_block: str,
        warnings: list[str],
        research_context: dict[str, Any] | None = None,
        query_attempts: list[dict[str, Any]] | None = None,
        selected_sources: list[dict[str, Any]] | None = None,
        rejected_sources: list[dict[str, Any]] | None = None,
        provider_status: str = "",
        stop_reason: str = "",
        answer_confidence: str = "",
    ) -> WebLookupRun:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET stage = 'completed', status = 'completed',
                    research_context = ?, query_attempts = ?,
                    selected_sources = ?, rejected_sources = ?,
                    provider_status = ?, stop_reason = ?, answer_confidence = ?,
                    items = ?, source_block = ?, warnings = ?, error = '',
                    completed_at = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'running'
                """,
                (
                    _dump(research_context or {}),
                    _dump(query_attempts or []),
                    _dump(selected_sources if selected_sources is not None else items),
                    _dump(rejected_sources or []),
                    provider_status,
                    stop_reason,
                    answer_confidence,
                    _dump(items),
                    source_block,
                    _dump(warnings),
                    now,
                    now,
                    run_id,
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"WebLookupRun is not completable: {run_id}")
        return self._required(run_id)

    def fail(
        self,
        run_id: str,
        error: str,
        *,
        research_context: dict[str, Any] | None = None,
        query_attempts: list[dict[str, Any]] | None = None,
        provider_status: str = "provider_failed",
        stop_reason: str = "providers_failed",
    ) -> WebLookupRun:
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET stage = 'failed', status = 'failed', error = ?,
                    research_context = ?, query_attempts = ?,
                    provider_status = ?, stop_reason = ?, completed_at = ?,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'running'
                """,
                (
                    error,
                    _dump(research_context or {}),
                    _dump(query_attempts or []),
                    provider_status,
                    stop_reason,
                    now,
                    now,
                    run_id,
                ),
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
        stage=row["stage"],
        status=row["status"],
        research_context=json.loads(row["research_context"] or "{}"),
        query_attempts=json.loads(row["query_attempts"] or "[]"),
        selected_sources=json.loads(row["selected_sources"] or "[]"),
        rejected_sources=json.loads(row["rejected_sources"] or "[]"),
        provider_status=row["provider_status"],
        stop_reason=row["stop_reason"],
        answer_confidence=row["answer_confidence"],
        items=json.loads(row["items"] or "[]"),
        source_block=row["source_block"],
        warnings=json.loads(row["warnings"] or "[]"),
        error=row["error"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )
