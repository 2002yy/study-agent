"""Shadow-only stop decision derived from the deterministic Evidence Gate.

This module never decides the legacy output path. It records what the shadow
engine would have done and exposes a false-closure candidate metric while
preserving the legacy stop decision exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.web.research.claim_evidence_assessment import (
    ClaimEvidenceAssessment,
    safe_assess_research_state,
)
from src.web.research.claim_conflict_assessment import (
    ConflictAssessment,
    safe_assess_state_conflicts,
)
from src.web.research.coverage_stop_assessment import (
    CoverageStopAssessment,
    safe_assess_coverage_stop,
)
from src.web.research.contracts import ResearchState
from src.web.research.evidence_gate import EvidenceGateResult, evaluate_evidence_gate

ShadowGateStatus = Literal["pass", "block", "partial", "unavailable"]


@dataclass(frozen=True)
class ShadowStopDecision:
    legacy_would_stop: bool
    legacy_should_stop: bool
    shadow_status: ShadowGateStatus
    shadow_would_pass: bool
    shadow_would_block: bool
    legacy_would_stop_but_shadow_blocked: bool
    open_critical_claims: tuple[str, ...] = ()
    gap_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    gate_result: EvidenceGateResult | None = None
    #: RQ-A observability only; never consulted for any stop/gate decision.
    claim_assessments: tuple[ClaimEvidenceAssessment, ...] = ()
    #: RQ-C observability only; never consulted for any stop/gate decision.
    claim_conflicts: tuple[ConflictAssessment, ...] = ()
    #: RQ-D advisory coverage view; never consulted for any stop/gate decision.
    coverage_assessment: CoverageStopAssessment | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "legacy_would_stop": self.legacy_would_stop,
            "legacy_should_stop": self.legacy_should_stop,
            "shadow_status": self.shadow_status,
            "shadow_would_pass": self.shadow_would_pass,
            "shadow_would_block": self.shadow_would_block,
            "legacy_would_stop_but_shadow_blocked": (
                self.legacy_would_stop_but_shadow_blocked
            ),
            "open_critical_claims": list(self.open_critical_claims),
            "gap_ids": list(self.gap_ids),
            "reasons": list(self.reasons),
            "gate_result": self.gate_result.to_dict() if self.gate_result else None,
            "claim_assessments": [item.to_dict() for item in self.claim_assessments],
            "claim_conflicts": [item.to_dict() for item in self.claim_conflicts],
            "coverage_assessment": (
                self.coverage_assessment.to_dict() if self.coverage_assessment else None
            ),
        }


def evaluate_shadow_stop(
    state: ResearchState,
    *,
    legacy_would_stop: bool,
) -> ShadowStopDecision:
    """Compute shadow truth without changing the legacy decision."""

    gate = evaluate_evidence_gate(state)
    shadow_would_pass = gate.status in {"pass", "partial"}
    shadow_would_block = gate.status == "block"
    return ShadowStopDecision(
        legacy_would_stop=legacy_would_stop,
        legacy_should_stop=legacy_would_stop,
        shadow_status=gate.status,
        shadow_would_pass=shadow_would_pass,
        shadow_would_block=shadow_would_block,
        legacy_would_stop_but_shadow_blocked=(
            legacy_would_stop and shadow_would_block
        ),
        open_critical_claims=gate.open_critical_claims,
        gap_ids=gate.gap_ids,
        reasons=gate.reasons,
        gate_result=gate,
        claim_assessments=safe_assess_research_state(state),
        claim_conflicts=safe_assess_state_conflicts(state),
        coverage_assessment=safe_assess_coverage_stop(state),
    )


def safe_evaluate_shadow_stop(
    state: ResearchState,
    *,
    legacy_would_stop: bool,
) -> ShadowStopDecision:
    """Keep legacy behavior available if the shadow evaluator itself fails."""

    try:
        return evaluate_shadow_stop(state, legacy_would_stop=legacy_would_stop)
    except Exception:
        return ShadowStopDecision(
            legacy_would_stop=legacy_would_stop,
            legacy_should_stop=legacy_would_stop,
            shadow_status="unavailable",
            shadow_would_pass=False,
            shadow_would_block=False,
            legacy_would_stop_but_shadow_blocked=False,
            reasons=("shadow_gate_failed",),
        )
