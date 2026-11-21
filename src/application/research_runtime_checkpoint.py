"""Durable checkpoint boundary for one active research execution.

The executor owns research decisions and the current mutable values. This
context owns the *ordered* projection of those values to a repository
checkpoint, without owning search, model calls or final publication.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from src.application.research_runtime_result_buffers import (
    ActiveResearchResultBuffers,
    _dedupe,
    _eligible_items,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.domain.runtime_entities import WebLookupRun
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.contracts import ResearchState
from src.web.research.runtime import ResearchRuntimeCursor, attach_runtime_cursor
from src.web.research.state import attach_claim_engine_state
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY, TimingLedger


_logger = logging.getLogger(__name__)


def updated_runtime_budget(
    state: ResearchState,
    cursor: ResearchRuntimeCursor,
    *,
    elapsed_seconds: float,
    reads_used: int | None = None,
) -> ResearchState:
    """One budget projection shared by read progress and durable checkpoints."""

    return replace(
        state,
        budget=replace(
            state.budget,
            candidates_used=min(len(cursor.candidates), state.budget.max_candidates),
            reads_used=(state.budget.reads_used if reads_used is None else reads_used),
            elapsed_seconds=elapsed_seconds,
        ),
    )


@dataclass
class ActiveRuntimeCheckpointContext:
    """Explicit snapshot and operation lease for a single checkpoint.

    `prepare` must precede `persist`: visible stage, refreshed budget, both
    serialized state layers, then the repository's concurrency-aware write.
    The caller replaces its local context with the returned durable context.
    """

    repository: WebLookupRepository
    run_id: str
    operation_id: str
    context: dict[str, Any]
    state: ResearchState
    cursor: ResearchRuntimeCursor
    results: ActiveResearchResultBuffers

    def prepare_and_persist(
        self,
        *,
        stage: str | None,
        elapsed: Callable[[], float],
        bind_prepared: Callable[[ResearchState, dict[str, Any]], None],
        diagnostics: dict[str, Any] | None,
        elapsed_ms: Callable[[], float],
    ) -> WebLookupRun:
        """Rebind the projected values even when preparation fails.

        The executor owns the live values; this boundary fixes the order of
        projection, in-memory handoff and durable write. A failed projection
        must not proceed to persistence.
        """
        try:
            self.prepare(stage=stage, elapsed=elapsed)
        finally:
            bind_prepared(self.state, self.context)
        return self.persist(diagnostics=diagnostics, elapsed_ms=elapsed_ms)

    def prepare(self, *, stage: str | None, elapsed: Callable[[], float]) -> None:
        if stage is not None:
            current = self.repository.get(self.run_id)
            if current is None:
                raise ValueError(f"WebLookupRun not found: {self.run_id}")
            if current.stage != stage:
                self.repository.set_stage(
                    self.run_id,
                    stage=stage,
                    operation_id=self.operation_id,
                )
        self.state = updated_runtime_budget(
            self.state, self.cursor, elapsed_seconds=elapsed()
        )
        self.context = attach_runtime_cursor(self.context, self.cursor)
        self.context = attach_claim_engine_state(
            self.context,
            self.state,
            known_evidence_ids=self.results.known_evidence_ids(self.run_id),
        )
        _update_metrics(self.context, self.state, self.cursor)

    def persist(
        self,
        *,
        diagnostics: dict[str, Any] | None,
        elapsed_ms: Callable[[], float],
    ) -> WebLookupRun:
        started = elapsed_ms()
        persisted = self.repository.checkpoint(
            self.run_id,
            operation_id=self.operation_id,
            research_context=self.context,
            query_attempts=self.results.query_attempts,
            selected_sources=self.results.selected_sources,
            rejected_sources=self.results.rejected_sources,
            items=_eligible_items(self.results.selected_sources),
            warnings=_dedupe(self.results.warnings),
            provider_status="",
            stop_reason="",
            answer_confidence="",
            diagnostics=diagnostics,
        )
        if isinstance(diagnostics, dict):
            diagnostics["repo_call_ms"] = round(elapsed_ms() - started, 1)
        return persisted


@dataclass(slots=True)
class ActiveRuntimeCheckpointSession:
    """Resolve fresh live values for every checkpoint in one execution.

    The snapshot remains short-lived: steering, recovery, and wave settlement
    can replace the cursor, state, and durable context between checkpoints.
    Timing observation stays outside the persistence session, in the recorder
    bound by the executor at its existing checkpoint call sites.
    """

    repository: WebLookupRepository
    run_id: str
    operation_id: str
    live: ActiveRuntimeLiveValues
    results: ActiveResearchResultBuffers
    elapsed: Callable[[], float]
    elapsed_ms: Callable[[], float]

    def checkpoint(
        self, *, stage: str | None, diagnostics: dict[str, Any]
    ) -> WebLookupRun:
        snapshot = ActiveRuntimeCheckpointContext(
            repository=self.repository,
            run_id=self.run_id,
            operation_id=self.operation_id,
            context=self.live.current_context(),
            state=self.live.current_state(),
            cursor=self.live.current_cursor(),
            results=self.results,
        )
        persisted = snapshot.prepare_and_persist(
            stage=stage,
            elapsed=self.elapsed,
            bind_prepared=self.live.bind_prepared_checkpoint,
            diagnostics=diagnostics,
            elapsed_ms=self.elapsed_ms,
        )
        # A concurrent steering entry can be merged in the repository.
        # Only a successful persistence result may replace the live context.
        self.live.context = dict(persisted.research_context)
        return persisted


@dataclass(frozen=True, slots=True)
class ActiveRuntimeCheckpointRecorder:
    """Observe the existing durable checkpoint without owning its live values.

    Callers invoke ``checkpoint`` directly, so caller-name diagnostics retain
    their original stack depth and the executor has no timing closure.
    """

    session: ActiveRuntimeCheckpointSession
    live: ActiveRuntimeLiveValues
    elapsed_ms: Callable[[], float]
    timing_ledger: TimingLedger
    caller_name: Callable[[], str]
    record_timing: Callable[..., None]

    def checkpoint(self, *, stage: str | None = None) -> WebLookupRun:
        diagnostics: dict[str, Any] = {}
        started = self.elapsed_ms()
        try:
            return self.session.checkpoint(stage=stage, diagnostics=diagnostics)
        finally:
            # Telemetry may fail independently of the durable repository write.
            # Preserve both the successful result and the original checkpoint
            # exception; an observation error must never mask either one.
            try:
                self.timing_ledger.record_checkpoint(self.elapsed_ms() - started)
                self.record_timing(
                    self.live.current_context(),
                    diagnostics,
                    wall_ms=self.elapsed_ms() - started,
                    stage=stage,
                    caller=self.caller_name(),
                    phase=self.timing_ledger.current_phase(),
                )
            except Exception:
                _logger.exception("research checkpoint timing observation failed")


def _update_metrics(
    context: dict[str, Any],
    state: ResearchState,
    cursor: ResearchRuntimeCursor,
) -> None:
    context[ACTIVE_RESEARCH_METRICS_KEY] = {
        **(
            dict(context.get(ACTIVE_RESEARCH_METRICS_KEY) or {})
            if isinstance(context.get(ACTIVE_RESEARCH_METRICS_KEY), Mapping)
            else {}
        ),
        "candidate_count": len(cursor.candidates),
        "read_count": sum(item.status == "success" for item in cursor.read_outcomes),
        "cluster_count": len(state.source_clusters),
        "open_critical_gap_count": sum(
            gap.state in {"open", "searching"}
            and any(claim.id == gap.claim_id and claim.priority == "critical" for claim in state.claims)
            for gap in state.gaps
        ),
        "phase": cursor.phase,
    }
