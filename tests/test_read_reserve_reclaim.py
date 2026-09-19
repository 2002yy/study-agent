"""§41 Read Reserve Reclaim: unused conflict reserve within the hard cap."""

from __future__ import annotations

from typing import Any

from src.application.active_research_runtime import _fair_read_plan
from src.domain.evidence import ClaimEvidenceLinkV1
from src.web.research.candidate_assessment import CandidateSemanticAssessment
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.candidate_ranking import RankedCandidate
from src.web.research.contracts import (
    ConflictGap,
    EvidenceCluster,
    EvidenceRequirement,
    ResearchClaim,
    ResearchClaimEvidenceLink,
    ResearchEvidence,
    ResearchQuestion,
)
from src.web.research.state import build_research_state

QUESTION = ResearchQuestion(id="q1", question_surface="question")


def _claim(claim_id: str, priority: str = "critical") -> ResearchClaim:
    return ResearchClaim(
        id=claim_id,
        question_id="q1",
        text="claim",
        kind="factual",
        priority=priority,  # type: ignore[arg-type]
        state="pending",
        evidence_requirement=EvidenceRequirement(),
    )


def _ranked(candidate_id: str, cluster_id: str, rank: int) -> RankedCandidate:
    candidate = CandidatePoolItem(
        id=candidate_id,
        canonical_url=f"https://x.example/{candidate_id}",
        url=f"https://x.example/{candidate_id}",
        title=candidate_id,
        snippet="",
        source="",
        published_at="",
        query_ids=("q1",),
        intents=(),
        providers=("searxng",),
        first_seen_rank=rank,
    )
    return RankedCandidate(
        candidate=candidate,
        assessment=CandidateSemanticAssessment(
            candidate_id=candidate_id,
            relevance="answer_relevant",
            relevance_confidence=0.9,
            source_role="primary",
            source_role_confidence=0.9,
            cluster_id=cluster_id,
            expected_gain_signals=("new_primary",),
            freshness_score=0.5,
            estimated_read_cost=1.0,
        ),
        rank=rank,
        eligibility="eligible",
        reason_codes=(),
        new_cluster=False,
        expected_information_gain=1,
    )


def _budget(reads_used: int) -> Any:
    from src.web.research.contracts import ResearchBudget

    return ResearchBudget(
        max_candidates=20,
        max_reads=8,
        reads_used=reads_used,
        soft_timeout_seconds=45,
        hard_timeout_seconds=60,
        max_total_chars=16000,
    )


def _conflict_gap(claim_id: str) -> ConflictGap:
    return ConflictGap(
        id="conflict_1",
        claim_id=claim_id,
        supporting_evidence_ids=("ev_support",),
        contradicting_evidence_ids=("ev_contradict",),
        state="open",
    )


def _conflict_evidence() -> tuple[
    tuple[ResearchEvidence, ...], tuple[ResearchClaimEvidenceLink, ...], tuple[EvidenceCluster, ...]
]:
    evidence = (
        ResearchEvidence(
            evidence_id="ev_support",
            locator="support",
            anchored_spans=("support",),
            lifecycle_status="read",
            extraction_status="eligible",
        ),
        ResearchEvidence(
            evidence_id="ev_contradict",
            locator="contradict",
            anchored_spans=("contradict",),
            lifecycle_status="read",
            extraction_status="eligible",
        ),
    )
    links = (
        ResearchClaimEvidenceLink(
            link=ClaimEvidenceLinkV1(
                claim_id="claim_conflict",
                evidence_id="ev_support",
                support_type="supports",
                confidence=0.9,
            ),
            source_role="primary",
            source_cluster_id="evidence_cluster_support",
        ),
        ResearchClaimEvidenceLink(
            link=ClaimEvidenceLinkV1(
                claim_id="claim_conflict",
                evidence_id="ev_contradict",
                support_type="contradicts",
                confidence=0.9,
            ),
            source_role="independent_secondary",
            source_cluster_id="evidence_cluster_contradict",
        ),
    )
    clusters = (
        EvidenceCluster(id="evidence_cluster_support", evidence_ids=("ev_support",)),
        EvidenceCluster(
            id="evidence_cluster_contradict", evidence_ids=("ev_contradict",)
        ),
    )
    return evidence, links, clusters


def test_no_conflict_reclaims_the_unused_reserve() -> None:
    state = build_research_state(
        mode="active",
        questions=(QUESTION,),
        claims=(_claim("claim_A"),),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=_budget(reads_used=5),
        reference_date="2026-09-19",
        known_evidence_ids=(),
    )
    diagnostics: dict[str, Any] = {}
    physical, _ = _fair_read_plan(
        state,
        {"claim_A": (_ranked("P", "cluster_X", 1), _ranked("Q", "cluster_Y", 2))},
        diagnostics=diagnostics,
    )
    assert diagnostics["read_reserve"] == {
        "configured": 3,
        "reclaimed": 3,
        "reclaim_reason": "no_open_conflicts",
        "hard_cap": 8,
        "reads_used": 5,
    }
    # Ordinary scheduling may now use the reclaimed capacity.
    assert len(physical) >= 1
    # ...but never beyond the existing hard cap.
    assert len(physical) <= 8 - 5


def test_open_conflict_keeps_the_reserve_reserved() -> None:
    evidence, links, clusters = _conflict_evidence()
    state = build_research_state(
        mode="active",
        questions=(QUESTION,),
        claims=(_claim("claim_A"), _claim("claim_conflict")),
        evidence=evidence,
        evidence_links=links,
        source_clusters=clusters,
        gaps=(),
        conflict_gaps=(_conflict_gap("claim_conflict"),),
        budget=_budget(reads_used=5),
        reference_date="2026-09-19",
        known_evidence_ids=("ev_support", "ev_contradict"),
    )
    diagnostics: dict[str, Any] = {}
    physical, _ = _fair_read_plan(
        state,
        {
            "claim_A": (_ranked("P", "cluster_X", 1),),
            "claim_conflict": (_ranked("C", "cluster_C", 1),),
        },
        diagnostics=diagnostics,
    )
    assert diagnostics["read_reserve"]["reclaimed"] == 0
    assert diagnostics["read_reserve"]["reclaim_reason"] == "open_conflicts_present"
    planned = {item["candidate_id"] for item in physical}
    assert "P" not in planned  # the ordinary claim keeps waiting for the reserve
    assert "C" in planned  # the conflict claim may consume the reserved capacity


def test_hard_read_cap_is_never_exceeded_in_either_mode() -> None:
    rankings = {
        "claim_A": tuple(
            _ranked(f"S{index}", f"cluster_{index}", index + 1) for index in range(10)
        )
    }
    no_conflict = build_research_state(
        mode="active",
        questions=(QUESTION,),
        claims=(_claim("claim_A"),),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=_budget(reads_used=3),
        reference_date="2026-09-19",
        known_evidence_ids=(),
    )
    physical, _ = _fair_read_plan(no_conflict, rankings)
    assert len(physical) <= 8 - 3

    evidence, links, clusters = _conflict_evidence()
    with_conflict = build_research_state(
        mode="active",
        questions=(QUESTION,),
        claims=(_claim("claim_A"), _claim("claim_conflict")),
        evidence=evidence,
        evidence_links=links,
        source_clusters=clusters,
        gaps=(),
        conflict_gaps=(_conflict_gap("claim_conflict"),),
        budget=_budget(reads_used=3),
        reference_date="2026-09-19",
        known_evidence_ids=("ev_support", "ev_contradict"),
    )
    conflict_physical, _ = _fair_read_plan(
        with_conflict,
        {**rankings, "claim_conflict": (_ranked("C", "cluster_C", 1),)},
    )
    assert len(conflict_physical) <= 8 - 3
