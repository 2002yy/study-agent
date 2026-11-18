"""Focused invariants for the run-scoped steering boundary."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from src.application.research_runtime_steering_context import (
    ActiveResearchSteeringContext,
)
from src.web.research.steering import (
    ACTIVE_RESEARCH_STEERING_KEY,
    append_active_steering,
)


def _boundary(
    durable: dict[str, Any] | None,
) -> tuple[ActiveResearchSteeringContext, Mock]:
    repository = Mock()
    repository.get.return_value = (
        SimpleNamespace(research_context=durable) if durable is not None else None
    )
    timing = Mock()
    times = iter((10.0, 13.0))
    return (
        ActiveResearchSteeringContext(
            repository=repository,
            run_id="run-1",
            utc_now=lambda: "2026-11-18T00:00:00Z",
            elapsed_ms=lambda: next(times),
            timing_ledger=timing,
        ),
        timing,
    )


def test_refresh_uses_live_context_and_merges_concurrent_direction() -> None:
    incoming = append_active_steering(
        {}, entry_id="a", content="first", received_at="2026-11-18T00:00:00Z"
    )
    durable = append_active_steering(
        incoming, entry_id="b", content="second", received_at="2026-11-18T00:00:01Z"
    )
    incoming[ACTIVE_RESEARCH_STEERING_KEY][0]["status"] = "applied"
    steering, timing = _boundary(durable)

    refreshed = steering.refresh(incoming)

    assert [entry["id"] for entry in refreshed[ACTIVE_RESEARCH_STEERING_KEY]] == [
        "a",
        "b",
    ]
    assert refreshed[ACTIVE_RESEARCH_STEERING_KEY][0]["status"] == "applied"
    assert incoming[ACTIVE_RESEARCH_STEERING_KEY][0]["status"] == "applied"
    timing.record_refresh.assert_called_once_with(3.0)


def test_refresh_failure_does_not_record_successful_refresh() -> None:
    steering, timing = _boundary(None)
    with pytest.raises(ValueError, match="WebLookupRun not found: run-1"):
        steering.refresh({})
    timing.record_refresh.assert_not_called()


def test_apply_preserves_timestamp_before_evidence_snapshot(monkeypatch: Any) -> None:
    import src.application.research_runtime_steering_context as module

    events: list[str] = []
    steering, _ = _boundary({})
    steering = replace(steering, utc_now=lambda: (events.append("timestamp"), "now")[1])
    state: Any = object()
    context = {"version": 2}
    projection = Mock(return_value=(state, context, ("direction-1",)))
    monkeypatch.setattr(module, "_apply_pending_active_steering", projection)

    assert steering.apply_pending(
        state=state,
        context=context,
        wave_index=2,
        known_evidence_ids=lambda: (events.append("evidence"), ("evidence-1",))[1],
    ) == (state, context, ("direction-1",))
    assert events == ["timestamp", "evidence"]
    assert projection.call_args.kwargs["applied_at"] == "now"
    assert projection.call_args.kwargs["known_evidence_ids"] == ("evidence-1",)
