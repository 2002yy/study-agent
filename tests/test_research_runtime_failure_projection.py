"""Runtime failure projection preserves identity and does not persist state."""

import pytest

from src.application.research_runtime_failure_projection import (
    with_appended_runtime_failure,
)
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
