"""A persisted body is reusable without a physical read or source-independence credit."""

from dataclasses import replace

import pytest

from src.application.active_research_runtime import _fair_read_plan
from src.web.research.candidate_assessment import CandidateSemanticAssessment
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.candidate_ranking import RankedCandidate
from tests.test_deep_runtime_seams import _state


def ranked(name, cluster="official", eligibility="eligible"):
    candidate = CandidatePoolItem(
        id=name,
        canonical_url=f"https://example.org/{name}",
        url=f"https://example.org/{name}",
        title=name,
        snippet="",
        source="",
        published_at="",
        query_ids=("q1",),
        intents=(),
        providers=("deep_seed",),
        first_seen_rank=1,
    )
    assessment = CandidateSemanticAssessment(
        candidate_id=name,
        relevance="answer_relevant",
        relevance_confidence=0.9,
        source_role="primary",
        source_role_confidence=0.9,
        cluster_id=cluster,
        expected_gain_signals=("new_primary",),
        freshness_score=0.5,
        estimated_read_cost=1.0,
    )
    return RankedCandidate(
        candidate=candidate,
        assessment=assessment,
        rank=1,
        eligibility=eligibility,
        reason_codes=(),
        new_cluster=False,
        expected_information_gain=1,
    )


def test_unprocessed_seed_reuses_covered_cluster_while_fresh_same_cluster_is_rejected():
    state = _state()
    rankings = {
        "c1": (ranked("notes"), ranked("fresh"), ranked("independent", "other"))
    }
    old, _ = _fair_read_plan(
        state, rankings, covered_cluster_ids_by_claim={"c1": {"official"}}
    )
    assert {r["candidate_id"] for r in old} == {"independent"}
    reads, targets = _fair_read_plan(
        state,
        rankings,
        covered_cluster_ids_by_claim={"c1": {"official"}},
        seed_candidate_ids=frozenset({"notes"}),
    )
    assert {r["candidate_id"] for r in reads} == {"notes", "independent"}
    assert [t["cluster_id"] for t in targets if t["candidate_id"] == "notes"] == [
        "official"
    ]
    assert (
        state.evidence == ()
        and state.evidence_links == ()
        and state.budget.reads_used == 0
    )


def test_seed_does_not_consume_or_expand_last_physical_read_slot():
    state = _state()
    state = replace(state, budget=replace(state.budget, reads_used=11))
    reads, _ = _fair_read_plan(
        state,
        {"c1": (ranked("seed"), ranked("one", "other"), ranked("two", "third"))},
        seed_candidate_ids=frozenset({"seed"}),
    )
    assert {r["candidate_id"] for r in reads} == {"seed", "one"}


def test_seed_materialization_still_planned_when_physical_reads_exhausted():
    state = _state()
    state = replace(state, budget=replace(state.budget, reads_used=12))
    reads, _ = _fair_read_plan(
        state,
        {"c1": (ranked("seed"), ranked("fresh", "other"))},
        seed_candidate_ids=frozenset({"seed"}),
    )
    assert [r["candidate_id"] for r in reads] == ["seed"]


def test_same_candidate_claim_pair_is_not_duplicated_by_multiple_scheduling_passes():
    reads, targets = _fair_read_plan(
        _state(),
        {"c1": (ranked("seed"), ranked("seed"))},
        seed_candidate_ids=frozenset({"seed"}),
    )
    assert len(reads) == len(targets) == 1


@pytest.mark.parametrize("eligibility", ["rejected", "lead_only"])
def test_reuse_cannot_bypass_per_claim_scheduler_eligibility(eligibility):
    item = ranked("seed", eligibility=eligibility)
    item = replace(item, assessment=replace(item.assessment, expected_gain_signals=()))
    reads, targets = _fair_read_plan(
        _state(), {"c1": (item,)}, seed_candidate_ids=frozenset({"seed"})
    )
    assert reads == targets == []


def test_seed_identity_does_not_route_to_a_claim_without_its_own_ranking():
    reads, targets = _fair_read_plan(
        _state(), {}, seed_candidate_ids=frozenset({"seed"})
    )
    assert reads == targets == []
