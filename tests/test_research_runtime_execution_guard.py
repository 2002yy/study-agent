"""Run guards never cache a stale recovered budget or cancellation token."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_execution_guard import (
    ActiveResearchCancelled,
    ActiveResearchExecutionGuard,
    HardResearchBudgetReached,
)
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.contracts import ResearchState


def test_cancellation_queries_live_operation_owner() -> None:
    repository = Mock(spec=WebLookupRepository)
    repository.cancel_requested.side_effect = [False, True, False, True]
    guard = ActiveResearchExecutionGuard(
        live=ActiveRuntimeLiveValues(state=cast(ResearchState, object())),
        repository=repository,
        run_id="run-1",
        operation_id="operation-2",
        elapsed=lambda: 0.0,
    )

    # The candidate pool needs a bool probe, not the runtime exception.
    assert guard.cancel_requested() is False
    assert guard.cancel_requested() is True
    guard.ensure_active()
    with pytest.raises(ActiveResearchCancelled, match="active research cancelled"):
        guard.ensure_active()
    assert repository.cancel_requested.call_count == 4
    repository.cancel_requested.assert_called_with(
        "run-1", operation_id="operation-2"
    )


def _state(hard_timeout_seconds: float) -> ResearchState:
    """Only the current hard limit matters to the admission guard."""
    return cast(
        ResearchState,
        SimpleNamespace(
            budget=SimpleNamespace(hard_timeout_seconds=hard_timeout_seconds)
        ),
    )


def test_budget_check_uses_rebound_live_state_at_exact_boundary() -> None:
    repository = Mock(spec=WebLookupRepository)
    observed = [9.0, 10.0, 10.0]
    live = ActiveRuntimeLiveValues(state=_state(10.0))
    guard = ActiveResearchExecutionGuard(
        live=live,
        repository=repository,
        run_id="run-1",
        operation_id="operation-2",
        elapsed=lambda: observed.pop(0),
    )

    guard.ensure_budget()
    live.state = _state(15.0)
    guard.ensure_budget()
    live.state = _state(10.0)
    with pytest.raises(HardResearchBudgetReached):
        guard.ensure_budget()

    assert observed == []
    repository.cancel_requested.assert_not_called()


def test_budget_samples_state_before_clock_without_mutation() -> None:
    repository = Mock(spec=WebLookupRepository)
    initial = _state(10.0)
    rebound = _state(1.0)
    live = ActiveRuntimeLiveValues(state=initial)
    order: list[str] = []

    def elapsed() -> float:
        order.append("clock")
        live.state = rebound
        return 5.0

    guard = ActiveResearchExecutionGuard(
        live=live,
        repository=repository,
        run_id="run-1",
        operation_id="operation-2",
        elapsed=elapsed,
    )
    # Freeze the original caller's ordering: state resolved before the clock
    # samples elapsed time, even if the clock callback changes the owner.
    guard.ensure_budget()
    assert order == ["clock"]
    assert live.state is rebound
    with pytest.raises(HardResearchBudgetReached):
        guard.ensure_budget()
    assert order == ["clock", "clock"]
    repository.cancel_requested.assert_not_called()


def test_budget_rejection_does_not_cancel_or_persist() -> None:
    repository = Mock(spec=WebLookupRepository)
    live = ActiveRuntimeLiveValues(state=_state(3.0))
    clock_samples: list[float] = []

    def elapsed() -> float:
        clock_samples.append(3.0)
        return 3.0

    guard = ActiveResearchExecutionGuard(
        live=live,
        repository=repository,
        run_id="run-1",
        operation_id="operation-2",
        elapsed=elapsed,
    )
    with pytest.raises(HardResearchBudgetReached):
        guard.ensure_budget()
    assert clock_samples == [3.0]
    repository.assert_not_called()
