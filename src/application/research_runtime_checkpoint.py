"""Durable checkpoint boundary for one active research execution.

The executor owns research decisions and the current mutable values. This
context owns the *ordered* projection of those values to a repository
checkpoint, without owning search, model calls or final publication.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from src.application.research_runtime_result_buffers import (
    ActiveResearchResultBuffers,
    _dedupe,
    _eligible_items,
)
from src.domain.runtime_entities import WebLookupRun
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.contracts import ResearchState
from src.web.research.runtime import ResearchRuntimeCursor, attach_runtime_cursor
from src.web.research.state import attach_claim_engine_state
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


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
