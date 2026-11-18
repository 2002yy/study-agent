"""A single mutable ResearchState owner survives checkpoint and model callbacks."""

from __future__ import annotations

from dataclasses import replace
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
from src.web.research.runtime import ResearchRuntimeCursor


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


def test_model_and_read_observers_share_latest_rebound_cursor() -> None:
    """A model callback and read observer must not retain a pre-handoff cursor."""
    live = ActiveRuntimeLiveValues(state=_state(20.0))
    model_cursor = live.current_cursor
    read_cursor = live.current_cursor

    original = live.current_cursor()
    after_attempt = replace(original, phase="planning", wave_index=1)
    model_cursor_before = model_cursor()
    assert model_cursor_before is original

    # Model attempt auditing replaces the cursor; the reader sees that value.
    live.set_cursor(after_attempt)
    assert read_cursor() is after_attempt

    # Wave handoff may replace it again after checkpoint/recovery.
    recovered = replace(after_attempt, phase="searching", wave_index=2)
    live.cursor = recovered
    assert model_cursor() is recovered
    assert read_cursor() is recovered


def test_live_values_owns_independent_default_cursors() -> None:
    first = ActiveRuntimeLiveValues(state=_state(10.0))
    second = ActiveRuntimeLiveValues(state=_state(10.0))
    assert isinstance(first.cursor, ResearchRuntimeCursor)
    assert first.cursor is not second.cursor
