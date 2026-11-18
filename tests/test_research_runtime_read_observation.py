"""Read diagnostics bind the latest context and cursor after a checkpoint."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.application.research_runtime_read_observation import (
    ActiveReadObservationContext,
)
from src.web.research.runtime import ResearchRuntimeCursor
from src.web.research.timing_ledger import RuntimePhaseTiming, TimingLedger


@pytest.fixture
def read_observation_case() -> tuple[SimpleNamespace, ActiveReadObservationContext]:
    """Reuse the same live-state and timing setup for phase and retry tests."""

    tick: dict[str, float] = {"now": 1.0}
    ledger = TimingLedger(now_ms=lambda: tick["now"] * 1000.0)
    ledger.start_wave(1)
    live = SimpleNamespace(
        context={"before": True},
        cursor=ResearchRuntimeCursor(wave_index=1),
        tick=tick,
    )
    observation = ActiveReadObservationContext(
        current_context=lambda: live.context,
        current_cursor=lambda: live.cursor,
        phase_timing=RuntimePhaseTiming(ledger=ledger, now=lambda: tick["now"]),
        timing_ledger=ledger,
    )
    return live, observation


def test_read_phase_end_records_on_rebound_context(
    read_observation_case: tuple[SimpleNamespace, ActiveReadObservationContext],
) -> None:
    live, observation = read_observation_case
    old_context = live.context
    observation.phase_start("read")
    live.context = {"after_checkpoint": True}
    live.tick["now"] = 1.5

    observation.phase_end("read")

    assert "claim_engine_metrics" not in old_context
    assert live.context["claim_engine_metrics"]["phase_seconds"]["read"] == {
        "seconds": 0.5,
        "calls": 1,
    }
    assert observation.phase_timing.started == {}


def test_read_retry_and_wave_index_use_live_bindings(
    read_observation_case: tuple[SimpleNamespace, ActiveReadObservationContext],
) -> None:
    live, observation = read_observation_case
    assert observation.wave_index() == 1
    live.cursor = ResearchRuntimeCursor(wave_index=4)

    observation.retry(wait_ms=12.0, fetch_ms=7.0)
    timeline: dict[str, Any] = observation.timing_ledger.to_metrics()

    assert observation.wave_index() == 4
    assert timeline["wave_timeline"][0]["retry_count"] == 1
    assert timeline["wave_timeline"][0]["retry_wait_ms"] == 12.0
    assert timeline["wave_timeline"][0]["retry_fetch_ms"] == 7.0
