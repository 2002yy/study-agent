"""Run diagnostics bind the latest context and cursor after a checkpoint."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_observation import (
    ActiveRuntimeObservationContext,
)
from src.web.research.contracts import ResearchState
from src.web.research.runtime import ResearchRuntimeCursor
from src.web.research.timing_ledger import RuntimePhaseTiming, TimingLedger


@pytest.fixture
def runtime_observation_case() -> tuple[ActiveRuntimeLiveValues, dict[str, float], ActiveRuntimeObservationContext]:
    """Share the same live-state and timing setup for all phase/retry tests."""

    tick: dict[str, float] = {"now": 1.0}
    ledger = TimingLedger(now_ms=lambda: tick["now"] * 1000.0)
    ledger.start_wave(1)
    live = ActiveRuntimeLiveValues(
        state=cast(ResearchState, SimpleNamespace()),
        context={"before": True},
        cursor=ResearchRuntimeCursor(wave_index=1),
    )
    observation = ActiveRuntimeObservationContext(
        live=live,
        phase_timing=RuntimePhaseTiming(ledger=ledger, now=lambda: tick["now"]),
        timing_ledger=ledger,
    )
    return live, tick, observation


@pytest.mark.parametrize("phase", ["read", "assessment", "late_tail", "ranking", "gating"])
def test_phase_end_records_on_rebound_context(
    runtime_observation_case: tuple[ActiveRuntimeLiveValues, dict[str, float], ActiveRuntimeObservationContext],
    phase: str,
) -> None:
    live, tick, observation = runtime_observation_case
    old_context = live.context
    observation.phase_start(phase)
    live.context = {"after_checkpoint": True}
    tick["now"] = 1.5

    observation.phase_end(phase)

    assert "claim_engine_metrics" not in old_context
    assert live.context["claim_engine_metrics"]["phase_seconds"][phase] == {
        "seconds": 0.5,
        "calls": 1,
    }
    assert observation.phase_timing.started == {}


def test_sequential_phases_do_not_write_to_stale_context(
    runtime_observation_case: tuple[ActiveRuntimeLiveValues, dict[str, float], ActiveRuntimeObservationContext],
) -> None:
    live, tick, observation = runtime_observation_case
    observation.phase_start("assessment")
    tick["now"] = 1.2
    observation.phase_end("assessment")
    first_context = live.context

    live.context = {"after_checkpoint": True}
    observation.phase_start("extraction")
    tick["now"] = 1.7
    observation.phase_end("extraction")

    assert first_context["claim_engine_metrics"]["phase_seconds"] == {
        "assessment": {"seconds": pytest.approx(0.2), "calls": 1}
    }
    assert live.context["claim_engine_metrics"]["phase_seconds"] == {
        "extraction": {"seconds": pytest.approx(0.5), "calls": 1}
    }


def test_read_retry_and_wave_index_use_live_bindings(
    runtime_observation_case: tuple[ActiveRuntimeLiveValues, dict[str, float], ActiveRuntimeObservationContext],
) -> None:
    live, tick, observation = runtime_observation_case
    assert observation.wave_index() == 1
    live.cursor = ResearchRuntimeCursor(wave_index=4)

    observation.retry(wait_ms=12.0, fetch_ms=7.0)
    timeline: dict[str, Any] = observation.timing_ledger.to_metrics()

    assert observation.wave_index() == 4
    assert timeline["wave_timeline"][0]["retry_count"] == 1
    assert timeline["wave_timeline"][0]["retry_wait_ms"] == 12.0
    assert timeline["wave_timeline"][0]["retry_fetch_ms"] == 7.0


def test_live_observation_rebinds_state_cursor_and_context_after_checkpoint(
    runtime_observation_case: tuple[ActiveRuntimeLiveValues, dict[str, float], ActiveRuntimeObservationContext],
) -> None:
    live, _, observation = runtime_observation_case
    original_context = live.current_context()
    original_cursor = live.current_cursor()

    # Both replaceable values change together at the durable checkpoint seam.
    recovered_state = cast(ResearchState, SimpleNamespace())
    live.bind_prepared_checkpoint(recovered_state, {"run_attempt": 2})
    live.set_cursor(ResearchRuntimeCursor(wave_index=7))

    assert observation.live is live
    assert observation.current_context() is live.current_context()
    assert observation.current_cursor() is live.current_cursor()
    assert observation.current_context() is not original_context
    assert observation.current_cursor() is not original_cursor
    assert observation.wave_index() == 7
    assert original_context == {"before": True}
