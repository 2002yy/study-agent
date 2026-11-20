"""Resume-safe evidence and discovery progress accounting for one wave.

The executor keeps the gate, checkpoint, budget and stop decisions. This
context reads the single live owner at each boundary and only projects the
frozen gain/saturation result onto its cursor and bounded diagnostics.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.web.research.contracts import ResearchState
from src.web.research.evidence_gain import (
    GapBatchDelta,
    SaturationState,
    evaluate_evidence_gain,
    update_saturation,
)
from src.web.research.evidence_gate import EvidenceGateResult
from src.web.research.runtime import ResearchRuntimeCursor
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


@dataclass(frozen=True, slots=True)
class DiscoveryProgressSnapshot:
    """Three pre-lead counters, not a retained cursor or context reference."""

    candidate_count: int
    discovery_count: int
    followup_count: int


def _discovery_candidate_count(cursor: ResearchRuntimeCursor) -> int:
    return sum(
        1
        for candidate in cursor.candidates
        if candidate.discovery_method in {"lead_url", "evidence_lead_url"}
    )


@dataclass(frozen=True, slots=True)
class ActiveWaveProgressContext:
    """Own post-gate progress projection, never the durable checkpoint."""

    live: ActiveRuntimeLiveValues
    gap_provenance: Callable[
        [ResearchRuntimeCursor, ResearchState, EvidenceGateResult, tuple[str, ...]],
        Mapping[str, GapBatchDelta],
    ]
    max_research_waves: int

    def capture_before_lead(self) -> DiscoveryProgressSnapshot:
        cursor = self.live.current_cursor()
        return DiscoveryProgressSnapshot(
            candidate_count=_discovery_candidate_count(cursor),
            discovery_count=len(cursor.lead_discoveries),
            followup_count=len(cursor.evidence_lead_followups),
        )

    def record_after_gate(
        self,
        *,
        baseline: ResearchState,
        gate: EvidenceGateResult,
        before_lead: DiscoveryProgressSnapshot,
    ) -> None:
        """Record gain before checkpoint; discovery only defers saturation.

        In particular, neither newly found URLs nor lead hints can reset
        historical no-gain counters or become substantive evidence by fiat.
        """
        cursor = self.live.current_cursor()
        state = self.live.current_state()
        handled_gap_ids = tuple(cursor.active_gap_ids)
        handled_claim_ids = tuple(
            dict.fromkeys(
                gap.claim_id for gap in state.gaps if gap.id in set(handled_gap_ids)
            )
        )
        gain = evaluate_evidence_gain(
            baseline,
            state,
            target_gap_ids=handled_gap_ids,
            gain_provenance_by_gap=self.gap_provenance(
                cursor, state, gate, handled_gap_ids
            ),
        )
        saturation = update_saturation(
            SaturationState(
                no_gain_batches_by_claim=dict(cursor.no_gain_batches_by_claim),
                no_gain_batches_by_gap=dict(cursor.no_gain_batches_by_gap),
            ),
            gain,
            handled_claim_ids=handled_claim_ids,
            handled_gap_ids=handled_gap_ids,
        )
        evidence_progress = bool(gain.substantive_gain)
        discovered_candidates_after = _discovery_candidate_count(cursor)
        new_discovery_payloads = cursor.lead_discoveries[
            before_lead.discovery_count :
        ]
        new_discovery_assets = any(
            bool(payload.get("discovered_urls"))
            or bool(payload.get("domains"))
            or bool(payload.get("organizations"))
            or bool(payload.get("primary_source_hints"))
            for payload in new_discovery_payloads
            if isinstance(payload, Mapping)
        )
        discovery_progress = (
            discovered_candidates_after > before_lead.candidate_count
            or new_discovery_assets
            or any(
                str(item.get("hint_domain") or "")
                for item in cursor.evidence_lead_followups[
                    before_lead.followup_count :
                ]
                if isinstance(item, Mapping)
            )
        )
        no_gain_incremented = not (evidence_progress or discovery_progress)
        if no_gain_incremented:
            self.live.set_cursor(
                replace(
                    cursor,
                    gain_history=(*cursor.gain_history, gain.to_dict()),
                    no_gain_batches_by_claim=dict(saturation.no_gain_batches_by_claim),
                    no_gain_batches_by_gap=dict(saturation.no_gain_batches_by_gap),
                )
            )
        else:
            self.live.set_cursor(
                replace(cursor, gain_history=(*cursor.gain_history, gain.to_dict()))
            )

        # A checkpoint or steering operation may have rebound the context.
        metrics: dict[str, Any] = self.live.current_context().setdefault(
            ACTIVE_RESEARCH_METRICS_KEY, {}
        )
        wave_progress = metrics.get("wave_progress")
        if not isinstance(wave_progress, list):
            wave_progress = []
        wave_progress.append(
            {
                "wave_index": self.live.current_cursor().wave_index,
                "evidence_progress": evidence_progress,
                "discovery_progress": discovery_progress,
                "discovered_candidates_added": max(
                    0, discovered_candidates_after - before_lead.candidate_count
                ),
                "no_gain_incremented": no_gain_incremented,
            }
        )
        metrics["wave_progress"] = wave_progress[-self.max_research_waves :]
