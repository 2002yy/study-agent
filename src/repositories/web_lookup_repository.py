"""SQLite repository for durable, recoverable WebLookupRun results."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

from src.domain.runtime_entities import WebLookupRun, utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.web.source_assessment import assess_sources


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _is_assessed_source(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("item"), dict)
        and isinstance(value.get("assessment"), dict)
    )


def _operation_state(context: dict[str, Any]) -> dict[str, Any]:
    value = context.get("operation")
    return dict(value) if isinstance(value, dict) else {}


def _with_operation(context: dict[str, Any], **updates: Any) -> dict[str, Any]:
    result = dict(context)
    operation = _operation_state(result)
    operation.update(updates)
    result["operation"] = operation
    return result


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


def _operation_is_stale(context: dict[str, Any], seconds: int) -> bool:
    started = _parse_timestamp(_operation_state(context).get("active_operation_started_at"))
    if started is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1, seconds))
    return started < cutoff


class WebLookupRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()

    def create(self, run: WebLookupRun) -> WebLookupRun:
        context = _with_operation(
            run.research_context,
            max_items=max(1, min(int(run.max_items), 20)),
            active_operation_id=run.active_operation_id,
            active_operation_started_at=run.active_operation_started_at,
            stage_started_at=run.stage_started_at,
            cancel_requested_at=run.cancel_requested_at,
        )
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
                    _dump(context),
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
        return self._required(run.id)

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

    def list_by_owner_turn(self, turn_id: str, *, limit: int = 20) -> list[WebLookupRun]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM web_lookup_runs
                WHERE json_extract(research_context, '$.owner.turn_id') = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (turn_id, max(1, min(int(limit), 100))),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def begin_operation(
        self,
        run_id: str,
        *,
        operation_id: str,
        stage: str,
        stale_after_seconds: int = 120,
    ) -> WebLookupRun:
        """Acquire one run operation without allowing stale-owner writeback."""

        if not operation_id.strip() or not stage.strip():
            raise ValueError("Research operation and stage must be non-empty")
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM web_lookup_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise ValueError(f"WebLookupRun not found: {run_id}")
            run = _from_row(row)
            resumable_completed = run.status == "completed" and run.provider_status in {
                "empty",
                "partial",
                "insufficient",
            }
            recoverable_running = run.status == "running" and _operation_is_stale(
                run.research_context,
                stale_after_seconds,
            )
            if not (
                run.status in {"pending", "failed", "cancelled", "partial"}
                or resumable_completed
                or recoverable_running
            ):
                connection.rollback()
                raise ValueError(f"WebLookupRun is not resumable: {run_id}")
            context = _with_operation(
                run.research_context,
                active_operation_id=operation_id,
                active_operation_started_at=now,
                stage_started_at=now,
                cancel_requested_at=None,
                max_items=run.max_items,
            )
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET stage = ?, status = 'running', research_context = ?,
                    error = '', completed_at = NULL, updated_at = ?,
                    version = version + 1
                WHERE id = ? AND version = ?
                """,
                (stage, _dump(context), now, run_id, run.version),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise ValueError(f"WebLookupRun operation acquisition conflicted: {run_id}")
            connection.commit()
        return self._required(run_id)

    def transition_stage(
        self,
        run_id: str,
        *,
        expected_stage: str,
        stage: str,
        operation_id: str | None = None,
    ) -> WebLookupRun:
        if not expected_stage.strip() or not stage.strip():
            raise ValueError("Research stages must be non-empty")
        run = self._required(run_id)
        self._assert_running_owner(run, operation_id)
        if run.stage != expected_stage:
            raise ValueError(
                f"WebLookupRun stage is not transitionable: {run_id} "
                f"({expected_stage} -> {stage})"
            )
        now = utc_now()
        context = _with_operation(run.research_context, stage_started_at=now)
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET stage = ?, research_context = ?, updated_at = ?,
                    version = version + 1
                WHERE id = ? AND status = 'running' AND stage = ? AND version = ?
                """,
                (stage, _dump(context), now, run_id, expected_stage, run.version),
            )
        if cursor.rowcount != 1:
            raise ValueError(
                f"WebLookupRun stage transition conflicted: {run_id} "
                f"({expected_stage} -> {stage})"
            )
        return self._required(run_id)

    def checkpoint(
        self,
        run_id: str,
        *,
        operation_id: str,
        research_context: dict[str, Any],
        query_attempts: list[dict[str, Any]],
        selected_sources: list[dict[str, Any]],
        rejected_sources: list[dict[str, Any]],
        items: list[dict[str, Any]],
        warnings: list[str],
        provider_status: str = "",
        stop_reason: str = "",
        answer_confidence: str = "",
    ) -> WebLookupRun:
        run = self._required(run_id)
        self._assert_running_owner(run, operation_id)
        context = _with_operation(
            research_context,
            **_operation_state(run.research_context),
        )
        now = utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET research_context = ?, query_attempts = ?,
                    selected_sources = ?, rejected_sources = ?, items = ?,
                    warnings = ?, provider_status = ?, stop_reason = ?,
                    answer_confidence = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'running' AND version = ?
                """,
                (
                    _dump(context),
                    _dump(query_attempts),
                    _dump(selected_sources),
                    _dump(rejected_sources),
                    _dump(items),
                    _dump(warnings),
                    provider_status,
                    stop_reason,
                    answer_confidence,
                    now,
                    run_id,
                    run.version,
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"WebLookupRun checkpoint conflicted: {run_id}")
        return self._required(run_id)

    def request_cancel(self, run_id: str) -> WebLookupRun:
        run = self._required(run_id)
        if run.status == "cancelled":
            return run
        if run.status not in {"pending", "running", "failed", "partial"}:
            raise ValueError(f"WebLookupRun is not cancellable: {run_id}")
        now = utc_now()
        context = _with_operation(run.research_context, cancel_requested_at=now)
        if run.status == "running":
            next_status = "running"
            next_stage = run.stage
            completed_at = run.completed_at
        else:
            next_status = "cancelled"
            next_stage = "cancelled"
            completed_at = now
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET status = ?, stage = ?, research_context = ?,
                    stop_reason = 'user_cancelled', completed_at = ?,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND version = ?
                """,
                (
                    next_status,
                    next_stage,
                    _dump(context),
                    completed_at,
                    now,
                    run_id,
                    run.version,
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"WebLookupRun cancellation conflicted: {run_id}")
        return self._required(run_id)

    def cancel_requested(self, run_id: str, *, operation_id: str) -> bool:
        run = self._required(run_id)
        self._assert_running_owner(run, operation_id)
        return bool(run.cancel_requested_at)

    def finish_cancel(self, run_id: str, *, operation_id: str) -> WebLookupRun:
        run = self._required(run_id)
        self._assert_running_owner(run, operation_id)
        now = utc_now()
        context = _with_operation(
            run.research_context,
            active_operation_id=None,
            active_operation_started_at=None,
            stage_started_at=None,
        )
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET status = 'cancelled', stage = 'cancelled',
                    research_context = ?, stop_reason = 'user_cancelled',
                    completed_at = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'running' AND version = ?
                """,
                (_dump(context), now, now, run_id, run.version),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"WebLookupRun cancellation finalization conflicted: {run_id}")
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
        operation_id: str | None = None,
        final_status: str | None = None,
    ) -> WebLookupRun:
        run = self._required(run_id)
        if operation_id is not None:
            self._assert_running_owner(run, operation_id)
        elif run.status != "running":
            raise ValueError(f"WebLookupRun is not completable: {run_id}")

        raw_context = research_context or run.research_context
        attempts = query_attempts if query_attempts is not None else run.query_attempts
        current_attempt = int(raw_context.get("run_attempt") or 0)
        current_provider_failure = any(
            attempt.get("status") == "provider_failed"
            and int(attempt.get("run_attempt") or 0) == current_attempt
            for attempt in attempts
        )
        read_summary = raw_context.get("read_summary")
        had_read_failure = (
            isinstance(read_summary, dict)
            and int(read_summary.get("failed") or 0) > 0
        )
        if (
            provider_status == "partial"
            and not current_provider_failure
            and not had_read_failure
        ):
            provider_status = "found" if items else "empty"

        now = utc_now()
        status = final_status or (
            "partial" if provider_status == "insufficient" else "completed"
        )
        context = _with_operation(
            raw_context,
            active_operation_id=None,
            active_operation_started_at=None,
            stage_started_at=None,
            cancel_requested_at=None,
            max_items=run.max_items,
        )
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET stage = 'completed', status = ?, research_context = ?,
                    query_attempts = ?, selected_sources = ?, rejected_sources = ?,
                    provider_status = ?, stop_reason = ?, answer_confidence = ?,
                    items = ?, source_block = ?, warnings = ?, error = '',
                    completed_at = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'running' AND version = ?
                """,
                (
                    status,
                    _dump(context),
                    _dump(attempts),
                    _dump(
                        selected_sources
                        if selected_sources is not None
                        else (run.selected_sources or items)
                    ),
                    _dump(
                        rejected_sources
                        if rejected_sources is not None
                        else run.rejected_sources
                    ),
                    provider_status,
                    stop_reason,
                    answer_confidence,
                    _dump(items),
                    source_block,
                    _dump(warnings),
                    now,
                    now,
                    run_id,
                    run.version,
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"WebLookupRun completion conflicted: {run_id}")
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
        operation_id: str | None = None,
    ) -> WebLookupRun:
        run = self._required(run_id)
        if operation_id is not None:
            self._assert_running_owner(run, operation_id)
        elif run.status != "running":
            raise ValueError(f"WebLookupRun is not fail-able: {run_id}")
        now = utc_now()
        context = _with_operation(
            research_context or run.research_context,
            active_operation_id=None,
            active_operation_started_at=None,
            stage_started_at=None,
            cancel_requested_at=None,
            max_items=run.max_items,
        )
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET stage = 'failed', status = 'failed', error = ?,
                    research_context = ?, query_attempts = ?,
                    provider_status = ?, stop_reason = ?, completed_at = ?,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND status = 'running' AND version = ?
                """,
                (
                    error,
                    _dump(context),
                    _dump(query_attempts if query_attempts is not None else run.query_attempts),
                    provider_status,
                    stop_reason,
                    now,
                    now,
                    run_id,
                    run.version,
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"WebLookupRun failure conflicted: {run_id}")
        return self._required(run_id)

    @staticmethod
    def _assert_running_owner(run: WebLookupRun, operation_id: str | None) -> None:
        if run.status != "running":
            raise ValueError(f"WebLookupRun is not running: {run.id}")
        if operation_id is not None and run.active_operation_id != operation_id:
            raise ValueError(f"WebLookupRun operation lost ownership: {run.id}")

    def _required(self, run_id: str) -> WebLookupRun:
        run = self.get(run_id)
        if run is None:
            raise ValueError(f"WebLookupRun not found: {run_id}")
        return run


def _normalized_source_records(row) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected = json.loads(row["selected_sources"] or "[]")
    rejected = json.loads(row["rejected_sources"] or "[]")
    if all(_is_assessed_source(item) for item in selected) and all(
        _is_assessed_source(item) for item in rejected
    ):
        return selected, rejected

    legacy_items = json.loads(row["items"] or "[]")
    candidates = legacy_items or [
        item for item in selected if isinstance(item, dict)
    ]
    normalized_selected, normalized_rejected = assess_sources(
        candidates,
        canonical_query=row["query"],
    )
    return normalized_selected, normalized_rejected


def _from_row(row) -> WebLookupRun:
    selected_sources, rejected_sources = _normalized_source_records(row)
    context = json.loads(row["research_context"] or "{}")
    operation = _operation_state(context)
    return WebLookupRun(
        id=row["id"],
        query=row["query"],
        stage=row["stage"],
        status=row["status"],
        research_context=context,
        query_attempts=json.loads(row["query_attempts"] or "[]"),
        selected_sources=selected_sources,
        rejected_sources=rejected_sources,
        provider_status=row["provider_status"],
        stop_reason=row["stop_reason"],
        answer_confidence=row["answer_confidence"],
        items=json.loads(row["items"] or "[]"),
        source_block=row["source_block"],
        warnings=json.loads(row["warnings"] or "[]"),
        error=row["error"],
        max_items=max(1, min(int(operation.get("max_items") or 8), 20)),
        active_operation_id=operation.get("active_operation_id"),
        active_operation_started_at=operation.get("active_operation_started_at"),
        stage_started_at=operation.get("stage_started_at"),
        cancel_requested_at=operation.get("cancel_requested_at"),
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )
