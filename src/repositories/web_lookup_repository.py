"""SQLite repository for durable, recoverable WebLookupRun results."""

from __future__ import annotations

import builtins
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import time
from typing import Any

from src.domain.runtime_entities import WebLookupRun, new_id, utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.web.research.failure_contracts import require_research_stop_reason
from src.web.research.steering import (
    append_active_steering,
    is_active_claim_engine_context,
    merge_active_steering_context,
)
from src.web.source_assessment import assess_sources


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _monotonic() -> float:
    return time.perf_counter()


def _short_hash(value: str) -> str:
    """Identity of one serialized section, without keeping its content."""

    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _validated_stop_reason(value: str) -> str:
    if not value:
        return ""
    return require_research_stop_reason(value)


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
        stop_reason = _validated_stop_reason(run.stop_reason)
        run = replace(run, root_run_id=run.root_run_id or run.id)
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
                    warnings, error, owner_thread_id, parent_run_id, root_run_id,
                    lineage_depth, create_request_id, version, created_at,
                    updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    stop_reason,
                    run.answer_confidence,
                    _dump(run.items),
                    run.source_block,
                    _dump(run.warnings),
                    run.error,
                    run.owner_thread_id,
                    run.parent_run_id,
                    run.root_run_id,
                    run.lineage_depth,
                    run.create_request_id,
                    run.version,
                    run.created_at,
                    run.updated_at,
                    run.completed_at,
                ),
            )
        return self._required(run.id)

    def create_child(
        self,
        run: WebLookupRun,
        *,
        max_descendants: int = 20,
    ) -> WebLookupRun:
        """Atomically validate lineage authority and create one idempotent child."""

        request_id = str(run.create_request_id or "").strip()
        parent_id = str(run.parent_run_id or "").strip()
        thread_id = str(run.owner_thread_id or "").strip()
        if not request_id or not parent_id or not thread_id:
            raise ValueError(
                "Follow-up child requires create_request_id, parent_run_id and owner_thread_id"
            )
        stop_reason = _validated_stop_reason(run.stop_reason)
        context = _with_operation(
            run.research_context,
            max_items=max(1, min(int(run.max_items), 20)),
            active_operation_id=run.active_operation_id,
            active_operation_started_at=run.active_operation_started_at,
            stage_started_at=run.stage_started_at,
            cancel_requested_at=run.cancel_requested_at,
        )
        created_id = run.id
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM web_lookup_runs WHERE create_request_id = ?",
                (request_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["query"] != run.query
                    or existing["parent_run_id"] != parent_id
                    or existing["owner_thread_id"] != thread_id
                ):
                    connection.rollback()
                    raise ValueError(
                        f"Research child idempotency conflict: {request_id}"
                    )
                created_id = str(existing["id"])
                connection.commit()
            else:
                thread = connection.execute(
                    "SELECT status FROM chat_threads WHERE id = ?",
                    (thread_id,),
                ).fetchone()
                if thread is None or thread["status"] != "active":
                    connection.rollback()
                    raise ValueError(f"Chat thread is not active: {thread_id}")
                parent_row = connection.execute(
                    "SELECT * FROM web_lookup_runs WHERE id = ?",
                    (parent_id,),
                ).fetchone()
                if parent_row is None:
                    connection.rollback()
                    raise ValueError(f"WebLookupRun parent not found: {parent_id}")
                parent = _from_row(parent_row)
                if parent.owner_thread_id != thread_id:
                    connection.rollback()
                    raise ValueError("Research parent belongs to another thread")
                if parent.status not in {"completed", "partial", "failed", "cancelled"}:
                    connection.rollback()
                    raise ValueError("Research parent is not terminal")
                deep = parent.research_context.get("deep")
                notes = deep.get("notes") if isinstance(deep, dict) else []
                if parent.status in {"failed", "cancelled"} and not (
                    parent.selected_sources or (isinstance(notes, list) and notes)
                ):
                    connection.rollback()
                    raise ValueError("Research parent has no persisted checkpoint evidence")
                root_id = parent.root_run_id or parent.id
                descendant_row = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM web_lookup_runs
                    WHERE root_run_id = ? AND parent_run_id IS NOT NULL
                    """,
                    (root_id,),
                ).fetchone()
                descendant_count = int(descendant_row["count"] if descendant_row else 0)
                if descendant_count >= max(1, int(max_descendants)):
                    connection.rollback()
                    raise ValueError("Research lineage descendant limit reached")
                child = replace(
                    run,
                    root_run_id=root_id,
                    lineage_depth=parent.lineage_depth + 1,
                )
                connection.execute(
                    """
                    INSERT INTO web_lookup_runs(
                        id, query, stage, status, research_context, query_attempts,
                        selected_sources, rejected_sources, provider_status,
                        stop_reason, answer_confidence, items, source_block,
                        warnings, error, owner_thread_id, parent_run_id, root_run_id,
                        lineage_depth, create_request_id, version, created_at,
                        updated_at, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        child.id,
                        child.query,
                        child.stage,
                        child.status,
                        _dump(context),
                        _dump(child.query_attempts),
                        _dump(child.selected_sources),
                        _dump(child.rejected_sources),
                        child.provider_status,
                        stop_reason,
                        child.answer_confidence,
                        _dump(child.items),
                        child.source_block,
                        _dump(child.warnings),
                        child.error,
                        child.owner_thread_id,
                        child.parent_run_id,
                        child.root_run_id,
                        child.lineage_depth,
                        child.create_request_id,
                        child.version,
                        child.created_at,
                        child.updated_at,
                        child.completed_at,
                    ),
                )
                connection.commit()
        return self._required(created_id)

    def get(self, run_id: str) -> WebLookupRun | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM web_lookup_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        run = _from_row(row)
        return replace(run, lineage_summary=self.lineage_summary(run.root_run_id or run.id))

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
        return [
            replace(
                run,
                lineage_summary=self.lineage_summary(run.root_run_id or run.id),
            )
            for row in rows
            for run in (_from_row(row),)
        ]

    def list_by_owner_thread(
        self,
        thread_id: str,
        *,
        limit: int = 20,
    ) -> builtins.list[WebLookupRun]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM web_lookup_runs
                WHERE owner_thread_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (thread_id, max(1, min(int(limit), 100))),
            ).fetchall()
        return [
            replace(
                run,
                lineage_summary=self.lineage_summary(run.root_run_id or run.id),
            )
            for row in rows
            for run in (_from_row(row),)
        ]

    def thread_status(self, thread_id: str) -> str | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT status FROM chat_threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
        return str(row["status"]) if row is not None else None

    def lineage_summary(self, root_run_id: str) -> dict[str, int]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT query_attempts, research_context, created_at, completed_at,
                       parent_run_id
                FROM web_lookup_runs
                WHERE root_run_id = ?
                """,
                (root_run_id,),
            ).fetchall()
        search_count = read_count = elapsed_ms = child_count = 0
        for row in rows:
            attempts = json.loads(row["query_attempts"] or "[]")
            search_count += len(attempts) if isinstance(attempts, list) else 0
            context = json.loads(row["research_context"] or "{}")
            summary = context.get("read_summary") if isinstance(context, dict) else {}
            if isinstance(summary, dict):
                read_count += int(summary.get("attempted") or 0)
            started = _parse_timestamp(row["created_at"])
            ended = _parse_timestamp(row["completed_at"])
            if started is not None and ended is not None:
                elapsed_ms += max(0, int((ended - started).total_seconds() * 1000))
            if row["parent_run_id"]:
                child_count += 1
        return {
            "search_count": search_count,
            "read_count": read_count,
            "elapsed_ms": elapsed_ms,
            "child_count": child_count,
        }

    def list_by_owner_turn(
        self,
        turn_id: str,
        *,
        limit: int = 20,
    ) -> builtins.list[WebLookupRun]:
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
                    stop_reason = '', error = '', completed_at = NULL, updated_at = ?,
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

    def set_stage(
        self,
        run_id: str,
        *,
        stage: str,
        operation_id: str,
    ) -> WebLookupRun:
        """Owner-scoped unconditional stage write for the G18 round loop.

        The deep-research loop revisits the same stages across rounds, so the
        strict expected-stage CAS of ``transition_stage`` does not fit; the
        running-owner + version guards are the concurrency contract here.
        """
        if not stage.strip():
            raise ValueError("Research stage must be non-empty")
        run = self._required(run_id)
        self._assert_running_owner(run, operation_id)
        now = utc_now()
        context = _with_operation(run.research_context, stage_started_at=now)
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET stage = ?, research_context = ?, updated_at = ?,
                    version = version + 1
                WHERE id = ? AND status = 'running' AND version = ?
                """,
                (stage, _dump(context), now, run_id, run.version),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"WebLookupRun stage write conflicted: {run_id}")
        return self._required(run_id)

    def append_steering(self, run_id: str, *, content: str) -> WebLookupRun | None:
        """G18 decision 12: inject a mid-run steering message into a running run.

        The message is metadata attached to the active run (never a new
        ChatTurn); the iteration loop consumes it at the next round boundary.
        """
        normalized = " ".join((content or "").strip().split())
        if not normalized:
            raise ValueError("Steering content is required")
        entry_id = new_id("steering")
        received_at = utc_now()
        for _attempt in range(4):
            with self.database.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM web_lookup_runs WHERE id = ?", (run_id,)
                ).fetchone()
                # Steering is valid while queued (pending) as well as running:
                # the user may refine direction before the worker starts.
                if row is None or row["status"] not in {"running", "pending"}:
                    return None
                current = _from_row(row)
                context = dict(current.research_context)
                if is_active_claim_engine_context(context):
                    context = append_active_steering(
                        context,
                        entry_id=entry_id,
                        content=normalized[:2000],
                        received_at=received_at,
                    )
                else:
                    # Preserve the delivered legacy deep-research envelope.
                    deep = dict(context.get("deep") or {})
                    steering = [
                        dict(item)
                        for item in deep.get("steering", [])
                        if isinstance(item, dict)
                    ]
                    steering.append(
                        {
                            "content": normalized[:2000],
                            "received_at": received_at,
                            "incorporated_in_round": None,
                        }
                    )
                    deep["steering"] = steering
                    context["deep"] = deep
                cursor = connection.execute(
                    """
                    UPDATE web_lookup_runs
                    SET research_context = ?, updated_at = ?, version = version + 1
                    WHERE id = ? AND status IN ('running', 'pending') AND version = ?
                    """,
                    (_dump(context), utc_now(), run_id, current.version),
                )
            if cursor.rowcount == 1:
                return self._required(run_id)
        return None

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
        diagnostics: dict[str, Any] | None = None,
    ) -> WebLookupRun:
        """Persist one research checkpoint.

        ``diagnostics`` is an optional, purely observational sink (F2-O4a): when
        given, it receives how long serialization took versus how long the actual
        write took, the serialized size per section, and how many version
        conflicts the optimistic-concurrency loop hit. Nothing about behaviour,
        durability or recovery semantics changes, and callers that pass nothing
        keep their exact previous behaviour.
        """

        stop_reason = _validated_stop_reason(stop_reason)
        checkpoint_context = dict(research_context)
        repo_started = _monotonic()
        conflicts = 0
        serialize_ms = 0.0
        write_ms = 0.0
        load_ms = 0.0
        attempts_used = 0
        section_sizes: dict[str, int] = {}
        # Loop-invariant sections are serialized once, outside the retry loop.
        invariant_started = _monotonic()
        dumped_query_attempts = _dump(query_attempts)
        dumped_selected_sources = _dump(selected_sources)
        dumped_rejected_sources = _dump(rejected_sources)
        dumped_items = _dump(items)
        dumped_warnings = _dump(warnings)
        invariant_ms = (_monotonic() - invariant_started) * 1000.0
        for _attempt in range(4):
            load_started = _monotonic()
            run = self._required(run_id)
            load_ms += (_monotonic() - load_started) * 1000.0
            self._assert_running_owner(run, operation_id)
            checkpoint_context = merge_active_steering_context(
                checkpoint_context,
                run.research_context,
            )
            context = _with_operation(
                checkpoint_context,
                **_operation_state(run.research_context),
            )
            now = utc_now()
            attempts_used = _attempt + 1
            serialize_started = _monotonic()
            dumped_context = _dump(context)
            serialize_ms = (
                invariant_ms + (_monotonic() - serialize_started) * 1000.0
            )
            section_sizes = {
                "research_context": len(dumped_context),
                "query_attempts": len(dumped_query_attempts),
                "selected_sources": len(dumped_selected_sources),
                "rejected_sources": len(dumped_rejected_sources),
                "items": len(dumped_items),
                "warnings": len(dumped_warnings),
            }
            write_started = _monotonic()
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
                    dumped_context,
                    dumped_query_attempts,
                    dumped_selected_sources,
                    dumped_rejected_sources,
                    dumped_items,
                    dumped_warnings,
                    provider_status,
                    stop_reason,
                    answer_confidence,
                    now,
                    run_id,
                    run.version,
                ),
                )
            write_ms = (_monotonic() - write_started) * 1000.0
            if cursor.rowcount == 1:
                hash_started = _monotonic()
                section_hashes = {
                    "research_context": _short_hash(dumped_context),
                    "query_attempts": _short_hash(dumped_query_attempts),
                    "selected_sources": _short_hash(dumped_selected_sources),
                    "rejected_sources": _short_hash(dumped_rejected_sources),
                    "items": _short_hash(dumped_items),
                    "warnings": _short_hash(dumped_warnings),
                }
                hash_ms = (_monotonic() - hash_started) * 1000.0
                load_started = _monotonic()
                persisted = self._required(run_id)
                load_ms += (_monotonic() - load_started) * 1000.0
                if diagnostics is not None:
                    repo_ms = (_monotonic() - repo_started) * 1000.0
                    diagnostics.update(
                        {
                            "attempts": attempts_used,
                            "conflicts": conflicts,
                            "repo_ms": round(repo_ms, 1),
                            "load_ms": round(load_ms, 1),
                            "serialize_ms": round(serialize_ms, 1),
                            "write_ms": round(write_ms, 1),
                            "hash_ms": round(hash_ms, 1),
                            "repo_other_ms": round(
                                max(
                                    0.0,
                                    repo_ms - load_ms - serialize_ms - write_ms,
                                ),
                                1,
                            ),
                            "bytes_by_section": dict(section_sizes),
                            "section_hashes": section_hashes,
                            "bytes_total": int(sum(section_sizes.values())),
                            "write_targets": 1,
                            "files": 0,
                        }
                    )
                return persisted
            conflicts += 1
            checkpoint_context = context
        raise ValueError(f"WebLookupRun checkpoint conflicted: {run_id}")

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
        stop_reason = _validated_stop_reason(stop_reason)
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
        stop_reason = _validated_stop_reason(stop_reason)
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
        owner_thread_id=row["owner_thread_id"],
        parent_run_id=row["parent_run_id"],
        root_run_id=row["root_run_id"] or row["id"],
        lineage_depth=int(row["lineage_depth"] or 0),
        create_request_id=row["create_request_id"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )
