"""RQ-D v1: coverage-aware stop *assessment* (judgement only, advisory).

Frozen context: ``docs/PROJECT_STATUS.md`` §144.10.

This module answers one question: from a *semantic coverage* standpoint, is there
anything left that should keep research going? It composes the RQ-A assessment
(per-claim semantic adequacy) and the RQ-C assessment (per-claim conflict).

It is deliberately **advisory**: it never decides the engine's stop, never
changes gate/stop/routing, and is not consulted by them. It exists so a later
coverage-aware stop policy has a stable, testable input.

The distinction it exists to encode:

    "there is a lot of evidence" is not the same as
    "the critical claims are covered and their conflicts are resolved".

Evidence volume is reported for context and is never used in the rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.web.research.claim_conflict_assessment import (
    assess_claim_conflict,
)
from src.web.research.claim_evidence_assessment import (
    assess_claim_evidence,
)
from src.web.research.contracts import ResearchState

Recommendation = Literal["stop_candidate", "continue_candidate"]
CoverageStopStatus = Literal["covered", "gaps_remain", "conflict_unresolved"]

#: Adequacy values that block a coverage-based stop.
BLOCKING_ADEQUACY: frozenset[str] = frozenset({"partial", "insufficient"})

REASON_NO_CRITICAL_CLAIMS = "no_critical_claims"
REASON_ALL_CRITICAL_COVERED = "all_critical_claims_adequate"
REASON_SEMANTIC_GAP = "critical_claim_not_adequate"
REASON_CONFLICT_UNRESOLVED = "critical_conflict_unresolved"
REASON_NO_REQUIREMENT = "critical_claim_has_no_required_units"
REASON_VOLUME_NOT_USED = "evidence_volume_never_decides"


@dataclass(frozen=True)
class ClaimCoverageGap:
    claim_id: str
    priority: str
    semantic_adequacy: str
    missing_unit_count: int
    conflict_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "priority": self.priority,
            "semantic_adequacy": self.semantic_adequacy,
            "missing_unit_count": self.missing_unit_count,
            "conflict_status": self.conflict_status,
        }


@dataclass(frozen=True)
class CoverageStopAssessment:
    status: CoverageStopStatus
    recommendation: Recommendation
    critical_claim_count: int
    adequate_critical_claim_count: int
    blocking_claims: tuple[ClaimCoverageGap, ...] = ()
    unresolved_conflict_claim_ids: tuple[str, ...] = ()
    evidence_count: int = 0
    reasons: tuple[str, ...] = ()

    @property
    def blocks_stop(self) -> bool:
        return bool(self.blocking_claims) or bool(self.unresolved_conflict_claim_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "recommendation": self.recommendation,
            "critical_claim_count": self.critical_claim_count,
            "adequate_critical_claim_count": self.adequate_critical_claim_count,
            "blocking_claims": [item.to_dict() for item in self.blocking_claims],
            "unresolved_conflict_claim_ids": list(self.unresolved_conflict_claim_ids),
            "evidence_count": self.evidence_count,
            "reasons": list(self.reasons),
        }


def assess_coverage_stop(state: ResearchState) -> CoverageStopAssessment:
    """Judge whether coverage would justify stopping; pure and advisory."""

    critical_claims = [claim for claim in state.claims if claim.priority == "critical"]
    evidence_count = len(state.evidence)

    if not critical_claims:
        return CoverageStopAssessment(
            status="gaps_remain",
            recommendation="continue_candidate",
            critical_claim_count=0,
            adequate_critical_claim_count=0,
            evidence_count=evidence_count,
            reasons=(REASON_NO_CRITICAL_CLAIMS, REASON_VOLUME_NOT_USED),
        )

    blocking: list[ClaimCoverageGap] = []
    unresolved_conflicts: list[str] = []
    adequate_count = 0
    no_requirement = False

    for claim in critical_claims:
        evidence_assessment = assess_claim_evidence(state, claim)
        conflict = assess_claim_conflict(state, claim)

        if evidence_assessment.semantic_adequacy == "not_evaluated":
            no_requirement = True
        if evidence_assessment.semantic_adequacy == "adequate":
            adequate_count += 1

        conflict_unresolved = conflict.status == "unresolved_conflict"
        if conflict_unresolved:
            unresolved_conflicts.append(claim.id)

        semantic_gap = evidence_assessment.semantic_adequacy in BLOCKING_ADEQUACY
        if semantic_gap or conflict_unresolved:
            blocking.append(
                ClaimCoverageGap(
                    claim_id=claim.id,
                    priority=claim.priority,
                    semantic_adequacy=evidence_assessment.semantic_adequacy,
                    missing_unit_count=len(evidence_assessment.missing_units),
                    conflict_status=conflict.status,
                )
            )

    reasons: list[str] = [REASON_VOLUME_NOT_USED]
    if no_requirement:
        reasons.append(REASON_NO_REQUIREMENT)
    if any(
        item.semantic_adequacy in BLOCKING_ADEQUACY for item in blocking
    ):
        reasons.append(REASON_SEMANTIC_GAP)
    if unresolved_conflicts:
        reasons.append(REASON_CONFLICT_UNRESOLVED)

    if blocking:
        return CoverageStopAssessment(
            status=(
                "conflict_unresolved"
                if unresolved_conflicts
                else "gaps_remain"
            ),
            recommendation="continue_candidate",
            critical_claim_count=len(critical_claims),
            adequate_critical_claim_count=adequate_count,
            blocking_claims=tuple(blocking),
            unresolved_conflict_claim_ids=tuple(unresolved_conflicts),
            evidence_count=evidence_count,
            reasons=tuple(reasons),
        )

    return CoverageStopAssessment(
        status="covered",
        recommendation="stop_candidate",
        critical_claim_count=len(critical_claims),
        adequate_critical_claim_count=adequate_count,
        evidence_count=evidence_count,
        reasons=tuple([*reasons, REASON_ALL_CRITICAL_COVERED]),
    )


def safe_assess_coverage_stop(state: ResearchState) -> CoverageStopAssessment | None:
    """Keep shadow observability available if the assessor fails."""

    try:
        return assess_coverage_stop(state)
    except Exception:  # noqa: BLE001 - shadow observation must never raise
        return None
