"""Derive the durable stop signal for a completed research wave.

The executor owns pending steering, time sampling, checkpoints, and wave
advancement.  This projection consumes their current values and leaves the
frozen ResearchStopGate as the only authority for deciding whether to stop.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.application.research_stop_gate import ResearchStopSignal
from src.web.research.contracts import EvidenceGap, ResearchState
from src.web.research.evidence_gain import SaturationState, saturated_claim_ids
from src.web.research.evidence_gate import EvidenceGateResult
from src.web.research.runtime import ResearchRuntimeCursor
from src.web.research.steering import _unapplied_steering_blocks_completion


def completed_wave_stop_signal(
    *,
    state: ResearchState,
    cursor: ResearchRuntimeCursor,
    context: Mapping[str, Any],
    gate: EvidenceGateResult,
    actionable_gaps: Sequence[EvidenceGap],
    hard_exhausted: bool,
    wave_exhausted: bool,
) -> ResearchStopSignal:
    """Project the same actionable scope, saturation and late-steering truth.

    ``actionable_gaps`` is computed by the executor's shared ``_ordered_gaps``
    planning selector. Context-priority gaps cannot keep a saturated wave
    alive, and only the current (possibly recovered) context supplies the late
    steering signal.
    """

    open_gap_claims = {gap.claim_id for gap in actionable_gaps}
    extra_batch_claims = {
        claim.id for claim in state.claims if claim.priority == "critical"
    } | {conflict.claim_id for conflict in state.conflict_gaps}
    saturated_claims = set(
        saturated_claim_ids(
            SaturationState(
                no_gain_batches_by_claim=dict(cursor.no_gain_batches_by_claim)
            ),
            extra_batch_eligible_claim_ids=extra_batch_claims,
        )
    )
    unapplied_steering = _unapplied_steering_blocks_completion(context)
    return ResearchStopSignal(
        gate_pass=gate.status == "pass",
        hard_budget_exhausted=hard_exhausted,
        has_actionable_gaps=bool(open_gap_claims) or unapplied_steering,
        all_actionable_saturated=bool(open_gap_claims)
        and open_gap_claims <= saturated_claims,
        wave_limit_reached=wave_exhausted,
        has_evidence=bool(state.evidence),
        unapplied_steering_blocks_completion=unapplied_steering,
    )
