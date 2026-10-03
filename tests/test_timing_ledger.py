"""F2-S1 timing ledger: exclusive spans, wave parents, wait decomposition."""

from __future__ import annotations

import pytest

from src.web.research.timing_ledger import (
    TimedGateway,
    TimingLedger,
    model_kind,
)


class _Clock:
    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, ms: float) -> None:
        self.value += ms


def test_exclusive_spans_never_exceed_the_parent() -> None:
    clock = _Clock()
    ledger = TimingLedger(clock)
    ledger.start_wave(1)
    with ledger.span("search"):
        clock.advance(500)
        with ledger.span("search_model"):
            clock.advance(200)
        clock.advance(100)
    clock.advance(400)  # outside any span -> unattributed
    ledger.end_wave()

    record = ledger.to_metrics()["wave_timeline"][0]
    assert record["duration_ms"] == pytest.approx(1200.0)
    # exclusive: search owns 500 + 100 = 600 of its 800ms inclusive span
    assert record["spans_ms"]["search"] == pytest.approx(600.0)
    assert record["spans_ms"]["search_model"] == pytest.approx(200.0)
    assert record["covered_ms"] == pytest.approx(800.0)
    assert record["unattributed_ms"] == pytest.approx(400.0)


def test_model_waits_are_components_not_additions() -> None:
    clock = _Clock()
    ledger = TimingLedger(clock)
    ledger.start_wave(1)
    with ledger.span("assessment"):
        clock.advance(300)
        ledger.record_model_call("assessment", 250)
        ledger.record_model_call("assessment", 400)
    ledger.end_wave()

    record = ledger.to_metrics()["wave_timeline"][0]
    assert record["model_calls"]["assessment"] == 2
    assert record["model_wait_ms"]["assessment"] == pytest.approx(650.0)
    assert record["model_wait_max_ms"]["assessment"] == pytest.approx(400.0)
    # the span stays the authoritative wall time; waits do not extend it
    assert record["spans_ms"]["assessment"] == pytest.approx(300.0)
    assert record["covered_ms"] == pytest.approx(300.0)


def test_retry_backoff_and_fetch_are_separate() -> None:
    clock = _Clock()
    ledger = TimingLedger(clock)
    ledger.start_wave(1)
    ledger.record_retry(wait_ms=1000.0, fetch_ms=12000.0)
    ledger.record_retry(wait_ms=2000.0, fetch_ms=8000.0)
    ledger.end_wave()

    record = ledger.to_metrics()["wave_timeline"][0]
    assert record["retry_count"] == 2
    assert record["retry_wait_ms"] == pytest.approx(3000.0)
    assert record["retry_fetch_ms"] == pytest.approx(20000.0)


def test_refresh_and_checkpoint_are_explicit_spans() -> None:
    clock = _Clock()
    ledger = TimingLedger(clock)
    ledger.start_wave(2)
    ledger.record_refresh(3700.0)
    ledger.record_refresh(120.0)
    ledger.record_checkpoint(80.0)
    ledger.end_wave()

    record = ledger.to_metrics()["wave_timeline"][0]
    assert record["refresh_steering_count"] == 2
    assert record["refresh_steering_ms"] == pytest.approx(3820.0)
    assert record["checkpoint_count"] == 1
    assert record["checkpoint_ms"] == pytest.approx(80.0)


def test_waves_are_separate_parent_records() -> None:
    clock = _Clock()
    ledger = TimingLedger(clock)
    ledger.start_wave(1)
    clock.advance(18000)
    ledger.end_wave()
    ledger.start_wave(2)
    clock.advance(10000)
    ledger.end_wave()

    timeline = ledger.to_metrics()["wave_timeline"]
    assert [item["wave_index"] for item in timeline] == [1, 2]
    assert timeline[0]["duration_ms"] == pytest.approx(18000.0)
    assert timeline[1]["duration_ms"] == pytest.approx(10000.0)


def test_starting_a_wave_closes_the_previous_one() -> None:
    clock = _Clock()
    ledger = TimingLedger(clock)
    ledger.start_wave(1)
    clock.advance(5000)
    ledger.start_wave(2)  # no explicit end for wave 1
    clock.advance(1000)
    ledger.end_wave()

    timeline = ledger.to_metrics()["wave_timeline"]
    assert timeline[0]["duration_ms"] == pytest.approx(5000.0)
    assert timeline[1]["duration_ms"] == pytest.approx(1000.0)


def test_phase_spans_and_missing_exits_are_tolerated() -> None:
    clock = _Clock()
    ledger = TimingLedger(clock)
    ledger.start_wave(1)
    ledger._phase_enter("read")
    clock.advance(250)
    ledger._phase_exit("read")
    ledger._phase_exit("never_opened")  # tolerated
    ledger.end_wave()

    record = ledger.to_metrics()["wave_timeline"][0]
    assert record["spans_ms"]["read"] == pytest.approx(250.0)


def test_timed_gateway_records_purpose_kinds() -> None:
    clock = _Clock()
    ledger = TimingLedger(clock)
    ledger.start_wave(1)

    class _Inner:
        def complete_structured(self, **kwargs):
            clock.advance(400)
            return {"ok": True}

    gateway = TimedGateway(_Inner(), ledger, clock)
    gateway.complete_structured(purpose="research_selection_authority")
    gateway.complete_structured(purpose="research_candidate_assessment")
    gateway.complete_structured(purpose="something_else")
    ledger.end_wave()

    record = ledger.to_metrics()["wave_timeline"][0]
    assert record["model_calls"] == {
        "assessment": 1,
        "other": 1,
        "selector": 1,
    }
    assert record["model_wait_ms"]["selector"] == pytest.approx(400.0)
    assert model_kind("research_evidence_extraction") == "extraction"
    assert model_kind("research_support_formation") == "support"
    assert model_kind("") == "other"


def test_timed_gateway_delegates_unknown_attributes() -> None:
    ledger = TimingLedger(_Clock())
    ledger.start_wave(1)

    class _Inner:
        model_profile = "flash"

    gateway = TimedGateway(_Inner(), ledger, _Clock())
    assert gateway.model_profile == "flash"
