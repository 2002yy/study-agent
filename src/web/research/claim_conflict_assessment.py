"""RQ-C: stable evidence-conflict model for one claim.

Frozen context: ``docs/PROJECT_STATUS.md`` §144.9.

This module only *judges* the conflict that already exists between eligible
evidence for a claim. It never searches, never decides to continue research,
never changes stop/gate/routing, and never picks a truth winner by counting
sources.

v1 model:

* supporting and contradicting evidence are kept strictly separate;
* each evidence carries ``authority`` (canonical source-role rank), ``freshness``
  and ``directness`` (does the link speak to the claim);
* ``contested`` never implies a winner: preference is reported only when an
  explicit rule is strong enough, otherwise the conflict stays unresolved;
* source counts are never used to decide which side is preferred;
* **freshness is not re-litigated here**: link eligibility already filters it
  (``evidence_link_eligibility`` is the single freshness truth), so this module
  reports each standing's freshness but never builds a second, weaker rule on
  top of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.web.research.contracts import (
    ResearchClaim,
    ResearchClaimEvidenceLink,
    ResearchEvidence,
    ResearchState,
)
from src.web.research.evidence_gate import (
    STRONG_EVIDENCE_THRESHOLD,
    evidence_link_eligibility,
    evidence_link_meets_freshness,
)
from src.web.research.policy import SOURCE_ROLE_AUTHORITY_ORDER

ConflictStatus = Literal["none", "unresolved_conflict", "preferred_side"]
PreferredSide = Literal["support", "contradict", ""]

#: Relations that speak directly to the claim itself (vs. background/lead).
DIRECT_RELATIONS: frozenset[str] = frozenset({"supports", "contradicts"})

REASON_NO_CONFLICT = "no_conflict"
REASON_AUTHORITY_GAP = "authority_gap"
REASON_TIED_AUTHORITY = "tied_authority"
REASON_COUNT_NOT_USED = "source_count_never_decides"


def authority_rank(source_role: str) -> int:
    """Canonical authority rank (0 = strongest); unknown roles rank last."""

    try:
        return SOURCE_ROLE_AUTHORITY_ORDER.index(source_role)  # type: ignore[arg-type]
    except ValueError:
        return len(SOURCE_ROLE_AUTHORITY_ORDER)


@dataclass(frozen=True)
class EvidenceStanding:
    evidence_id: str
    relation: str
    source_role: str
    authority_rank: int
    fresh: bool
    direct: bool
    strength: float

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "relation": self.relation,
            "source_role": self.source_role,
            "authority_rank": self.authority_rank,
            "fresh": self.fresh,
            "direct": self.direct,
            "strength": self.strength,
        }


@dataclass(frozen=True)
class ConflictAssessment:
    claim_id: str
    status: ConflictStatus
    preferred_side: PreferredSide
    supporting: tuple[EvidenceStanding, ...] = ()
    contradicting: tuple[EvidenceStanding, ...] = ()
    preferred_evidence_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def has_conflict(self) -> bool:
        return self.status != "none"

    @property
    def resolved(self) -> bool:
        return self.status == "preferred_side"

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "status": self.status,
            "preferred_side": self.preferred_side,
            "supporting": [item.to_dict() for item in self.supporting],
            "contradicting": [item.to_dict() for item in self.contradicting],
            "preferred_evidence_ids": list(self.preferred_evidence_ids),
            "reasons": list(self.reasons),
        }


def assess_claim_conflict(
    state: ResearchState,
    claim: ResearchClaim,
) -> ConflictAssessment:
    """Judge the support/contradict conflict for one claim; pure."""

    evidence_by_id = {item.evidence_id: item for item in state.evidence}
    supports: list[ResearchClaimEvidenceLink] = []
    contradictions: list[ResearchClaimEvidenceLink] = []
    for link in state.evidence_links:
        if link.claim_id != claim.id:
            continue
        if link.strength < STRONG_EVIDENCE_THRESHOLD:
            continue
        evidence = evidence_by_id.get(link.evidence_id)
        if not evidence_link_eligibility(
            claim=claim,
            link=link,
            evidence=evidence,
            reference_date=state.reference_date,
        ):
            continue
        if link.relation == "supports":
            supports.append(link)
        elif link.relation == "contradicts":
            contradictions.append(link)

    if not supports or not contradictions:
        return ConflictAssessment(
            claim_id=claim.id,
            status="none",
            preferred_side="",
            supporting=_standings(supports, evidence_by_id, claim, state),
            contradicting=_standings(contradictions, evidence_by_id, claim, state),
            reasons=(REASON_NO_CONFLICT,),
        )

    supporting = _standings(supports, evidence_by_id, claim, state)
    contradicting = _standings(contradictions, evidence_by_id, claim, state)

    support_best = min(item.authority_rank for item in supporting)
    contradict_best = min(item.authority_rank for item in contradicting)

    # The only v1 preference rule: a strict gap between the best authority rank
    # on each side. Counts are never consulted, and a side holding a primary
    # source can never be the weaker side (rank 0 is the strongest), so no
    # separate "loser has a primary" guard is needed -- it is implied.
    reasons: list[str] = [REASON_COUNT_NOT_USED]
    if support_best == contradict_best:
        return ConflictAssessment(
            claim_id=claim.id,
            status="unresolved_conflict",
            preferred_side="",
            supporting=supporting,
            contradicting=contradicting,
            reasons=tuple([*reasons, REASON_TIED_AUTHORITY]),
        )

    preferred: PreferredSide = "support" if support_best < contradict_best else "contradict"
    reasons.append(REASON_AUTHORITY_GAP)
    winner = supporting if preferred == "support" else contradicting
    return ConflictAssessment(
        claim_id=claim.id,
        status="preferred_side",
        preferred_side=preferred,
        supporting=supporting,
        contradicting=contradicting,
        preferred_evidence_ids=tuple(sorted(item.evidence_id for item in winner)),
        reasons=tuple(reasons),
    )


def assess_state_conflicts(
    state: ResearchState,
) -> tuple[ConflictAssessment, ...]:
    return tuple(assess_claim_conflict(state, claim) for claim in state.claims)


def safe_assess_state_conflicts(
    state: ResearchState,
) -> tuple[ConflictAssessment, ...]:
    """Keep shadow observability available if the conflict assessor fails."""

    try:
        return assess_state_conflicts(state)
    except Exception:  # noqa: BLE001 - shadow observation must never raise
        return ()


def _standings(
    links: list[ResearchClaimEvidenceLink],
    evidence_by_id: dict[str, ResearchEvidence],
    claim: ResearchClaim,
    state: ResearchState,
) -> tuple[EvidenceStanding, ...]:
    standings = []
    for link in links:
        evidence = evidence_by_id.get(link.evidence_id)
        standings.append(
            EvidenceStanding(
                evidence_id=link.evidence_id,
                relation=link.relation,
                source_role=link.source_role,
                authority_rank=authority_rank(link.source_role),
                fresh=evidence_link_meets_freshness(
                    claim=claim,
                    evidence=evidence,
                    reference_date=state.reference_date,
                ),
                direct=link.relation in DIRECT_RELATIONS,
                strength=link.strength,
            )
        )
    return tuple(sorted(standings, key=lambda item: (item.authority_rank, item.evidence_id)))
