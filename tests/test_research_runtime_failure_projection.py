"""Runtime failure projection preserves identity and does not persist state."""

from dataclasses import replace
from types import SimpleNamespace
from typing import cast

import pytest

from src.application.research_runtime_failure_projection import (
    ActiveRuntimeFailureContext,
    with_appended_runtime_failure,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.web.research.contracts import ResearchState
from src.web.research.runtime import ResearchRuntimeCursor


def test_failure_projection_uses_current_rebound_attempt_for_unattached_ids() -> None:
    empty = ResearchRuntimeCursor()
    first = with_appended_runtime_failure(
        empty,
        {"run_attempt": 1},
        code="read_failed",
        phase="reading",
        item_id="candidate-7",
    )
    resumed = with_appended_runtime_failure(
        first,
        {"run_attempt": 2},
        code="read_failed",
        phase="reading",
        item_id="candidate-7",
    )

    assert empty.failures == ()
    assert first.failures[0].attempt_id == "run-attempt:1"
    assert resumed.failures[1].attempt_id == "run-attempt:2"
    assert first.failures[0].failure_id != resumed.failures[1].failure_id

    duplicate = with_appended_runtime_failure(
        first,
        {"run_attempt": 1},
        code="read_failed",
        phase="reading",
        item_id="candidate-7",
    )
    assert duplicate.failures == first.failures
    assert len(duplicate.failures) == 1


def test_failure_projection_respects_explicit_attempt_without_context_lookup() -> None:
    # The old closure short-circuits `attempt_id or context['run_attempt']`.
    # An explicit attempt remains valid even if no run_attempt is supplied.
    cursor = with_appended_runtime_failure(
        ResearchRuntimeCursor(),
        {},
        code="model_attempts_exhausted",
        phase="planning",
        logical_call_id="claim:7",
        item_id="claim:7",
        detail="provider unavailable",
        attempt_id="claim:7:attempt:2",
    )

    assert len(cursor.failures) == 1
    assert cursor.failures[0].attempt_id == "claim:7:attempt:2"
    assert cursor.failures[0].detail == "provider unavailable"


def test_failure_projection_missing_fallback_context_cannot_mutate_cursor() -> None:
    original = ResearchRuntimeCursor()
    with pytest.raises(KeyError, match="run_attempt"):
        with_appended_runtime_failure(
            original, {}, code="read_failed", phase="reading", item_id="missing"
        )

    assert original.failures == ()


def _live_failure_case() -> tuple[ActiveRuntimeLiveValues, ActiveRuntimeFailureContext]:
    """One replaceable cursor/context owner for all append-path regressions."""
    live = ActiveRuntimeLiveValues(
        state=cast(ResearchState, SimpleNamespace()),
        context={"run_attempt": 1},
    )
    return live, ActiveRuntimeFailureContext(live)


def test_live_failure_context_resolves_new_attempt_after_context_and_cursor_rebind() -> None:
    live, failures = _live_failure_case()
    old_cursor = live.current_cursor()
    failures.append("read_failed", "reading", item_id="candidate-7")
    assert old_cursor.failures == ()
    first = live.current_cursor()
    assert first.failures[0].attempt_id == "run-attempt:1"

    # Checkpoint recovery replaces both values while retaining the failure context.
    live.context = {"run_attempt": 2}
    live.set_cursor(replace(first, phase="reading"))
    failures.append("read_failed", "reading", item_id="candidate-7")
    updated = live.current_cursor()
    assert len(updated.failures) == 2
    assert updated.failures[1].attempt_id == "run-attempt:2"
    assert updated.failures[0].failure_id != updated.failures[1].failure_id

    failures.append("read_failed", "reading", item_id="candidate-7")
    assert len(live.current_cursor().failures) == 2


def test_live_failure_context_dedupes_logical_call_across_recovery_attempts() -> None:
    live, failures = _live_failure_case()
    failures.append(
        "model_attempts_exhausted",
        "assessing",
        logical_call_id="claim:7",
        item_id="claim:7",
        detail="attempts_exhausted",
    )
    existing = live.current_cursor().failures
    live.context = {"run_attempt": 2}
    failures.append(
        "model_attempts_exhausted",
        "assessing",
        logical_call_id="claim:7",
        item_id="claim:7",
        detail="attempts_exhausted",
    )
    assert live.current_cursor().failures == existing


def test_live_failure_context_retains_cursor_on_missing_attempt_context() -> None:
    live, failures = _live_failure_case()
    before = live.current_cursor()
    live.context = {}
    with pytest.raises(KeyError, match="run_attempt"):
        failures.append("read_failed", "reading", item_id="missing")
    assert live.current_cursor() is before

    failures.append(
        "model_attempts_exhausted",
        "planning",
        logical_call_id="claim:7",
        attempt_id="claim:7:attempt:2",
    )
    assert live.current_cursor().failures[0].attempt_id == "claim:7:attempt:2"
