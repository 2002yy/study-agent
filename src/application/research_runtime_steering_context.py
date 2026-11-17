"""Run-bound steering actions with explicit, current research state.

Steering can rebind the executor's research context after a durable checkpoint.
This object retains only stable dependencies; callers supply the current state
and context on every operation. Checkpoint ownership stays in the executor.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.contracts import ResearchState
from src.web.research.steering import (
    _apply_pending_active_steering,
    _mark_pending_active_steering_late,
    merge_active_steering_context,
)
from src.web.research.timing_ledger import TimingLedger


@dataclass(frozen=True, slots=True)
class ActiveResearchSteeringContext:
    """Coordinate one run's steering without caching rebound state or context."""

    repository: WebLookupRepository
    run_id: str
    utc_now: Callable[[], str]
    elapsed_ms: Callable[[], float]
    timing_ledger: TimingLedger

    def refresh(self, context: dict[str, Any]) -> dict[str, Any]:
        """Merge the latest durable steering and retain refresh timing order."""

        started = self.elapsed_ms()
        run = self.repository.get(self.run_id)
        if run is None:
            raise ValueError(f"WebLookupRun not found: {self.run_id}")
        merged = merge_active_steering_context(context, run.research_context)
        self.timing_ledger.record_refresh(self.elapsed_ms() - started)
        return merged

    def apply_pending(
        self,
        *,
        state: ResearchState,
        context: dict[str, Any],
        wave_index: int,
        known_evidence_ids: Callable[[], tuple[str, ...]],
    ) -> tuple[ResearchState, dict[str, Any], tuple[str, ...]]:
        """Project pending directions once using the caller's current graph."""

        return _apply_pending_active_steering(
            state,
            context,
            run_id=self.run_id,
            wave_index=wave_index,
            applied_at=self.utc_now(),
            known_evidence_ids=known_evidence_ids(),
        )

    def mark_late(
        self, context: dict[str, Any], *, reason: str
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        """Preserve late directions in current context before checkpointing."""

        return _mark_pending_active_steering_late(context, reason=reason)
