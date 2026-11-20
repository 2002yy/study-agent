"""Assessment result ownership without repeating model and gateway setup."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.application.research_runtime_assessment_results import (
    ACTIVE_RESEARCH_ASSESSMENTS_KEY,
    ACTIVE_RESEARCH_ASSESSMENT_INPUTS_KEY,
    ActiveAssessmentResultContext,
    assessment_inputs_store,
    assessment_store,
    record_assessment_result,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.candidate_ranking import (
    CandidateSemanticAssessment,
    rank_candidate_pool,
)
from src.web.research.contracts import (
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    build_research_state,
)
from src.web.research.gap_planner import GapSearchIntent
from src.web.research.selection_trace import SelectionTraceCollector


def _claim() -> ResearchClaim:
    return ResearchClaim(
        id="claim", question_id="q", text="Which source is authoritative?",
        kind="factual", priority="critical", state="searching",
        evidence_requirement=EvidenceRequirement(),
    )


def _candidate(candidate_id: str) -> CandidatePoolItem:
    url = f"https://{candidate_id}.example/page"
    return CandidatePoolItem(
        id=candidate_id, canonical_url=url, url=url, title=candidate_id,
        snippet="", source="search", published_at="", query_ids=("q1",),
        intents=(GapSearchIntent.DISCOVERY,), providers=("test",),
        first_seen_rank=1,
    )


def _assessment(candidate_id: str, *, role: str = "primary") -> CandidateSemanticAssessment:
    return CandidateSemanticAssessment(
        candidate_id=candidate_id, relevance="answer_relevant",
        relevance_confidence=0.9, source_role=role, source_role_confidence=0.9,
        cluster_id=f"cluster-{candidate_id}",
    )


def _live(context: dict | None = None) -> ActiveRuntimeLiveValues:
    state = build_research_state(
        mode="active", questions=(), claims=(), evidence=(), evidence_links=(),
        source_clusters=(), gaps=(), conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=5, max_reads=2,
            soft_timeout_seconds=10, hard_timeout_seconds=20,
        ),
        known_evidence_ids=(),
    )
    return ActiveRuntimeLiveValues(state=state, context=context if context is not None else {})


def _prior_ranked():
    candidate = _candidate("old")
    return rank_candidate_pool(
        (candidate,), claim=_claim(),
        assessments={candidate.id: _assessment(candidate.id)},
    )


def test_restore_saved_ranked_without_touching_durable_context() -> None:
    old = _prior_ranked()
    durable = {ACTIVE_RESEARCH_ASSESSMENTS_KEY: {"claim": [row.to_dict() for row in old]}}
    live = _live(durable)
    owner = ActiveAssessmentResultContext.for_live(live, SelectionTraceCollector())

    assert owner.restore_claim("claim") == old
    assert owner.claim_rankings == {"claim": old}
    assert owner.restore_claim("other") == ()
    assert live.context == durable
    assert owner.stored_assessments is not live.context[ACTIVE_RESEARCH_ASSESSMENTS_KEY]


def test_merge_new_assessment_uses_prior_binding_and_exact_persistence_order() -> None:
    old = _prior_ranked()
    live = _live({
        ACTIVE_RESEARCH_ASSESSMENTS_KEY: {"claim": [row.to_dict() for row in old]},
        ACTIVE_RESEARCH_ASSESSMENT_INPUTS_KEY: {"claim": ["old"]},
    })
    trace = SelectionTraceCollector()
    owner = ActiveAssessmentResultContext.for_live(live, trace)
    saved = owner.restore_claim("claim")
    merged = owner.record_completed(
        claim=_claim(), claim_candidates=(_candidate("old"), _candidate("new")),
        previous_ranked=saved, new_assessments={"new": _assessment("new")},
    )

    assert sorted(merged) == ["new", "old"]
    assert sorted(owner.assessed_inputs["claim"]) == ["new", "old"]
    assert live.context[ACTIVE_RESEARCH_ASSESSMENTS_KEY] is owner.stored_assessments
    assert live.context[ACTIVE_RESEARCH_ASSESSMENT_INPUTS_KEY] is owner.assessed_inputs
    assert owner.claim_rankings["claim"] == tuple(
        owner.restore_claim("claim")
    )
    assert len(owner.claim_rankings["claim"]) == 2
    assert {entry["canonical_url"] for entry in trace.to_payload()["entries"]} == {
        _candidate("old").canonical_url, _candidate("new").canonical_url
    }


def test_rebound_context_is_write_target_without_caching_old_dict() -> None:
    original: dict = {}
    live = _live(original)
    owner = ActiveAssessmentResultContext.for_live(live, SelectionTraceCollector())
    live.context = {"steering": "new durable context"}
    owner.record_completed(
        claim=_claim(), claim_candidates=(_candidate("new"),),
        previous_ranked=(), new_assessments={"new": _assessment("new")},
    )

    assert original == {}
    assert live.context["steering"] == "new durable context"
    assert list(live.context[ACTIVE_RESEARCH_ASSESSMENTS_KEY]) == ["claim"]


def test_malformed_cache_projection_still_ignores_non_lists() -> None:
    context = {
        ACTIVE_RESEARCH_ASSESSMENTS_KEY: {3: [], "claim": "not-a-list"},
        ACTIVE_RESEARCH_ASSESSMENT_INPUTS_KEY: {"claim": ("not", "a-list"), "ok": [1, "x"]},
    }
    assert assessment_store(context) == {"3": [], "claim": "not-a-list"}
    assert assessment_inputs_store(context) == {"ok": ["1", "x"]}
    owner = ActiveAssessmentResultContext.for_live(_live(context), SelectionTraceCollector())
    assert owner.restore_claim("claim") == ()


def test_rank_failure_does_not_persist_partial_candidate_results() -> None:
    live = _live()
    owner = ActiveAssessmentResultContext.for_live(live, SelectionTraceCollector())
    with patch(
        "src.application.research_runtime_assessment_results.rank_candidate_pool",
        side_effect=ValueError("bad assessment"),
    ):
        with pytest.raises(ValueError, match="bad assessment"):
            owner.record_completed(
                claim=_claim(), claim_candidates=(_candidate("new"),),
                previous_ranked=(), new_assessments={"new": _assessment("new")},
            )
    assert live.context == {}
    assert owner.claim_rankings == {}
    assert owner.stored_assessments == {}
    assert owner.assessed_inputs == {}


def test_late_tail_path_uses_same_projection_without_trace() -> None:
    context: dict = {}
    rankings: dict = {}
    saved: dict = {}
    inputs: dict = {}
    merged, ranked = record_assessment_result(
        claim=_claim(), claim_candidates=(_candidate("late"),),
        previous_ranked=(), new_assessments={"late": _assessment("late")},
        claim_rankings=rankings, stored_assessments=saved,
        assessed_inputs=inputs, context=context, trace=None,
    )
    assert sorted(merged) == ["late"]
    assert rankings["claim"] == ranked
    assert saved["claim"] == [item.to_dict() for item in ranked]
    assert inputs["claim"] == ["late"]
    assert context[ACTIVE_RESEARCH_ASSESSMENTS_KEY] is saved
    assert context[ACTIVE_RESEARCH_ASSESSMENT_INPUTS_KEY] is inputs
