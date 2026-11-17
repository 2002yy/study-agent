"""Checkpoint boundary for one active research execution.

The caller owns the live state and cursor.  A checkpoint receives one explicit
snapshot of those values and returns the budget-adjusted state and prepared
context *before* writing, preserving the in-memory state if persistence fails.
The repository remains the sole authority for durable writes and CAS merges.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from src.domain.runtime_entities import WebLookupRun
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.contracts import ResearchState
from src.web.research.runtime import (
    ResearchRuntimeCursor,
    attach_runtime_cursor,
)
from src.web.research.state import attach_claim_engine_state
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY
from src.application.active_research_evidence_projection import _evidence_snapshot


@dataclass(frozen=True, slots=True)
class ResearchCheckpointExecutionContext:
    """All inputs required to prepare and persist one recoverable checkpoint."""

    repository: WebLookupRepository
    run_id: str
    operation_id: str
    state: ResearchState
    cursor: ResearchRuntimeCursor
    research_context: dict[str, Any]
    query_attempts: list[dict[str, Any]]
    selected_sources: list[dict[str, Any]]
    rejected_sources: list[dict[str, Any]]
    warnings: list[str]
    elapsed_seconds: Callable[[], float]
    elapsed_ms: Callable[[], float]

    def prepare(
        self, *, stage: str | None = None
    ) -> tuple[ResearchState, dict[str, Any]]:
        """Stage transition -> budget -> cursor -> research graph -> metrics."""

        if stage is not None:
            run = self.repository.get(self.run_id)
            if run is None:
                raise ValueError(f"WebLookupRun not found: {self.run_id}")
            if run.stage != stage:
                self.repository.set_stage(
                    self.run_id,
                    stage=stage,
                    operation_id=self.operation_id,
                )
        budget = self.state.budget
        state = replace(
            self.state,
            budget=replace(
                budget,
                candidates_used=min(len(self.cursor.candidates), budget.max_candidates),
                reads_used=budget.reads_used,
                elapsed_seconds=self.elapsed_seconds(),
            ),
        )
        context = attach_runtime_cursor(self.research_context, self.cursor)
        snapshot = _evidence_snapshot(
            self.run_id,
            self.selected_sources,
            self.rejected_sources,
        )
        context = attach_claim_engine_state(
            context,
            state,
            known_evidence_ids=tuple(ref.id for ref in snapshot.refs),
        )
        _update_metrics(context, state, self.cursor)
        return state, context

    def persist(
        self,
        *,
        prepared_context: dict[str, Any],
        diagnostics: dict[str, Any],
    ) -> WebLookupRun:
        """Write prepared facts; repository may merge concurrent steering."""

        started = self.elapsed_ms()
        persisted = self.repository.checkpoint(
            self.run_id,
            operation_id=self.operation_id,
            research_context=prepared_context,
            query_attempts=self.query_attempts,
            selected_sources=self.selected_sources,
            rejected_sources=self.rejected_sources,
            items=_eligible_items(self.selected_sources),
            warnings=_dedupe(self.warnings),
            provider_status="",
            stop_reason="",
            answer_confidence="",
            diagnostics=diagnostics,
        )
        diagnostics["repo_call_ms"] = round(self.elapsed_ms() - started, 1)
        return persisted


def _eligible_items(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(record.get("item") or {})
        for record in records
        if isinstance(record.get("extraction"), Mapping)
        and record["extraction"].get("status") == "eligible"
    ]


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


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value)[:500] for value in values if str(value).strip()))
