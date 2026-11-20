"""Frozen wave gain, saturation and discovery bookkeeping without a live run."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import Mock, patch

import pytest

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_wave_progress import ActiveWaveProgressContext
from src.web.research.contracts import (
    EvidenceGap,
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    ResearchQuestion,
    ResearchState,
    build_research_state,
)
from src.web.research.evidence_gain import EvidenceGainResult
from src.web.research.evidence_gate import EvidenceGateResult
from src.web.research.runtime import ResearchRuntimeCursor, RuntimeCandidate
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


def _state() -> ResearchState:
    return build_research_state(
        mode="active",
        questions=(ResearchQuestion(id="q", question_surface="What happened?"),),
        claims=(
            ResearchClaim(
                id="claim", question_id="q", text="A claim", kind="factual",
                priority="critical", state="pending",
                evidence_requirement=EvidenceRequirement(),
            ),
        ),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(
            EvidenceGap(id="g1", claim_id="claim", gap_type="missing"),
            EvidenceGap(id="g2", claim_id="claim", gap_type="missing"),
        ),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=10, max_reads=3,
            soft_timeout_seconds=30, hard_timeout_seconds=50,
        ),
        known_evidence_ids=(),
    )


_GATE = EvidenceGateResult(
    status="partial", open_critical_claims=(), gap_ids=(), conflicts=(),
    reasons=(), eligible_evidence_ids=(), budget_exhausted=False,
)


def _context(
    live: ActiveRuntimeLiveValues, *, provenance: Any = None, max_waves: int = 8
) -> ActiveWaveProgressContext:
    return ActiveWaveProgressContext(
        live=live,
        gap_provenance=provenance or Mock(return_value={}),
        max_research_waves=max_waves,
    )


def _live() -> ActiveRuntimeLiveValues:
    return ActiveRuntimeLiveValues(
        state=_state(),
        cursor=ResearchRuntimeCursor(
            wave_index=2,
            active_gap_ids=("g2", "g1"),
            no_gain_batches_by_claim={"claim": 1},
            no_gain_batches_by_gap={"g1": 2, "g2": 1},
        ),
    )


def test_no_gain_increments_frozen_gap_counters_once_and_records_progress() -> None:
    live = _live()
    provenance = Mock(return_value={})
    progress = _context(live, provenance=provenance)
    before = progress.capture_before_lead()
    original_cursor = live.cursor

    progress.record_after_gate(baseline=live.state, gate=_GATE, before_lead=before)

    assert live.cursor.no_gain_batches_by_claim == {"claim": 2}
    assert live.cursor.no_gain_batches_by_gap == {"g1": 3, "g2": 2}
    assert len(live.cursor.gain_history) == 1
    assert live.cursor.gain_history[0]["substantive_gain"] is False
    provenance.assert_called_once_with(original_cursor, live.state, _GATE, ("g2", "g1"))
    assert live.context[ACTIVE_RESEARCH_METRICS_KEY]["wave_progress"] == [
        {
            "wave_index": 2,
            "evidence_progress": False,
            "discovery_progress": False,
            "discovered_candidates_added": 0,
            "no_gain_incremented": True,
        }
    ]


@pytest.mark.parametrize(
    ("kind", "expected_added"),
    [("candidate", 1), ("lead_payload", 0), ("followup", 0)],
)
def test_discovery_only_delays_saturation_without_faking_evidence_gain(
    kind: str, expected_added: int
) -> None:
    live = _live()
    progress = _context(live)
    before = progress.capture_before_lead()
    if kind == "candidate":
        live.cursor = replace(
            live.cursor,
            candidates=(RuntimeCandidate(
                id="new", url="https://example.com", title="new",
                discovery_method="lead_url",
            ),),
        )
    elif kind == "lead_payload":
        live.cursor = replace(live.cursor, lead_discoveries=({"domains": ["example.com"]},))
    else:
        live.cursor = replace(
            live.cursor, evidence_lead_followups=({"hint_domain": "example.com"},)
        )

    progress.record_after_gate(baseline=live.state, gate=_GATE, before_lead=before)

    assert live.cursor.gain_history[0]["substantive_gain"] is False
    assert live.cursor.no_gain_batches_by_claim == {"claim": 1}
    assert live.cursor.no_gain_batches_by_gap == {"g1": 2, "g2": 1}
    assert live.context[ACTIVE_RESEARCH_METRICS_KEY]["wave_progress"] == [
        {
            "wave_index": 2,
            "evidence_progress": False,
            "discovery_progress": True,
            "discovered_candidates_added": expected_added,
            "no_gain_incremented": False,
        }
    ]


def test_true_evidence_gain_preserves_no_gain_history_until_frozen_settlement() -> None:
    live = _live()
    progress = _context(live)
    before = progress.capture_before_lead()
    gain = EvidenceGainResult(
        substantive_gain=True,
        gain_reasons=("new_eligible_evidence",),
        affected_claim_ids=("claim",),
        affected_gap_ids=("g1",),
    )
    with patch(
        "src.application.research_runtime_wave_progress.evaluate_evidence_gain",
        return_value=gain,
    ):
        progress.record_after_gate(baseline=live.state, gate=_GATE, before_lead=before)

    assert live.cursor.no_gain_batches_by_claim == {"claim": 1}
    assert live.cursor.no_gain_batches_by_gap == {"g1": 2, "g2": 1}
    assert live.cursor.gain_history == (gain.to_dict(),)
    assert live.context[ACTIVE_RESEARCH_METRICS_KEY]["wave_progress"][0][
        "evidence_progress"
    ] is True


def test_after_rebind_reads_current_cursor_and_context_and_caps_metrics() -> None:
    live = _live()
    before = _context(live).capture_before_lead()
    old_cursor, old_context = live.cursor, live.context
    provenance = Mock(return_value={})
    progress = _context(live, provenance=provenance, max_waves=2)
    live.cursor = replace(
        old_cursor, wave_index=5, active_gap_ids=("g1",),
        no_gain_batches_by_claim={}, no_gain_batches_by_gap={},
    )
    live.state = replace(
        live.state, budget=replace(live.state.budget, reads_used=1)
    )
    live.context = {ACTIVE_RESEARCH_METRICS_KEY: {
        "wave_progress": [{"wave_index": 3}, {"wave_index": 4}],
    }}
    rebound_cursor = live.cursor
    progress.record_after_gate(baseline=live.state, gate=_GATE, before_lead=before)

    provenance.assert_called_once_with(rebound_cursor, live.state, _GATE, ("g1",))
    assert old_cursor.gain_history == ()
    assert old_context == {}
    assert live.cursor.no_gain_batches_by_gap == {"g1": 1}
    assert live.cursor.no_gain_batches_by_claim == {"claim": 1}
    assert [item["wave_index"] for item in live.context[ACTIVE_RESEARCH_METRICS_KEY][
        "wave_progress"
    ]] == [4, 5]


def test_provenance_failure_does_not_mutate_cursor_or_diagnostics() -> None:
    live = _live()
    original_cursor = live.cursor
    progress = _context(live, provenance=Mock(side_effect=ValueError("bad provenance")))
    before = progress.capture_before_lead()

    with pytest.raises(ValueError, match="bad provenance"):
        progress.record_after_gate(baseline=live.state, gate=_GATE, before_lead=before)

    assert live.cursor is original_cursor
    assert live.context == {}
