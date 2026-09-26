"""RQ-A pure assessor: Claim <-> Evidence coverage + semantic adequacy.

Frozen contract: ``docs/PROJECT_STATUS.md`` §144.1 / §144.6.

This module only *judges* the current claim contract against evidence that
already exists. It never searches for more evidence, never decides whether to
continue research, and never generates or infers ``required_units`` — those are
declared claim-side (explicit fixture / frozen claim contract).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.web.research.contracts import (
    ResearchClaim,
    ResearchClaimEvidenceLink,
    ResearchClaimState,
    ResearchEvidence,
    ResearchState,
)
from src.web.research.evidence_gate import (
    STRONG_EVIDENCE_THRESHOLD,
    evidence_link_eligibility,
)
from src.web.research.evidence_units import RequiredUnit, unit_satisfies_modality

SemanticAdequacy = Literal["adequate", "partial", "insufficient", "not_evaluated"]

REASON_NO_ELIGIBLE_SUPPORT = "no_eligible_support"
REASON_CONFLICTING_EVIDENCE = "conflicting_evidence"
REASON_STRUCTURE_SHORT = "structure_short"
REASON_PRIMARY_SOURCE_MISSING = "primary_source_missing"
REASON_STRUCTURE_MET = "structure_met"
REASON_NO_REQUIRED_UNITS = "no_required_units"
REASON_REQUIRED_UNITS_MISSING = "required_units_missing"
REASON_REQUIRED_UNITS_MET = "required_units_met"


@dataclass(frozen=True)
class ClaimEvidenceAssessment:
    """Deterministic judgement of one claim against eligible evidence."""

    claim_id: str
    state: ResearchClaimState
    semantic_adequacy: SemanticAdequacy
    supporting_clusters: int
    required_clusters: int
    has_primary: bool
    contradicting_clusters: int
    required_units: tuple[RequiredUnit, ...] = ()
    covered_units: tuple[RequiredUnit, ...] = ()
    missing_units: tuple[RequiredUnit, ...] = ()
    supporting_evidence: tuple[str, ...] = ()
    contradicting_evidence: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def structural_coverage(self) -> float:
        """``supporting_clusters / required_clusters`` (1.0 when none required)."""

        if self.required_clusters <= 0:
            return 1.0
        return self.supporting_clusters / self.required_clusters

    @property
    def semantic_coverage(self) -> float | None:
        """``covered_units / required_units`` or ``None`` when not evaluated."""

        if not self.required_units:
            return None
        return len(self.covered_units) / len(self.required_units)

    @property
    def conflict_flag(self) -> bool:
        return self.contradicting_clusters > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "state": self.state,
            "semantic_adequacy": self.semantic_adequacy,
            "supporting_clusters": self.supporting_clusters,
            "required_clusters": self.required_clusters,
            "has_primary": self.has_primary,
            "contradicting_clusters": self.contradicting_clusters,
            "structural_coverage": self.structural_coverage,
            "semantic_coverage": self.semantic_coverage,
            "conflict_flag": self.conflict_flag,
            "required_units": [unit.to_dict() for unit in self.required_units],
            "covered_units": [unit.to_dict() for unit in self.covered_units],
            "missing_units": [unit.to_dict() for unit in self.missing_units],
            "supporting_evidence": list(self.supporting_evidence),
            "contradicting_evidence": list(self.contradicting_evidence),
            "reasons": list(self.reasons),
        }


def assess_claim_evidence(
    state: ResearchState,
    claim: ResearchClaim,
) -> ClaimEvidenceAssessment:
    """Judge one claim; pure and side-effect free."""

    requirement = claim.evidence_requirement
    evidence_by_id = {item.evidence_id: item for item in state.evidence}

    supports: list[ResearchClaimEvidenceLink] = []
    contradictions: list[ResearchClaimEvidenceLink] = []
    for link in state.evidence_links:
        if link.claim_id != claim.id:
            continue
        if link.strength < STRONG_EVIDENCE_THRESHOLD:
            continue
        if not evidence_link_eligibility(
            claim=claim,
            link=link,
            evidence=evidence_by_id.get(link.evidence_id),
            reference_date=state.reference_date,
        ):
            continue
        if link.relation == "supports":
            supports.append(link)
        elif link.relation == "contradicts":
            contradictions.append(link)

    supporting_clusters = len({link.source_cluster_id for link in supports})
    required_clusters = requirement.min_independent_sources
    has_primary = any(link.source_role == "primary" for link in supports)
    contradicting_clusters = len({link.source_cluster_id for link in contradictions})

    required_units = requirement.required_units
    covered_units, missing_units = _split_units(required_units, supports, evidence_by_id)

    semantic_adequacy = _semantic_adequacy(required_units, covered_units, missing_units)
    structural_ok = supporting_clusters >= required_clusters and (
        not requirement.requires_primary_source or has_primary
    )
    units_ok = not required_units or not missing_units

    if contradicting_clusters > 0 and supporting_clusters > 0:
        claim_state: ResearchClaimState = "contested"
    elif structural_ok and units_ok:
        claim_state = "satisfied"
    elif structural_ok or supporting_clusters > 0:
        claim_state = "partially_satisfied"
    else:
        claim_state = "unresolved"

    return ClaimEvidenceAssessment(
        claim_id=claim.id,
        state=claim_state,
        semantic_adequacy=semantic_adequacy,
        supporting_clusters=supporting_clusters,
        required_clusters=required_clusters,
        has_primary=has_primary,
        contradicting_clusters=contradicting_clusters,
        required_units=required_units,
        covered_units=covered_units,
        missing_units=missing_units,
        supporting_evidence=tuple(sorted({link.evidence_id for link in supports})),
        contradicting_evidence=tuple(
            sorted({link.evidence_id for link in contradictions})
        ),
        reasons=_reasons(
            requirement=requirement,
            supporting_clusters=supporting_clusters,
            required_clusters=required_clusters,
            has_primary=has_primary,
            contradicting_clusters=contradicting_clusters,
            required_units=required_units,
            missing_units=missing_units,
        ),
    )


def assess_research_state(state: ResearchState) -> tuple[ClaimEvidenceAssessment, ...]:
    """Assess every claim in the state (observability only, never mutating)."""

    return tuple(assess_claim_evidence(state, claim) for claim in state.claims)


def safe_assess_research_state(
    state: ResearchState,
) -> tuple[ClaimEvidenceAssessment, ...]:
    """Keep shadow observability available if the assessor itself fails."""

    try:
        return assess_research_state(state)
    except Exception:  # noqa: BLE001 - shadow observation must never raise
        return ()


def _split_units(
    required_units: tuple[RequiredUnit, ...],
    supports: list[ResearchClaimEvidenceLink],
    evidence_by_id: dict[str, ResearchEvidence],
) -> tuple[tuple[RequiredUnit, ...], tuple[RequiredUnit, ...]]:
    if not required_units:
        return (), ()
    covered_keys: set[tuple[str, str]] = set()
    for link in supports:
        evidence = evidence_by_id.get(link.evidence_id)
        if evidence is None:
            continue
        for unit in evidence.units:
            covered_keys.add((unit.unit_id, unit.source_type))
    covered: list[RequiredUnit] = []
    missing: list[RequiredUnit] = []
    for required in required_units:
        if any(
            unit_id == required.unit_id
            and unit_satisfies_modality(source_type=source_type, modality=required.modality)
            for unit_id, source_type in covered_keys
        ):
            covered.append(required)
        else:
            missing.append(required)
    return tuple(covered), tuple(missing)


def _semantic_adequacy(
    required_units: tuple[RequiredUnit, ...],
    covered_units: tuple[RequiredUnit, ...],
    missing_units: tuple[RequiredUnit, ...],
) -> SemanticAdequacy:
    if not required_units:
        return "not_evaluated"
    if not missing_units:
        return "adequate"
    if covered_units:
        return "partial"
    return "insufficient"


def _reasons(
    *,
    requirement: object,
    supporting_clusters: int,
    required_clusters: int,
    has_primary: bool,
    contradicting_clusters: int,
    required_units: tuple[RequiredUnit, ...],
    missing_units: tuple[RequiredUnit, ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if supporting_clusters == 0:
        reasons.append(REASON_NO_ELIGIBLE_SUPPORT)
    if contradicting_clusters > 0 and supporting_clusters > 0:
        reasons.append(REASON_CONFLICTING_EVIDENCE)
    if supporting_clusters < required_clusters:
        reasons.append(REASON_STRUCTURE_SHORT)
    elif getattr(requirement, "requires_primary_source", False) and not has_primary:
        reasons.append(REASON_PRIMARY_SOURCE_MISSING)
    else:
        reasons.append(REASON_STRUCTURE_MET)
    if not required_units:
        reasons.append(REASON_NO_REQUIRED_UNITS)
    elif missing_units:
        reasons.append(REASON_REQUIRED_UNITS_MISSING)
    else:
        reasons.append(REASON_REQUIRED_UNITS_MET)
    return tuple(reasons)
