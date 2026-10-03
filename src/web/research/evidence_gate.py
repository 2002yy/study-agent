"""Deterministic hard Evidence Gate for Claim Engine shadow evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from src.web.research.contracts import (
    ConflictGap,
    ResearchClaim,
    ResearchClaimEvidenceLink,
    ResearchEvidence,
    ResearchState,
)

EvidenceGateStatus = Literal["pass", "block", "partial"]
STRONG_EVIDENCE_THRESHOLD = 0.7


@dataclass(frozen=True)
class EvidenceGateResult:
    status: EvidenceGateStatus
    open_critical_claims: tuple[str, ...]
    gap_ids: tuple[str, ...]
    conflicts: tuple[ConflictGap, ...]
    reasons: tuple[str, ...]
    eligible_evidence_ids: tuple[str, ...]
    budget_exhausted: bool

    @property
    def allows_stop(self) -> bool:
        return self.status in {"pass", "partial"}

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "open_critical_claims": list(self.open_critical_claims),
            "gap_ids": list(self.gap_ids),
            "conflicts": [item.to_dict() for item in self.conflicts],
            "reasons": list(self.reasons),
            "eligible_evidence_ids": list(self.eligible_evidence_ids),
            "budget_exhausted": self.budget_exhausted,
            "allows_stop": self.allows_stop,
        }


def claim_support_topology(
    state: ResearchState,
    claim: ResearchClaim,
) -> tuple[int, int, bool]:
    """Eligible support topology for one claim: (clusters, required, has_primary).

    This mirrors the Gate's own eligible-support computation exactly (same
    structural + freshness eligibility, same ``supports`` relation and strength
    threshold). It is exposed for the bounded lead scheduler so "does this claim
    still have a discovery-shaped gap?" cannot drift from what the Gate actually
    requires. The Gate's own evaluation is unchanged.
    """

    evidence_by_id = {item.evidence_id: item for item in state.evidence}
    supports = []
    for link in state.evidence_links:
        if link.claim_id != claim.id:
            continue
        evidence = evidence_by_id.get(link.evidence_id)
        if not evidence_link_eligibility(
            claim=claim,
            link=link,
            evidence=evidence,
            reference_date=state.reference_date,
        ):
            continue
        if link.relation != "supports" or link.strength < STRONG_EVIDENCE_THRESHOLD:
            continue
        supports.append(link)
    clusters = {link.source_cluster_id for link in supports}
    required = claim.evidence_requirement.min_independent_sources
    has_primary = any(link.source_role == "primary" for link in supports)
    return len(clusters), required, has_primary


def evaluate_evidence_gate(state: ResearchState) -> EvidenceGateResult:
    """Evaluate only code-owned hard rules; never trust model closure flags."""

    evidence_by_id = {item.evidence_id: item for item in state.evidence}
    links_by_claim: dict[str, list[ResearchClaimEvidenceLink]] = {}
    for link in state.evidence_links:
        links_by_claim.setdefault(link.claim_id, []).append(link)

    open_claims: list[str] = []
    reasons: list[str] = []
    eligible_ids: set[str] = set()
    detected_conflicts: list[ConflictGap] = []
    existing_conflicts = {item.claim_id: item for item in state.conflict_gaps}

    critical_claims = [claim for claim in state.claims if claim.priority == "critical"]
    for claim in critical_claims:
        claim_links = links_by_claim.get(claim.id, [])
        structurally_eligible_links = [
            link
            for link in claim_links
            if _link_is_eligible(
                claim=claim,
                link=link,
                evidence=evidence_by_id.get(link.evidence_id),
            )
        ]
        eligible_links = [
            link
            for link in structurally_eligible_links
            if _link_meets_freshness(
                claim=claim,
                evidence=evidence_by_id.get(link.evidence_id),
                reference_date=state.reference_date,
            )
        ]
        eligible_ids.update(link.evidence_id for link in eligible_links)
        supports = [
            link
            for link in eligible_links
            if link.relation == "supports"
            and link.strength >= STRONG_EVIDENCE_THRESHOLD
        ]
        contradictions = [
            link
            for link in eligible_links
            if link.relation == "contradicts"
            and link.strength >= STRONG_EVIDENCE_THRESHOLD
        ]

        conflict = _conflict_for_claim(
            claim=claim,
            supports=supports,
            contradictions=contradictions,
            existing=existing_conflicts.get(claim.id),
        )
        if conflict is not None:
            detected_conflicts.append(conflict)
            open_claims.append(claim.id)
            reasons.append(f"critical:{claim.id}:strong_conflict")
            continue

        support_clusters = {link.source_cluster_id for link in supports}
        required_clusters = claim.evidence_requirement.min_independent_sources
        has_primary = any(link.source_role == "primary" for link in supports)
        satisfied = (
            claim.state != "unavailable"
            and len(support_clusters) >= required_clusters
            and (
                not claim.evidence_requirement.requires_primary_source or has_primary
            )
        )
        if satisfied:
            continue

        open_claims.append(claim.id)
        if claim.state == "unavailable":
            reasons.append(f"critical:{claim.id}:unavailable_not_satisfied")
        if len(support_clusters) < required_clusters:
            reasons.append(
                f"critical:{claim.id}:eligible_support_clusters="
                f"{len(support_clusters)}/{required_clusters}"
            )
        if claim.evidence_requirement.requires_primary_source and not has_primary:
            reasons.append(f"critical:{claim.id}:primary_required")
        if len(eligible_links) < len(structurally_eligible_links):
            reasons.append(f"critical:{claim.id}:freshness_required")

    open_set = set(open_claims)
    active_gaps = [
        gap
        for gap in state.gaps
        if gap.claim_id in open_set and gap.state in {"open", "searching"}
    ]
    gap_ids = tuple(sorted(gap.id for gap in active_gaps))
    claims_with_gaps = {gap.claim_id for gap in active_gaps}
    for claim_id in sorted(open_set - claims_with_gaps):
        reasons.append(f"critical:{claim_id}:evidence_gap_missing")

    exhausted = _budget_exhausted(state)
    status: EvidenceGateStatus
    if not critical_claims:
        status = "block"
        reasons.append("claim_graph:no_critical_claims")
    elif not open_claims:
        status = "pass"
    elif exhausted:
        status = "partial"
        reasons.append("budget:hard_exhausted_with_open_critical_claims")
    else:
        status = "block"

    return EvidenceGateResult(
        status=status,
        open_critical_claims=tuple(sorted(open_set)),
        gap_ids=gap_ids,
        conflicts=tuple(sorted(detected_conflicts, key=lambda item: item.id)),
        reasons=tuple(sorted(set(reasons))),
        eligible_evidence_ids=tuple(sorted(eligible_ids)),
        budget_exhausted=exhausted,
    )


def evidence_link_structurally_eligible(
    *,
    claim: ResearchClaim,
    link: ResearchClaimEvidenceLink,
    evidence: ResearchEvidence | None,
) -> bool:
    """Single source of truth for structural link eligibility (R2).

    Shared by the Evidence Gate and Evidence Gain so the two can never drift
    into a second, weaker eligibility truth: the role must be one the claim's
    requirement accepts, the link must carry a cluster, the evidence must be
    extraction-eligible, and (unless the requirement waives it) it must come
    from a successful read.
    """
    if evidence is None:
        return False
    if link.source_role not in claim.evidence_requirement.source_roles:
        return False
    if not link.source_cluster_id:
        return False
    if evidence.extraction_status != "eligible":
        return False
    if claim.evidence_requirement.requires_successful_read:
        return evidence.lifecycle_status in {"read", "selected"}
    return evidence.lifecycle_status != "rejected"


def evidence_link_meets_freshness(
    *,
    claim: ResearchClaim,
    evidence: ResearchEvidence | None,
    reference_date: str,
) -> bool:
    """Single source of truth for freshness eligibility (shared with Gain)."""
    requirement = claim.evidence_requirement
    if requirement.max_age_days is None and not requirement.requires_dated_evidence:
        return True
    if evidence is None or not evidence.published_at:
        return False
    try:
        published = date.fromisoformat(evidence.published_at)
        reference = date.fromisoformat(reference_date)
    except ValueError:
        return False
    age_days = (reference - published).days
    if age_days < 0:
        return False
    if requirement.max_age_days is not None and age_days > requirement.max_age_days:
        return False
    return True


def evidence_link_eligibility(
    *,
    claim: ResearchClaim,
    link: ResearchClaimEvidenceLink,
    evidence: ResearchEvidence | None,
    reference_date: str,
) -> bool:
    """Full (structural + freshness) eligibility, shared by Gate and Gain."""
    return evidence_link_structurally_eligible(
        claim=claim, link=link, evidence=evidence
    ) and evidence_link_meets_freshness(
        claim=claim, evidence=evidence, reference_date=reference_date
    )


def _link_is_eligible(
    *,
    claim: ResearchClaim,
    link: ResearchClaimEvidenceLink,
    evidence: ResearchEvidence | None,
) -> bool:
    return evidence_link_structurally_eligible(
        claim=claim, link=link, evidence=evidence
    )


def _link_meets_freshness(
    *,
    claim: ResearchClaim,
    evidence: ResearchEvidence | None,
    reference_date: str,
) -> bool:
    return evidence_link_meets_freshness(
        claim=claim, evidence=evidence, reference_date=reference_date
    )


def _conflict_for_claim(
    *,
    claim: ResearchClaim,
    supports: list[ResearchClaimEvidenceLink],
    contradictions: list[ResearchClaimEvidenceLink],
    existing: ConflictGap | None,
) -> ConflictGap | None:
    if not supports or not contradictions:
        return None
    if existing is not None:
        return existing
    return ConflictGap(
        id=f"gate_conflict_{claim.id}",
        claim_id=claim.id,
        supporting_evidence_ids=tuple(sorted({link.evidence_id for link in supports})),
        contradicting_evidence_ids=tuple(
            sorted({link.evidence_id for link in contradictions})
        ),
    )


def _budget_exhausted(state: ResearchState) -> bool:
    budget = state.budget
    return (
        budget.candidates_used >= budget.max_candidates
        or budget.reads_used >= budget.max_reads
        or budget.elapsed_seconds >= budget.hard_timeout_seconds
    )
