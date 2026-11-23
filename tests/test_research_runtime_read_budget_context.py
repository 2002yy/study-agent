"""Read budget projection follows live state and shared wave charges."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_read_budget_context import ReadWaveBudgetContext
from src.application.research_runtime_read_quota_context import ReadWaveQuotaContext
from src.application.research_runtime_read_result_context import ReadWaveResultContext
from src.application.research_runtime_result_buffers import ActiveResearchResultBuffers
from src.application.research_runtime_source_evidence_context import ReadSourceEvidenceContext
from src.web.research.chain_executor import ChainStepResult
from src.web.research.contracts import (
    ResearchBudget,
    ResearchState,
    build_research_state,
)
from src.web.research.runtime import ResearchRuntimeCursor, RuntimeCandidate
from tests.research_read_candidate_factory import read_candidate


def _state(*, max_candidates: int, reads_used: int = 0) -> ResearchState:
    return build_research_state(
        mode="active",
        questions=(),
        claims=(),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=max_candidates,
            max_reads=max_candidates,
            reads_used=reads_used,
            max_total_chars=100,
            soft_timeout_seconds=10,
            hard_timeout_seconds=20,
        ),
        known_evidence_ids=(),
    )


def test_projection_uses_rebound_state_cursor_and_shared_read_charges() -> None:
    original_state = _state(max_candidates=5, reads_used=1)
    live = ActiveRuntimeLiveValues(state=original_state)
    quota = ReadWaveQuotaContext(successful_reads=1, used_chars=0)
    elapsed_samples: list[float] = []
    current_time = [1.5]

    def elapsed() -> float:
        elapsed_samples.append(current_time[0])
        return current_time[0]

    budget = ReadWaveBudgetContext(live=live, quota=quota, elapsed=elapsed)
    seed_state = budget.project()
    assert seed_state.budget.reads_used == 1
    assert seed_state.budget.elapsed_seconds == 1.5
    assert live.state is original_state  # projection is not a hidden writer

    # Checkpoint/steering can replace both live inputs between two read paths.
    recovered = _state(max_candidates=3, reads_used=1)
    live.state = recovered
    live.cursor = ResearchRuntimeCursor(
        candidates=(
            RuntimeCandidate(id="a", url="https://a.test", title="A"),
            RuntimeCandidate(id="b", url="https://b.test", title="B"),
            RuntimeCandidate(id="c", url="https://c.test", title="C"),
            RuntimeCandidate(id="d", url="https://d.test", title="D"),
        )
    )
    quota.charge_materialization("seed")  # characters, but no read slot
    quota.charge_read("evidence")
    quota.charge_read("lead")
    current_time[0] = 4.0

    projected = budget.project()
    assert projected.budget.reads_used == 3
    assert projected.budget.candidates_used == 3  # latest max_candidates
    assert projected.budget.elapsed_seconds == 4.0
    assert (quota.successful_reads, quota.used_chars) == (3, 16)
    assert live.state is recovered
    assert recovered.budget.reads_used == 1
    assert elapsed_samples == [1.5, 4.0]


def test_projection_does_not_change_cursor_or_context_when_no_read_succeeds() -> None:
    live = ActiveRuntimeLiveValues(
        state=_state(max_candidates=3, reads_used=1), context={"untouched": True}
    )
    cursor = replace(live.cursor, phase="reading")
    live.cursor = cursor
    quota = ReadWaveQuotaContext(successful_reads=1, used_chars=12)
    projection = ReadWaveBudgetContext(live, quota, lambda: 2.0)

    result = projection.project()

    assert result.budget.reads_used == 1
    assert result.budget.elapsed_seconds == 2.0
    assert live.state.budget.elapsed_seconds != 2.0
    assert live.cursor is cursor
    assert live.context == {"untouched": True}


def test_limit_views_rebind_latest_budget_without_mutation_or_time_sampling() -> None:
    original = _state(max_candidates=5, reads_used=1)
    live = ActiveRuntimeLiveValues(state=original)
    quota = ReadWaveQuotaContext(successful_reads=1, used_chars=12)

    def forbidden_elapsed() -> float:
        raise AssertionError("checking read limits must not sample elapsed time")

    budget = ReadWaveBudgetContext(
        live=live, quota=quota, elapsed=forbidden_elapsed
    )

    assert not budget.exhausted()
    assert budget.remaining_chars() == 88
    assert budget.source_limit() == 88

    # A checkpoint or steering change may replace the state and tighten both
    # ceilings between read admissions. The budget context cannot cache them.
    new_state = _state(max_candidates=2, reads_used=1)
    tightened = replace(
        new_state,
        budget=replace(new_state.budget, max_reads=1, max_total_chars=10),
    )
    live.state = tightened
    assert budget.exhausted()
    assert budget.remaining_chars() == -2
    # Preserve the historical non-clamped result: callers enforce admission.
    assert budget.source_limit() == -2

    # A later increase reuses the same quota but the newest live hard limit.
    reopened = replace(
        tightened,
        budget=replace(tightened.budget, max_reads=3, max_total_chars=7000),
    )
    live.state = reopened
    assert not budget.exhausted()
    assert budget.remaining_chars() == 6988
    assert budget.source_limit() == 6000
    assert (quota.successful_reads, quota.used_chars) == (1, 12)
    assert original.budget.max_total_chars == 100
    assert tightened.budget.max_total_chars == 10


@pytest.mark.parametrize("usable", [True, False], ids=["usable", "failed"])
def test_complete_chain_updates_shared_quota_and_source_before_budget_projection(
    usable: bool,
) -> None:
    state = _state(max_candidates=5, reads_used=1)
    live = ActiveRuntimeLiveValues(state=state)
    quota = ReadWaveQuotaContext(successful_reads=1, used_chars=3)
    results = ActiveResearchResultBuffers([], [], [], [])
    candidate = read_candidate("candidate-a", url="https://example.org/report")
    visuals = [{"unit_id": "figure-a"}]

    def visual_reader(**kwargs: Any) -> list[dict[str, Any]]:
        assert usable
        assert kwargs["state"] is state
        assert kwargs["canonical_url"] == candidate.canonical_url
        assert quota.successful_reads == 2
        assert quota.used_chars == 9
        assert results.selected_sources[0]["read"]["content"] == "strong"
        live.state = _state(max_candidates=7)
        return visuals

    def elapsed() -> float:
        assert len(results.selected_sources) == 1
        record = results.selected_sources[0]
        if usable:
            assert record["visual_units"] is visuals
        else:
            assert record["read_status"] == "failed"
            assert "visual_units" not in record
        return 3.5

    budget = ReadWaveBudgetContext(live, quota, elapsed)
    owner = ReadWaveResultContext(budget, ReadSourceEvidenceContext(results, live, visual_reader))
    projected = owner.record_chain(
        candidate=candidate,
        plan_item={"source_role": "primary", "cluster_id": "cluster-a", "claim_id": "claim-a"},
        chain_steps=[
            ChainStepResult(
                backend="native_http",
                retrieval_state="fetched" if usable else "failed",
                usable_content=usable,
                adequacy_reason="ok" if usable else "failed",
                content="strong whole answer" if usable else "",
            ),
        ],
        source_limit=6,
    )

    assert live.state is not projected  # the executor adopts the returned state
    assert projected.budget.reads_used == quota.successful_reads == (2 if usable else 1)
    assert quota.used_chars == (9 if usable else 3)
    assert projected.budget.max_candidates == (7 if usable else 5)
    assert projected.budget.elapsed_seconds == 3.5
