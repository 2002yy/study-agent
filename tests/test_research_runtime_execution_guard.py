"""Run guards never cache a stale recovered budget or cancellation token."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

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


def test_budget_check_uses_supplied_current_state_at_exact_boundary() -> None:
    repository = Mock(spec=WebLookupRepository)
    observed = [9.0, 10.0, 10.0]
    guard = ActiveResearchExecutionGuard(
        repository=repository,
        run_id="run-1",
        operation_id="operation-2",
        elapsed=lambda: observed.pop(0),
    )
    # This guard needs only the budget limit, not an unrelated full claim graph.
    state = cast(
        ResearchState,
        SimpleNamespace(budget=SimpleNamespace(hard_timeout_seconds=10.0)),
    )
    recovered_state = cast(
        ResearchState,
        SimpleNamespace(budget=SimpleNamespace(hard_timeout_seconds=15.0)),
    )

    guard.ensure_budget(state)
    guard.ensure_budget(recovered_state)
    with pytest.raises(HardResearchBudgetReached):
        guard.ensure_budget(state)
    repository.cancel_requested.assert_not_called()
