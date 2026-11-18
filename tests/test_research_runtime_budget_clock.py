"""Budget-clock contract: sampling, live state binding and unchanged bounds."""

from __future__ import annotations

from dataclasses import replace

from src.application.research_runtime_budget_clock import ResearchBudgetClock
from src.application.research_runtime_checkpoint import updated_runtime_budget
from src.web.research.contracts import ResearchBudget, ResearchState
from src.web.research.runtime import ResearchRuntimeCursor, RuntimeCandidate


class _Clock:
    def __init__(self, value: float) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return self.value


def _budget_clock(
    now: _Clock,
    hard_seconds: list[float],
    *,
    base_elapsed: float = 5.0,
) -> ResearchBudgetClock:
    return ResearchBudgetClock(
        monotonic=now,
        execution_started=10.0,
        base_elapsed=base_elapsed,
        current_hard_seconds=lambda: hard_seconds[0],
        model_timeout_cap_seconds=20.0,
        reserve_seconds=12.0,
    )


def test_elapsed_reuses_restored_base_and_ignores_monotonic_rewind() -> None:
    now = _Clock(14.0)
    clock = _budget_clock(now, [60.0], base_elapsed=17.0)

    assert clock.elapsed() == 21.0
    now.value = 9.0
    assert clock.elapsed() == 17.0
    assert now.calls == 2


def test_current_hard_limit_is_read_after_runtime_state_rebinding() -> None:
    now = _Clock(13.0)
    hard_seconds = [60.0]
    clock = _budget_clock(now, hard_seconds)

    assert clock.hard_seconds_left() == 52.0
    assert clock.research_seconds_left() == 40.0
    hard_seconds[0] = 45.0
    assert clock.hard_seconds_left() == 37.0
    assert clock.research_seconds_left() == 25.0
    assert now.calls == 4  # one monotonic reading per check


def test_research_window_boundary_uses_current_limit_and_one_sample() -> None:
    now = _Clock(10.0)
    hard_seconds = [17.0]
    clock = _budget_clock(now, hard_seconds)

    assert clock.research_window_exhausted() is True
    hard_seconds[0] = 18.0
    assert clock.research_window_exhausted() is False
    assert now.calls == 2


def test_model_timeout_preserves_cap_floor_and_research_reserve() -> None:
    now = _Clock(10.0)
    hard_seconds = [60.0]
    clock = _budget_clock(now, hard_seconds)

    assert clock.remaining_timeout() == 20.0
    hard_seconds[0] = 22.0
    assert clock.remaining_timeout() == 5.0
    hard_seconds[0] = 16.0
    assert clock.remaining_timeout() == 1.0
    assert now.calls == 3


def test_elapsed_ms_retains_single_sampling_and_one_decimal_rounding() -> None:
    now = _Clock(10.00024)
    clock = _budget_clock(now, [60.0], base_elapsed=0.0)

    assert clock.elapsed_ms() == 0.2
    assert now.calls == 1


def test_budget_projection_only_uses_explicit_current_state_and_cursor() -> None:
    original_budget = ResearchBudget(
        max_candidates=2,
        max_reads=3,
        soft_timeout_seconds=10.0,
        hard_timeout_seconds=30.0,
        candidates_used=1,
        reads_used=2,
        elapsed_seconds=4.0,
    )
    state = ResearchState(
        mode="active",
        questions=(),
        claims=(),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=original_budget,
    )
    cursor = ResearchRuntimeCursor(
        candidates=tuple(
            RuntimeCandidate(id=f"candidate-{index}", url=f"https://test/{index}", title="")
            for index in range(3)
        )
    )

    with_read = updated_runtime_budget(
        state, cursor, elapsed_seconds=8.0, reads_used=3
    )
    assert with_read.budget.candidates_used == 2
    assert with_read.budget.reads_used == 3
    assert with_read.budget.elapsed_seconds == 8.0
    assert state.budget is original_budget

    rebound = replace(state, budget=replace(original_budget, reads_used=3))
    without_read = updated_runtime_budget(rebound, cursor, elapsed_seconds=9.0)
    assert without_read.budget.reads_used == 3
    assert without_read.budget.elapsed_seconds == 9.0
    assert rebound.budget.elapsed_seconds == 4.0
