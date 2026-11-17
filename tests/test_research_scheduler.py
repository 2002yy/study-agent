from __future__ import annotations

import pytest

from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.candidate_ranking import (
    CandidateSemanticAssessment,
    RankedCandidate,
)
from src.web.research.contracts import EvidenceRequirement, ResearchBudget, ResearchClaim
from src.web.research.gap_planner import GapSearchIntent
from src.web.research.scheduler import (
    ReadSchedulingCancelled,
    _restore_completed_read_targets,
    plan_read_wave,
)


def _claim(priority: str = "critical") -> ResearchClaim:
    return ResearchClaim(
        id="claim-1",
        question_id="question-1",
        text="Claim",
        kind="factual",
        priority=priority,  # type: ignore[arg-type]
        state="searching",
        evidence_requirement=EvidenceRequirement(
            source_roles=("primary", "independent_secondary"),
            min_independent_sources=2,
            requires_successful_read=True,
        ),
    )


def _budget(*, reads: int = 0, elapsed: float = 0.0) -> ResearchBudget:
    return ResearchBudget(
        max_candidates=20,
        max_reads=8,
        soft_timeout_seconds=45,
        hard_timeout_seconds=60,
        reads_used=reads,
        elapsed_seconds=elapsed,
    )


def _ranked(
    candidate_id: str,
    rank: int,
    *,
    cluster: str | None = None,
    eligibility: str = "eligible",
    gains: tuple[str, ...] = (),
) -> RankedCandidate:
    url = f"https://{candidate_id}.example/item"
    candidate = CandidatePoolItem(
        id=candidate_id,
        canonical_url=url,
        url=url,
        title=candidate_id,
        snippet="",
        source="",
        published_at="",
        query_ids=("query",),
        intents=(GapSearchIntent.DISCOVERY,),
        providers=("test",),
        first_seen_rank=rank,
    )
    assessment = CandidateSemanticAssessment(
        candidate_id=candidate_id,
        relevance="answer_relevant",
        relevance_confidence=0.8,
        source_role="primary",
        source_role_confidence=0.9,
        cluster_id=cluster or f"cluster-{candidate_id}",
        expected_gain_signals=gains,
    )
    return RankedCandidate(
        candidate=candidate,
        assessment=assessment,
        rank=rank,
        eligibility=eligibility,  # type: ignore[arg-type]
        reason_codes=(),
        new_cluster=True,
        expected_information_gain=len(gains),
    )


def test_critical_wave_selects_three_distinct_clusters_and_holds_reserve() -> None:
    ranked = (
        _ranked("a", 1, cluster="one"),
        _ranked("duplicate", 2, cluster="one"),
        _ranked("b", 3, cluster="two"),
        _ranked("c", 4, cluster="three"),
        _ranked("d", 5, cluster="four"),
    )
    plan = plan_read_wave(ranked, claim=_claim(), budget=_budget())
    assert plan.status == "planned"
    assert plan.selected_candidate_ids == ("a", "b", "c")
    assert plan.selected_cluster_ids == ("one", "two", "three")
    assert plan.conflict_reserve_held == 3


def test_lead_only_requires_explicit_high_value_lead_signal() -> None:
    ranked = (
        _ranked("plain-lead", 1, eligibility="lead_only"),
        _ranked(
            "provenance",
            2,
            eligibility="lead_only",
            gains=("new_provenance_lead",),
        ),
    )
    plan = plan_read_wave(ranked, claim=_claim(), budget=_budget())
    assert plan.selected_candidate_ids == ("provenance",)
    assert plan.deferred_candidate_ids == ("plain-lead",)


def test_open_conflict_releases_reserved_budget() -> None:
    ranked = tuple(_ranked(str(index), index) for index in range(1, 4))
    held = plan_read_wave(ranked, claim=_claim(), budget=_budget(reads=6))
    released = plan_read_wave(
        ranked,
        claim=_claim(),
        budget=_budget(reads=6),
        conflict_open=True,
    )
    assert held.status == "conflict_reserve_held"
    assert released.selected_candidate_ids == ("1", "2")
    assert released.conflict_reserve_held == 0


def test_exhausted_budget_is_not_mislabeled_as_conflict_reserve() -> None:
    plan = plan_read_wave(
        (_ranked("a", 1),),
        claim=_claim(),
        budget=_budget(reads=8),
    )
    assert plan.status == "budget_exhausted"
    assert plan.conflict_reserve_held == 0
    assert plan.deferred_candidate_ids == ("a",)


@pytest.mark.parametrize(
    ("priority", "elapsed", "status"),
    [
        ("context", 0.0, "context_deferred"),
        ("critical", 45.0, "soft_deadline"),
        ("critical", 60.0, "hard_deadline"),
    ],
)
def test_priority_and_deadline_stop_states(
    priority: str,
    elapsed: float,
    status: str,
) -> None:
    plan = plan_read_wave(
        (_ranked("a", 1),),
        claim=_claim(priority),
        budget=_budget(elapsed=elapsed),
    )
    assert plan.status == status
    assert plan.deferred_candidate_ids == ("a",)


def test_scheduler_checks_cancellation_before_and_after_and_checkpoints() -> None:
    checks = 0
    checkpoints = []

    def should_cancel() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 2

    with pytest.raises(ReadSchedulingCancelled):
        plan_read_wave(
            (_ranked("a", 1),),
            claim=_claim(),
            budget=_budget(),
            should_cancel=should_cancel,
            checkpoint=checkpoints.append,
        )
    assert checkpoints == []


def test_reused_physical_read_requires_each_claims_own_eligibility() -> None:
    existing = [{"candidate_id": "same", "claim_id": "a", "cluster_id": "old", "source_role": "primary"}]
    restored = _restore_completed_read_targets(
        existing,
        completed_read_ids={"same", "lead"},
        rankings={
            "a": (_ranked("same", 1, cluster="one"),),
            "b": (
                _ranked("same", 1, cluster="two"),
                _ranked("lead", 2, eligibility="lead_only"),
            ),
        },
    )
    assert restored == existing + [
        {"candidate_id": "same", "claim_id": "b", "cluster_id": "two", "source_role": "primary"}
    ]
    assert existing[0]["cluster_id"] == "old"
