"""Wave-entry baseline contracts, without recreating the full executor."""

from __future__ import annotations

from dataclasses import replace
from typing import cast
from unittest import TestCase
from unittest.mock import Mock

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_wave_baseline import (
    ACTIVE_RESEARCH_WAVE_BASELINE_KEY,
    ActiveWaveBaselineContext,
)
from src.web.research.contracts import (
    EvidenceGap,
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    ResearchQuestion,
    ResearchState,
    build_research_state,
)
from src.web.research.runtime import ResearchRuntimeCursor


def _state() -> ResearchState:
    return build_research_state(
        mode="active",
        questions=(ResearchQuestion(id="q", question_surface="Which sources agree?"),),
        claims=(
            ResearchClaim(
                id="c", question_id="q", text="Claim", kind="factual",
                priority="critical", state="pending",
                evidence_requirement=EvidenceRequirement(),
            ),
        ),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(
            EvidenceGap(id="gap_a", claim_id="c", gap_type="missing"),
            EvidenceGap(id="gap_b", claim_id="c", gap_type="missing"),
        ),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=12, max_reads=4,
            soft_timeout_seconds=30, hard_timeout_seconds=50,
            max_total_chars=6000,
        ),
        known_evidence_ids=(),
    )


def _context(live: ActiveRuntimeLiveValues) -> ActiveWaveBaselineContext:
    # Ordering remains supplied by the executor's existing _ordered_gaps.
    return ActiveWaveBaselineContext(
        live=live, actionable_gaps=lambda state: tuple(reversed(state.gaps))
    )


class WaveBaselineContracts(TestCase):
    def test_new_wave_prepares_cursor_before_baseline_and_restores_original(self) -> None:
        state = _state()
        live = ActiveRuntimeLiveValues(state=state, cursor=ResearchRuntimeCursor(wave_index=1))
        context = _context(live)

        self.assertTrue(context.begin_if_needed("research_wave:run:1"))
        self.assertEqual(live.cursor.wave_id, "research_wave:run:1")
        self.assertEqual(live.cursor.active_gap_ids, ("gap_b", "gap_a"))
        self.assertEqual(live.context[ACTIVE_RESEARCH_WAVE_BASELINE_KEY], state.to_dict())
        self.assertEqual(context.restore(), state)

    def test_same_wave_resume_never_replaces_pre_read_baseline(self) -> None:
        initial = _state()
        live = ActiveRuntimeLiveValues(state=initial)
        context = _context(live)
        self.assertTrue(context.begin_if_needed("research_wave:run:1"))
        stored_baseline = live.context[ACTIVE_RESEARCH_WAVE_BASELINE_KEY]

        live.state = replace(initial, budget=replace(initial.budget, reads_used=3))
        self.assertFalse(context.begin_if_needed("research_wave:run:1"))
        self.assertIs(live.context[ACTIVE_RESEARCH_WAVE_BASELINE_KEY], stored_baseline)
        self.assertEqual(context.restore(), initial)

    def test_restore_reads_rebound_context_after_checkpoint(self) -> None:
        initial = _state()
        live = ActiveRuntimeLiveValues(state=initial)
        context = _context(live)
        self.assertTrue(context.begin_if_needed("research_wave:run:1"))
        old_context = live.context
        committed = replace(initial, budget=replace(initial.budget, reads_used=2))

        # A checkpoint can atomically hand back a new context/state owner.
        live.context = {ACTIVE_RESEARCH_WAVE_BASELINE_KEY: committed.to_dict()}
        live.state = committed
        self.assertEqual(context.restore(), committed)
        self.assertEqual(old_context[ACTIVE_RESEARCH_WAVE_BASELINE_KEY], initial.to_dict())

    def test_missing_and_malformed_baseline_fail_closed(self) -> None:
        live = ActiveRuntimeLiveValues(state=_state())
        context = _context(live)
        with self.assertRaisesRegex(ValueError, "active wave baseline is unavailable"):
            context.restore()
        live.context[ACTIVE_RESEARCH_WAVE_BASELINE_KEY] = []
        with self.assertRaisesRegex(ValueError, "active wave baseline is unavailable"):
            context.restore()
        live.context[ACTIVE_RESEARCH_WAVE_BASELINE_KEY] = {"mode": "active"}
        with self.assertRaises(ValueError):
            context.restore()

    def test_serialization_failure_keeps_cursor_update_without_baseline(self) -> None:
        bad_state = Mock()
        bad_state.to_dict.side_effect = ValueError("serialization failure")
        live = ActiveRuntimeLiveValues(state=cast(ResearchState, bad_state))
        context = ActiveWaveBaselineContext(live=live, actionable_gaps=lambda _: ())

        with self.assertRaisesRegex(ValueError, "serialization failure"):
            context.begin_if_needed("research_wave:run:1")
        self.assertEqual(live.cursor.wave_id, "research_wave:run:1")
        self.assertNotIn(ACTIVE_RESEARCH_WAVE_BASELINE_KEY, live.context)
