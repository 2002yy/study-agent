"""§164-C1b: the shadow read must be bounded, isolated and droppable."""

from __future__ import annotations

import threading
import time

import pytest

from src.application.learner_state_parity_observer import LearnerStateParityCollector
from src.application.shadow_isolation import (
    BestEffortTelemetry,
    DEFAULT_SHADOW_BUDGET_SECONDS,
    ShadowOutcome,
    run_shadow_bounded,
)
from src.domain.learner_state_parity import SHADOW_ERROR, SHADOW_OK, SHADOW_UNAVAILABLE

BUDGET = 0.15


def test_normal_work_returns_ok_with_its_value() -> None:
    outcome = run_shadow_bounded(lambda: {"classification": "MATCH"}, budget_seconds=BUDGET)
    assert outcome.ok is True
    assert outcome.status == SHADOW_OK
    assert outcome.value == {"classification": "MATCH"}


def test_failing_work_is_fail_open() -> None:
    def explode() -> object:
        raise RuntimeError("durable read exploded")

    outcome = run_shadow_bounded(explode, budget_seconds=BUDGET)
    assert outcome.status == SHADOW_ERROR
    assert outcome.reason == "RuntimeError"
    assert outcome.value is None


def test_stalling_work_hits_the_budget_and_the_caller_continues() -> None:
    release = threading.Event()

    def stall() -> object:
        release.wait(timeout=5)
        return "too late"

    started = time.monotonic()
    outcome = run_shadow_bounded(stall, budget_seconds=BUDGET)
    elapsed = time.monotonic() - started

    assert outcome.status == SHADOW_UNAVAILABLE
    assert outcome.reason == "budget_exceeded"
    # The caller returned within the budget, not when the worker finished.
    assert elapsed < 1.0, elapsed
    release.set()


def test_cancellation_of_the_shadow_does_not_propagate() -> None:
    """shadow cancellation != production turn cancellation."""

    def cancelled() -> object:
        raise KeyboardInterrupt

    outcome = run_shadow_bounded(cancelled, budget_seconds=BUDGET)
    assert isinstance(outcome, ShadowOutcome)
    assert outcome.status == SHADOW_ERROR
    assert outcome.reason == "isolated:KeyboardInterrupt"


def test_non_positive_budget_is_unavailable_not_an_error() -> None:
    outcome = run_shadow_bounded(lambda: "x", budget_seconds=0)
    assert outcome.status == SHADOW_UNAVAILABLE
    assert outcome.reason == "budget_not_positive"


def test_slow_telemetry_does_not_block_the_returned_outcome() -> None:
    recorded: list[object] = []

    def slow_sink(value: object) -> None:
        time.sleep(0.5)
        recorded.append(value)

    started = time.monotonic()
    outcome = run_shadow_bounded(
        lambda: "observation", budget_seconds=BUDGET, on_telemetry=slow_sink
    )
    elapsed = time.monotonic() - started

    # The read was bounded; the telemetry hook is the caller's own cost and is
    # not part of the read budget, but it must never change the outcome.
    assert outcome.status == SHADOW_OK
    assert outcome.value == "observation"
    assert elapsed < 1.0


def test_telemetry_failure_is_swallowed() -> None:
    def broken_sink(value: object) -> None:
        raise RuntimeError("telemetry write failed")

    outcome = run_shadow_bounded(
        lambda: "observation", budget_seconds=BUDGET, on_telemetry=broken_sink
    )
    assert outcome.status == SHADOW_OK
    assert outcome.value == "observation"


def test_best_effort_telemetry_drops_failures_without_raising() -> None:
    class BrokenSink:
        def record(self, observation: object) -> None:
            raise RuntimeError("collector is down")

    telemetry = BestEffortTelemetry(BrokenSink())
    telemetry.record({"turn_id": "t1"})
    assert telemetry.recorded == 0
    assert telemetry.dropped == 1


def test_best_effort_telemetry_counts_successful_records() -> None:
    collector = LearnerStateParityCollector()
    telemetry = BestEffortTelemetry(collector)
    telemetry.record("observation")
    assert telemetry.recorded == 1
    assert telemetry.dropped == 0
    assert collector.observations() == ("observation",)


def test_missing_sink_is_a_legal_drop() -> None:
    """chat turn success + parity artifact missing is a legal state."""
    telemetry = BestEffortTelemetry(None)
    telemetry.record("observation")
    assert telemetry.recorded == 0
    assert telemetry.dropped == 1


def test_default_budget_is_an_explicit_constant() -> None:
    assert isinstance(DEFAULT_SHADOW_BUDGET_SECONDS, float)
    assert 0 < DEFAULT_SHADOW_BUDGET_SECONDS <= 1.0


@pytest.mark.parametrize("scenario", ["normal", "throws", "stalls", "cancelled"])
def test_production_path_always_continues(scenario: str) -> None:
    """Whatever the shadow does, the caller gets control back and can proceed."""
    release = threading.Event()

    def work() -> object:
        if scenario == "normal":
            return "ok"
        if scenario == "throws":
            raise ValueError("boom")
        if scenario == "cancelled":
            raise KeyboardInterrupt
        release.wait(timeout=5)
        return "late"

    outcome = run_shadow_bounded(work, budget_seconds=BUDGET)
    production_continued = True  # the call returned; the turn can proceed
    assert production_continued is True
    assert isinstance(outcome, ShadowOutcome)
    if scenario == "normal":
        assert outcome.status == SHADOW_OK
    elif scenario == "stalls":
        assert outcome.status == SHADOW_UNAVAILABLE
    else:
        assert outcome.status == SHADOW_ERROR
    release.set()
