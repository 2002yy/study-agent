"""A single mutable ResearchState owner survives checkpoint and model callbacks."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from src.application.research_runtime_budget_clock import ResearchBudgetClock
from src.application.research_runtime_execution_guard import (
    ActiveResearchExecutionGuard,
    HardResearchBudgetReached,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.contracts import ResearchState


def _state(hard_seconds: float) -> ResearchState:
    # Only the budget limit is relevant to the two read-only consumers.
    return cast(
        ResearchState,
        SimpleNamespace(budget=SimpleNamespace(hard_timeout_seconds=hard_seconds)),
    )


def test_budget_clock_and_model_guard_share_rebound_state_owner() -> None:
    original = _state(10.0)
    recovered = _state(20.0)
    live = ActiveRuntimeLiveValues(state=original)
    clock = ResearchBudgetClock(
        monotonic=lambda: 0.0,
        execution_started=0.0,
        base_elapsed=15.0,
        current_hard_seconds=live.hard_timeout_seconds,
        model_timeout_cap_seconds=12.0,
        reserve_seconds=5.0,
    )
    guard = ActiveResearchExecutionGuard(
        repository=Mock(spec=WebLookupRepository),
        run_id="run-1",
        operation_id="operation-1",
        elapsed=clock.elapsed,
    )

    assert clock.hard_seconds_left() == -5.0
    with pytest.raises(HardResearchBudgetReached):
        guard.ensure_budget(live.current_state())

    # A restored/checkpoint-prepared state replaces the value, not its owner.
    live.state = recovered
    assert live.current_state() is recovered
    assert clock.hard_seconds_left() == 5.0
    guard.ensure_budget(live.current_state())
