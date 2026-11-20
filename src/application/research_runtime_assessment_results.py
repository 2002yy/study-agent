"""One wave's resume-aware candidate assessment result buffers.

Model calls, policy admission, budget attempts and checkpoints stay with their
existing owners. This module only restores prior rankings and projects a
successful assessment in the original merge/rank/audit/persist order.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.candidate_ranking import (
    CandidateSemanticAssessment,
    RankedCandidate,
    rank_candidate_pool,
)
from src.web.research.contracts import ResearchClaim
from src.web.research.gap_planner import GapSearchIntent
from src.web.research.selection_trace import SelectionTraceCollector


ACTIVE_RESEARCH_ASSESSMENTS_KEY = "claim_engine_assessments"
ACTIVE_RESEARCH_ASSESSMENT_INPUTS_KEY = "claim_engine_assessment_inputs"


def assessment_store(context: Mapping[str, Any]) -> dict[str, Any]:
    raw = context.get(ACTIVE_RESEARCH_ASSESSMENTS_KEY)
    return {str(key): value for key, value in raw.items()} if isinstance(raw, Mapping) else {}


def assessment_inputs_store(context: Mapping[str, Any]) -> dict[str, list[str]]:
    """Per-claim candidate-ID sets covered by persisted rankings."""
    raw = context.get(ACTIVE_RESEARCH_ASSESSMENT_INPUTS_KEY)
    if not isinstance(raw, Mapping):
        return {}
    inputs: dict[str, list[str]] = {}
    for key, value in raw.items():
        if isinstance(value, list):
            inputs[str(key)] = [str(item) for item in value]
    return inputs


def ranked_from_dict(raw: Mapping[str, Any]) -> RankedCandidate:
    """Recreate a saved ranking without changing its legacy wire shape."""
    candidate_raw = cast(Mapping[str, Any], raw["candidate"])
    assessment_raw = cast(Mapping[str, Any], raw["assessment"])
    candidate = CandidatePoolItem(
        id=str(candidate_raw["id"]),
        canonical_url=str(candidate_raw["canonical_url"]),
        url=str(candidate_raw["url"]),
        title=str(candidate_raw["title"]),
        snippet=str(candidate_raw.get("snippet") or ""),
        source=str(candidate_raw.get("source") or ""),
        published_at=str(candidate_raw.get("published_at") or ""),
        query_ids=tuple(str(item) for item in candidate_raw.get("query_ids", [])),
        intents=tuple(GapSearchIntent(str(item)) for item in candidate_raw.get("intents", [])),
        providers=tuple(str(item) for item in candidate_raw.get("providers", [])),
        first_seen_rank=int(candidate_raw.get("first_seen_rank") or 0),
    )
    assessment = CandidateSemanticAssessment(
        candidate_id=str(assessment_raw["candidate_id"]),
        relevance=cast(Any, str(assessment_raw["relevance"])),
        relevance_confidence=float(assessment_raw["relevance_confidence"]),
        source_role=str(assessment_raw["source_role"]),
        source_role_confidence=float(assessment_raw["source_role_confidence"]),
        cluster_id=str(assessment_raw["cluster_id"]),
        expected_gain_signals=tuple(str(item) for item in assessment_raw.get("expected_gain_signals", [])),
        freshness_score=float(assessment_raw.get("freshness_score") or 0.0),
        estimated_read_cost=float(assessment_raw.get("estimated_read_cost") or 1.0),
    )
    return RankedCandidate(
        candidate=candidate,
        assessment=assessment,
        rank=int(raw["rank"]),
        eligibility=cast(Any, str(raw["eligibility"])),
        reason_codes=tuple(str(item) for item in raw.get("reason_codes", [])),
        new_cluster=bool(raw.get("new_cluster")),
        expected_information_gain=int(raw.get("expected_information_gain") or 0),
    )


def record_assessment_result(
    *,
    claim: ResearchClaim,
    claim_candidates: tuple[CandidatePoolItem, ...],
    previous_ranked: tuple[RankedCandidate, ...],
    new_assessments: Mapping[str, CandidateSemanticAssessment],
    claim_rankings: dict[str, tuple[RankedCandidate, ...]],
    stored_assessments: dict[str, Any],
    assessed_inputs: dict[str, list[str]],
    context: dict[str, Any],
    trace: SelectionTraceCollector | None,
) -> tuple[dict[str, CandidateSemanticAssessment], tuple[RankedCandidate, ...]]:
    """Merge/rank/trace/write; keep both normal and late-tail order identical."""
    merged = {item.candidate.id: item.assessment for item in previous_ranked}
    merged.update(new_assessments)
    ranked_candidates = tuple(
        item for item in claim_candidates if item.id in merged
    )
    ranked = rank_candidate_pool(
        ranked_candidates,
        claim=claim,
        assessments=merged,
    )
    for rank_position, ranked_item in enumerate(ranked, start=1):
        if trace is not None:
            trace.note_scheduler_rank(
                ranked_item.candidate.canonical_url,
                rank=rank_position,
            )
    claim_rankings[claim.id] = ranked
    stored_assessments[claim.id] = [item.to_dict() for item in ranked]
    assessed_inputs[claim.id] = sorted(merged)
    context[ACTIVE_RESEARCH_ASSESSMENTS_KEY] = stored_assessments
    context[ACTIVE_RESEARCH_ASSESSMENT_INPUTS_KEY] = assessed_inputs
    return merged, ranked


@dataclass(slots=True)
class ActiveAssessmentResultContext:
    """Own the existing wave-local aliases, not a second durable snapshot.

    The stores are intentionally hydrated once at assessment-wave entry, as
    before. The write target is always resolved from the latest live context,
    since checkpoint and steering may replace that dictionary in between.
    """

    live: ActiveRuntimeLiveValues
    trace: SelectionTraceCollector
    stored_assessments: dict[str, Any]
    assessed_inputs: dict[str, list[str]]
    claim_rankings: dict[str, tuple[RankedCandidate, ...]] = field(default_factory=dict)

    @classmethod
    def for_live(
        cls, live: ActiveRuntimeLiveValues, trace: SelectionTraceCollector
    ) -> ActiveAssessmentResultContext:
        return cls(
            live=live,
            trace=trace,
            stored_assessments=assessment_store(live.current_context()),
            assessed_inputs=assessment_inputs_store(live.current_context()),
        )

    def restore_claim(self, claim_id: str) -> tuple[RankedCandidate, ...]:
        saved = self.stored_assessments.get(claim_id)
        restored = (
            tuple(ranked_from_dict(item) for item in saved)
            if isinstance(saved, list) and saved
            else ()
        )
        if restored:
            self.claim_rankings[claim_id] = restored
        return restored

    def record_completed(
        self,
        *,
        claim: ResearchClaim,
        claim_candidates: tuple[CandidatePoolItem, ...],
        previous_ranked: tuple[RankedCandidate, ...],
        new_assessments: Mapping[str, CandidateSemanticAssessment],
    ) -> dict[str, CandidateSemanticAssessment]:
        merged, _ranked = record_assessment_result(
            claim=claim,
            claim_candidates=claim_candidates,
            previous_ranked=previous_ranked,
            new_assessments=new_assessments,
            claim_rankings=self.claim_rankings,
            stored_assessments=self.stored_assessments,
            assessed_inputs=self.assessed_inputs,
            context=self.live.current_context(),
            trace=self.trace,
        )
        return merged
