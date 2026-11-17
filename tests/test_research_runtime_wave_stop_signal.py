"""Characterization of the completed-wave signal fed to the frozen stop gate."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.application.research_runtime_wave_stop_signal import (
    completed_wave_stop_signal,
)
from src.application.research_stop_gate import ResearchStopGate
from src.web.research.contracts import (
    ConflictGap,
    EvidenceGap,
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    ResearchEvidence,
    ResearchState,
)
from src.web.research.evidence_gate import EvidenceGateResult
from src.web.research.runtime import ResearchRuntimeCursor


def _state(*, priority: str = "major") -> ResearchState:
    return ResearchState(
        mode="active",
        questions=(),
        claims=(
            ResearchClaim(
                id="claim-1",
                question_id="question-1",
                text="A claim",
                kind="factual",
                priority=priority,
                state="unresolved",
                evidence_requirement=EvidenceRequirement(),
            ),
        ),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(EvidenceGap(id="gap-1", claim_id="claim-1", gap_type="missing"),),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=10,
            max_reads=5,
            soft_timeout_seconds=30,
            hard_timeout_seconds=60,
        ),
    )


def _signal(
    state: ResearchState,
    *,
    count: int = 0,
    actionable: bool = True,
    context: dict | None = None,
    gate_pass: bool = False,
    hard_exhausted: bool = False,
    wave_exhausted: bool = False,
):
    return completed_wave_stop_signal(
        state=state,
        cursor=ResearchRuntimeCursor(
            no_gain_batches_by_claim={"claim-1": count},
        ),
        context=context or {},
        gate=EvidenceGateResult(
            status="pass" if gate_pass else "partial",
            open_critical_claims=(),
            gap_ids=(),
            conflicts=(),
            reasons=(),
            eligible_evidence_ids=(),
            budget_exhausted=False,
        ),
        actionable_gaps=state.gaps if actionable else (),
        hard_exhausted=hard_exhausted,
        wave_exhausted=wave_exhausted,
    )


@pytest.mark.parametrize(
    ("priority", "count", "saturated"),
    [
        ("major", 1, False),
        ("major", 2, True),
        ("critical", 2, False),
        ("critical", 3, True),
    ],
)
def test_saturation_preserves_normal_and_critical_batch_thresholds(
    priority: str, count: int, saturated: bool,
) -> None:
    signal = _signal(_state(priority=priority), count=count)
    assert signal.has_actionable_gaps
    assert signal.all_actionable_saturated is saturated
    assert ResearchStopGate.evaluate(signal).reason == (
        "evidence_saturated" if saturated else ""
    )


def test_conflicting_claim_has_extra_no_gain_batch() -> None:
    state = _state()
    state = replace(
        state,
        conflict_gaps=(
            ConflictGap(
                id="conflict-1",
                claim_id="claim-1",
                supporting_evidence_ids=(),
                contradicting_evidence_ids=(),
            ),
        ),
    )
    assert not _signal(state, count=2).all_actionable_saturated
    assert _signal(state, count=3).all_actionable_saturated


def test_context_only_gaps_do_not_extend_wave_settlement() -> None:
    state = _state()
    signal = _signal(state, actionable=False, count=0)
    assert not signal.has_actionable_gaps
    assert not signal.all_actionable_saturated
    assert ResearchStopGate.evaluate(signal).reason == "evidence_gap_open"


def test_late_steering_from_recovered_context_blocks_stale_gate_pass() -> None:
    state = _state()
    late_context = {
        "claim_engine_steering": [
            {
                "id": "steer-1",
                "status": "late",
                "late_reason": "hard_budget_exhausted",
            }
        ]
    }
    signal = _signal(
        state,
        actionable=False,
        context=late_context,
        gate_pass=True,
        hard_exhausted=True,
    )
    assert signal.unapplied_steering_blocks_completion
    assert signal.has_actionable_gaps
    assert ResearchStopGate.evaluate(signal).reason == "evidence_budget_exhausted"
    assert ResearchStopGate.evaluate(_signal(state, actionable=False, gate_pass=True)).reason == (
        "evidence_gate_pass"
    )


def test_evidence_presence_and_wave_limit_are_projected_without_side_effects() -> None:
    state = replace(_state(), evidence=(ResearchEvidence(evidence_id="ev-1"),))
    signal = _signal(state, wave_exhausted=True)
    assert signal.has_evidence
    assert signal.wave_limit_reached
    assert not signal.hard_budget_exhausted
    assert ResearchStopGate.evaluate(signal).reason == "wave_limit_exhausted"
