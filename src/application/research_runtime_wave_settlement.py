"""One completed research wave's steering, stopping and checkpoint sequence.

The executor remains the owner of current mutable values and persistence. A
snapshot is short-lived and is handed back after every checkpoint, including
when an interrupted checkpoint raises after updating its in-memory projection.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from src.application.research_runtime_publication import ActiveResearchPublisher
from src.application.research_runtime_steering_context import (
    ActiveResearchSteeringContext,
)
from src.application.research_runtime_wave_stop_signal import completed_wave_stop_signal
from src.application.research_stop_gate import ResearchStopGate
from src.domain.runtime_entities import WebLookupRun
from src.web.research.contracts import EvidenceGap, ResearchState
from src.web.research.evidence_gate import EvidenceGateResult
from src.web.research.runtime import ResearchRuntimeCursor
from src.web.research.steering import _pending_active_steering_ids


@dataclass(slots=True)
class ActiveWaveSettlementSnapshot:
    """Current values, never a second persistence or budget authority."""

    state: ResearchState
    cursor: ResearchRuntimeCursor
    context: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ActiveWaveSettlementContext:
    """Bind stable run operations; always work on the supplied live snapshot."""

    steering: ActiveResearchSteeringContext
    ensure_active: Callable[[], None]
    elapsed: Callable[[], float]
    checkpoint: Callable[[ActiveWaveSettlementSnapshot], None]
    known_evidence_ids: Callable[[], tuple[str, ...]]
    actionable_gaps: Callable[[ResearchState], tuple[EvidenceGap, ...]]
    publisher: ActiveResearchPublisher
    max_research_waves: int

    def settle_completed_wave(
        self,
        snapshot: ActiveWaveSettlementSnapshot,
        gate: EvidenceGateResult,
        brief: Mapping[str, Any],
    ) -> WebLookupRun | None:
        """Advance or finish a gain-accounted wave, with original side-effect order."""

        self.ensure_active()
        snapshot.context = self.steering.refresh(snapshot.context)
        pending = _pending_active_steering_ids(snapshot.context)
        hard_exhausted = self.elapsed() >= snapshot.state.budget.hard_timeout_seconds
        wave_exhausted = snapshot.cursor.wave_index >= self.max_research_waves
        if pending and (hard_exhausted or wave_exhausted):
            snapshot.context, _late_ids = self.steering.mark_late(
                snapshot.context,
                reason=(
                    "hard_budget_exhausted" if hard_exhausted else "wave_limit_reached"
                ),
            )
            self.checkpoint(snapshot)
        elif pending:
            # Fresh user direction makes an old-graph gate pass inapplicable.
            next_wave = snapshot.cursor.wave_index + 1
            snapshot.state, snapshot.context, _applied_ids = (
                self.steering.apply_pending(
                    state=snapshot.state,
                    context=snapshot.context,
                    wave_index=next_wave,
                    known_evidence_ids=self.known_evidence_ids,
                )
            )
            snapshot.cursor = replace(
                snapshot.cursor,
                wave_index=next_wave,
                wave_id="",
                active_gap_ids=(),
                phase="searching",
            )
            self.checkpoint(snapshot)
            return None

        # The stop gate remains the sole stop-decision authority. Recompute
        # from context after checkpoint recovery or late-steering projection.
        stop = ResearchStopGate.evaluate(
            completed_wave_stop_signal(
                state=snapshot.state,
                cursor=snapshot.cursor,
                context=snapshot.context,
                gate=gate,
                actionable_gaps=self.actionable_gaps(snapshot.state),
                hard_exhausted=hard_exhausted,
                wave_exhausted=wave_exhausted,
            )
        )
        if stop.decision == "continue":
            snapshot.cursor = replace(
                snapshot.cursor,
                wave_index=snapshot.cursor.wave_index + 1,
                wave_id="",
                active_gap_ids=(),
                phase="searching",
            )
            self.checkpoint(snapshot)
            return None

        snapshot.cursor = replace(
            snapshot.cursor,
            phase="completed" if stop.decision == "success" else "unavailable",
        )
        self.checkpoint(snapshot)
        return self.publisher.complete(context=snapshot.context, stop=stop, brief=brief)
