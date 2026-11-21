"""Read-planner cross-claim cluster tests separated from durable runtime scenarios.

These cases are pure scheduler fixtures, with no database, network, or model.
"""

from __future__ import annotations

from dataclasses import fields, replace
from typing import Any
from types import SimpleNamespace

from src.application.active_research_runtime import (
    _bounded_assessment_candidates,
    _fair_read_plan,
)
from src.application.research_runtime_read_plan_context import FairReadPlanContext
from src.web.research.candidate_assessment import CandidateSemanticAssessment
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.candidate_ranking import RankedCandidate
from src.web.research.gap_planner import GapSearchIntent

from src.web.research.contracts import (
    ConflictGap,
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    ResearchQuestion,
    ResearchState,
    build_research_state,
)


def _claim(claim_id: str, priority: Any = "critical") -> ResearchClaim:
    return ResearchClaim(
        id=claim_id,
        question_id="q1",
        text="claim",
        kind="factual",
        priority=priority,
        state="pending",
        evidence_requirement=EvidenceRequirement(),
    )


def _ranked(
    candidate_id: str,
    cluster_id: str,
    rank: int,
    *,
    eligibility: str = "eligible",
    signals: tuple[str, ...] = ("new_primary",),
) -> RankedCandidate:
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
    assessment = CandidateSemanticAssessment(
        candidate_id=candidate_id,
        relevance="answer_relevant",
        relevance_confidence=0.9,
        source_role="primary",
        source_role_confidence=0.9,
        cluster_id=cluster_id,
        expected_gain_signals=signals,
        freshness_score=0.5,
        estimated_read_cost=1.0,
    )
    return RankedCandidate(
        candidate=candidate,
        assessment=assessment,
        rank=rank,
        eligibility=eligibility,
        reason_codes=(),
        new_cluster=False,
        expected_information_gain=1,
    )


def _two_claim_state() -> ResearchState:
    return build_research_state(
        mode="active",
        questions=(ResearchQuestion(id="q1", question_surface="question"),),
        claims=(_claim("claim_A"), _claim("claim_B")),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=20,
            max_reads=8,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=16000,
        ),
        reference_date="2026-08-28",
        known_evidence_ids=(),
    )


def test_read_plan_reserve_observation_is_one_shot_and_not_retained() -> None:
    state = _two_claim_state()
    rankings = {"claim_A": (_ranked("fresh", "cluster", 1),)}
    baseline = FairReadPlanContext(state=state, rankings=rankings).build(state.claims)
    metrics: dict[str, Any] = {"other": {"keep": True}}
    planner = FairReadPlanContext(
        state=state, rankings=rankings, diagnostics=metrics,
    )

    assert {item.name for item in fields(planner)}.isdisjoint({"diagnostics"})
    assert metrics == {
        "other": {"keep": True},
        "read_reserve": {
            "configured": 3,
            "reclaimed": 3,
            "reclaim_reason": "no_open_conflicts",
            "hard_cap": 8,
            "reads_used": 0,
        },
    }
    before = dict(metrics["read_reserve"])
    assert planner.build(state.claims) == baseline
    assert metrics["read_reserve"] == before


def test_read_plan_observation_does_not_change_scheduling() -> None:
    """The scheduler does not rely on diagnostics to decide what to read."""
    state = _two_claim_state()
    ranked = {"claim_A": (_ranked("a", "c1", 1),)}
    observed = FairReadPlanContext(
        state=state, rankings=ranked, diagnostics={},
    )
    unobserved = FairReadPlanContext(state=state, rankings=ranked)

    assert observed.build(state.claims) == unobserved.build(state.claims)
    assert observed.physical_ids == unobserved.physical_ids
    assert observed.claim_clusters == unobserved.claim_clusters


def test_conflict_reserve_observation_uses_existing_planner_decision() -> None:
    state = _two_claim_state()
    with_conflict = replace(
        state,
        conflict_gaps=(
            ConflictGap(
                id="conflict",
                claim_id="claim_A",
                supporting_evidence_ids=(),
                contradicting_evidence_ids=(),
                state="open",
            ),
        ),
    )
    metrics: dict[str, Any] = {}
    plan = FairReadPlanContext(
        state=with_conflict, rankings={}, diagnostics=metrics,
    )
    assert plan.reserve == 3
    assert plan.normal_limit == 5
    assert metrics["read_reserve"] == {
        "configured": 3,
        "reclaimed": 0,
        "reclaim_reason": "open_conflicts_present",
        "hard_cap": 8,
        "reads_used": 0,
    }


def test_each_read_plan_owns_fresh_bindings_without_mutating_prior_coverage() -> None:
    state = _two_claim_state()
    rankings = {
        "claim_A": (
            _ranked("old", "cluster_old", 1),
            _ranked("fresh", "cluster_fresh", 2),
        )
    }
    durable_coverage = {"claim_A": {"cluster_old"}}
    first = FairReadPlanContext(
        state=state,
        rankings=rankings,
        covered_cluster_ids_by_claim=durable_coverage,
    )
    first_plan = first.build(state.claims)
    second = FairReadPlanContext(
        state=state,
        rankings=rankings,
        covered_cluster_ids_by_claim=durable_coverage,
    )
    second_plan = second.build(state.claims)

    assert first_plan == second_plan
    assert [record["candidate_id"] for record in first_plan[0]] == ["fresh"]
    assert durable_coverage == {"claim_A": {"cluster_old"}}
    assert first.claim_clusters["claim_A"] == {"cluster_old", "cluster_fresh"}
    assert first.physical is not second.physical
    assert first.targets is not second.targets


def test_assessment_window_is_read_bounded_and_cluster_diverse() -> None:
    def candidate(candidate_id: str, rank: int) -> CandidatePoolItem:
        url = f"https://{candidate_id}.example/item"
        return CandidatePoolItem(
            id=candidate_id,
            canonical_url=url,
            url=url,
            title=candidate_id,
            snippet="snippet",
            source="source",
            published_at="2026-09-05",
            query_ids=("query",),
            intents=(GapSearchIntent.PRIMARY,),
            providers=("searxng",),
            first_seen_rank=rank,
        )

    candidates = tuple(candidate(chr(97 + index), index + 1) for index in range(6))
    assignments = {
        "a": SimpleNamespace(cluster_id="cluster-1"),
        "b": SimpleNamespace(cluster_id="cluster-1"),
        "c": SimpleNamespace(cluster_id="cluster-2"),
        "d": SimpleNamespace(cluster_id="cluster-2"),
        "e": SimpleNamespace(cluster_id="cluster-3"),
        "f": SimpleNamespace(cluster_id="cluster-4"),
    }

    selected = _bounded_assessment_candidates(
        candidates,
        assignments=assignments,
        max_reads=4,
    )

    assert [item.id for item in selected] == ["a", "c"]
    assert _bounded_assessment_candidates(
        candidates,
        assignments=assignments,
        max_reads=0,
    ) == ()
    advanced = _bounded_assessment_candidates(
        candidates,
        assignments=assignments,
        max_reads=4,
        excluded_candidate_ids=frozenset({"a", "c"}),
    )
    assert [item.id for item in advanced] == ["b", "d"]


def test_reusable_candidates_obey_scheduler_eligibility() -> None:
    """B5-H9: reusable candidates obey the same eligibility predicate as fresh.

    Claim B ranks the already-read shared candidate X as lead_only without any
    provenance-grade gain signal: it must not be bound to claim B even though
    its physical read exists, while a legitimate fresh Y is still selected and
    a lead_only candidate carrying a gain signal (Z) is not rejected.
    """
    state = _two_claim_state()
    rankings = {
        "claim_A": (_ranked("X", "cluster_X", 1),),
        "claim_B": (
            _ranked("X", "cluster_X", 1, eligibility="lead_only", signals=()),
            _ranked("Y", "cluster_Y", 2),
            _ranked("Z", "cluster_Z", 3, eligibility="lead_only", signals=("new_primary",)),
        ),
    }

    physical, targets = _fair_read_plan(state, rankings)

    b_pairs = {
        (item["candidate_id"], item["cluster_id"])
        for item in targets
        if item["claim_id"] == "claim_B"
    }
    # H9: X is lead_only without gain signals, so it must not be bound to
    # claim B even though it was already physically read for claim A.
    assert ("X", "cluster_X") not in b_pairs
    # The legitimate fresh candidate fills the wave; lead_only with a gain
    # signal (Z) stays schedulable in the next wave.
    assert ("Y", "cluster_Y") in b_pairs
    assert ("Z", "cluster_Z") in b_pairs
    assert "X" not in {item["candidate_id"] for item in physical if item["claim_id"] == "claim_B"}


def test_read_plan_cluster_diversity_spans_reusable_and_fresh() -> None:
    """B5-H8: fresh selections must skip clusters the claim already covers.

    Wave 1 binds the reusable shared candidate (cluster X) to claim_B; wave 2
    must skip the fresh same-cluster candidate Q without wasting the slot, and
    still take R (cluster Y).
    """
    state = _two_claim_state()
    rankings = {
        "claim_A": (_ranked("P", "cluster_X", 1),),
        "claim_B": (
            _ranked("P", "cluster_X", 1),
            _ranked("Q", "cluster_X", 2),
            _ranked("R", "cluster_Y", 3),
        ),
    }

    physical, targets = _fair_read_plan(state, rankings)

    b_pairs = {
        (item["candidate_id"], item["cluster_id"])
        for item in targets
        if item["claim_id"] == "claim_B"
    }
    assert ("P", "cluster_X") in b_pairs
    # H8: Q shares cluster X with the already-bound P, so it must be skipped
    # while R (cluster Y) still fills the slot.
    assert ("Q", "cluster_X") not in b_pairs
    assert ("R", "cluster_Y") in b_pairs
    assert "Q" not in {item["candidate_id"] for item in physical}

    # Later-wave planning removes the already-read P from fresh rankings, but
    # must still seed claim B with P's persisted cluster X. Q is therefore
    # skipped and the independent cluster Y candidate R is selected.
    later_physical, later_targets = _fair_read_plan(
        state,
        {
            "claim_B": (
                _ranked("Q", "cluster_X", 2),
                _ranked("R", "cluster_Y", 3),
            )
        },
        covered_cluster_ids_by_claim={"claim_B": {"cluster_X"}},
    )
    later_pairs = {
        (item["candidate_id"], item["cluster_id"])
        for item in later_targets
        if item["claim_id"] == "claim_B"
    }
    assert ("Q", "cluster_X") not in later_pairs
    assert ("R", "cluster_Y") in later_pairs
    assert {item["candidate_id"] for item in later_physical} == {"R"}


def test_read_plan_uses_persisted_conflicts_and_backfills_major_slots() -> None:
    """Persisted conflict truth releases reserve, and covered clusters do not
    consume a major claim's one-item wave before an independent backfill."""
    from src.domain.evidence import ClaimEvidenceLinkV1
    from src.web.research.contracts import (
        ConflictGap,
        EvidenceCluster,
        ResearchClaimEvidenceLink,
        ResearchEvidence,
    )

    question = ResearchQuestion(id="q1", question_surface="question")

    conflict_claim = _claim("claim_conflict", "critical")
    conflict_evidence = (
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
    conflict_links = (
        ResearchClaimEvidenceLink(
            link=ClaimEvidenceLinkV1(
                claim_id=conflict_claim.id,
                evidence_id="ev_support",
                support_type="supports",
                confidence=0.9,
            ),
            source_role="primary",
            source_cluster_id="evidence_cluster_support",
        ),
        ResearchClaimEvidenceLink(
            link=ClaimEvidenceLinkV1(
                claim_id=conflict_claim.id,
                evidence_id="ev_contradict",
                support_type="contradicts",
                confidence=0.9,
            ),
            source_role="independent_secondary",
            source_cluster_id="evidence_cluster_contradict",
        ),
    )
    conflict_state = build_research_state(
        mode="active",
        questions=(question,),
        claims=(conflict_claim,),
        evidence=conflict_evidence,
        evidence_links=conflict_links,
        source_clusters=(
            EvidenceCluster(
                id="evidence_cluster_support",
                evidence_ids=("ev_support",),
            ),
            EvidenceCluster(
                id="evidence_cluster_contradict",
                evidence_ids=("ev_contradict",),
            ),
        ),
        gaps=(),
        conflict_gaps=(
            ConflictGap(
                id="conflict_1",
                claim_id=conflict_claim.id,
                supporting_evidence_ids=("ev_support",),
                contradicting_evidence_ids=("ev_contradict",),
                state="open",
            ),
        ),
        budget=ResearchBudget(
            max_candidates=20,
            max_reads=6,
            reads_used=4,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=16000,
        ),
        reference_date="2026-08-30",
        known_evidence_ids=("ev_support", "ev_contradict"),
    )
    # Deliberately no new_contradiction: persisted conflict, not prediction,
    # must release the reservation.
    conflict_physical, _ = _fair_read_plan(
        conflict_state,
        {conflict_claim.id: (_ranked("conflict-source", "cluster_C", 1),)},
    )
    assert {item["candidate_id"] for item in conflict_physical} == {
        "conflict-source"
    }

    major_claim = _claim("claim_major", "major")
    major_state = build_research_state(
        mode="active",
        questions=(question,),
        claims=(major_claim,),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=20,
            max_reads=8,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=16000,
        ),
        reference_date="2026-08-30",
        known_evidence_ids=(),
    )
    major_physical, major_targets = _fair_read_plan(
        major_state,
        {
            major_claim.id: (
                _ranked("Q", "cluster_X", 1),
                _ranked("R", "cluster_Y", 2),
            )
        },
        covered_cluster_ids_by_claim={major_claim.id: {"cluster_X"}},
    )
    assert {item["candidate_id"] for item in major_physical} == {"R"}
    assert {item["candidate_id"] for item in major_targets} == {"R"}
