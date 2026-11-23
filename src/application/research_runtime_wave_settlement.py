"""One completed research wave's steering, stopping and checkpoint sequence.

The executor owns the single live state/cursor/context and physical checkpoints.
Settlement writes to that owner directly, including when persistence interrupts
after preparing an in-memory checkpoint projection.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_publication import ActiveResearchPublisher
from src.application.research_runtime_result_buffers import ActiveResearchResultBuffers
from src.application.research_runtime_steering_context import (
    ActiveResearchSteeringContext,
)
from src.application.research_runtime_wave_stop_signal import completed_wave_stop_signal
from src.application.research_stop_gate import ResearchStopGate
from src.domain.runtime_entities import WebLookupRun
from src.web.research.contracts import EvidenceGap, ResearchState
from src.web.research.evidence_gate import EvidenceGateResult
from src.web.research.steering import _pending_active_steering_ids


@dataclass(frozen=True, slots=True)
class ActiveWaveSettlementContext:
    """Bind stable run operations to the one mutable recovery-safe owner."""

    live: ActiveRuntimeLiveValues
    steering: ActiveResearchSteeringContext
    ensure_active: Callable[[], None]
    elapsed: Callable[[], float]
    checkpoint: Callable[[], object]
    results: ActiveResearchResultBuffers
    run_id: str
    actionable_gaps: Callable[[ResearchState], tuple[EvidenceGap, ...]]
    publisher: ActiveResearchPublisher
    max_research_waves: int

    def settle_completed_wave(
        self,
        gate: EvidenceGateResult,
        brief: Mapping[str, Any],
    ) -> WebLookupRun | None:
        """Advance or finish a gain-accounted wave, with original side-effect order."""

        self.ensure_active()
        self.live.context = self.steering.refresh(self.live.context)
        pending = _pending_active_steering_ids(self.live.context)
        hard_exhausted = self.elapsed() >= self.live.state.budget.hard_timeout_seconds
        wave_exhausted = self.live.cursor.wave_index >= self.max_research_waves
        if pending and (hard_exhausted or wave_exhausted):
            self.live.context, _late_ids = self.steering.mark_late(
                self.live.context,
                reason=(
                    "hard_budget_exhausted" if hard_exhausted else "wave_limit_reached"
                ),
            )
            self.checkpoint()
        elif pending:
            # Fresh user direction makes an old-graph gate pass inapplicable.
            next_wave = self.live.cursor.wave_index + 1
            self.live.state, self.live.context, _applied_ids = (
                self.steering.apply_pending(
                    state=self.live.state,
                    context=self.live.context,
                    wave_index=next_wave,
                    known_evidence_ids=lambda: self.results.known_evidence_ids(
                        self.run_id
                    ),
                )
            )
            self.live.cursor = replace(
                self.live.cursor,
                wave_index=next_wave,
                wave_id="",
                active_gap_ids=(),
                phase="searching",
            )
            self.checkpoint()
            return None

        # The stop gate remains the sole stop-decision authority. Recompute
        # from context after checkpoint recovery or late-steering projection.
        stop = ResearchStopGate.evaluate(
            completed_wave_stop_signal(
                state=self.live.state,
                cursor=self.live.cursor,
                context=self.live.context,
                gate=gate,
                actionable_gaps=self.actionable_gaps(self.live.state),
                hard_exhausted=hard_exhausted,
                wave_exhausted=wave_exhausted,
            )
        )
        if stop.decision == "continue":
            self.live.cursor = replace(
                self.live.cursor,
                wave_index=self.live.cursor.wave_index + 1,
                wave_id="",
                active_gap_ids=(),
                phase="searching",
            )
            self.checkpoint()
            return None

        self.live.cursor = replace(
            self.live.cursor,
            phase="completed" if stop.decision == "success" else "unavailable",
        )
        self.checkpoint()
        return self.publisher.complete(
            context=self.live.context, stop=stop, brief=brief
        )
