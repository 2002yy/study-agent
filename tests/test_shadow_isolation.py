"""§164-C1b-0: the shadow read must be bounded in workers, queue and telemetry."""

from __future__ import annotations

import threading
import time

import pytest

from src.application import shadow_isolation as iso
from src.application.learner_state_parity_observer import LearnerStateParityCollector
from src.application.shadow_isolation import (
    BestEffortTelemetry,
    CALLER_CANCELLED,
    CALLER_COMPLETED,
    CALLER_FAILED,
    CALLER_REJECTED,
    CALLER_TIMED_OUT,
    DEFAULT_SHADOW_BUDGET_SECONDS,
    SHADOW_CAPACITY,
    SHADOW_WORKERS,
    ShadowOutcome,
    run_shadow_bounded,
    shadow_resource_state,
)
from src.domain.learner_state_parity import SHADOW_ERROR, SHADOW_OK, SHADOW_UNAVAILABLE

BUDGET = 0.15


# ------------------------------------------------------------------ behaviour

def test_normal_work_completes() -> None:
    outcome = run_shadow_bounded(lambda: {"classification": "MATCH"}, budget_seconds=BUDGET)
    assert outcome.status == SHADOW_OK
    assert outcome.caller_status == CALLER_COMPLETED
    assert outcome.value == {"classification": "MATCH"}


def test_failing_work_is_isolated() -> None:
    def explode() -> object:
        raise RuntimeError("durable read exploded")

    outcome = run_shadow_bounded(explode, budget_seconds=BUDGET)
    assert outcome.status == SHADOW_ERROR
    assert outcome.reason == "RuntimeError"
    assert outcome.caller_status == CALLER_FAILED


def test_stall_hits_the_budget_and_does_not_claim_the_worker_stopped() -> None:
    release = threading.Event()

    def stall() -> object:
        release.wait(timeout=5)
        return "too late"

    started = time.monotonic()
    outcome = run_shadow_bounded(stall, budget_seconds=BUDGET)
    elapsed = time.monotonic() - started

    assert outcome.status == SHADOW_UNAVAILABLE
    assert outcome.reason == "budget_exceeded"
    assert outcome.caller_status == CALLER_TIMED_OUT
    # A running thread cannot be safely killed, so this must stay unknown.
    assert outcome.worker_termination_known is False
    assert elapsed < 1.0, elapsed
    release.set()


def test_non_positive_budget_is_rejected() -> None:
    outcome = run_shadow_bounded(lambda: "x", budget_seconds=0)
    assert outcome.status == SHADOW_UNAVAILABLE
    assert outcome.reason == "budget_not_positive"
    assert outcome.caller_status == CALLER_REJECTED


def test_cancelled_work_is_isolated() -> None:
    from concurrent.futures import CancelledError

    def cancelled() -> object:
        raise CancelledError()

    outcome = run_shadow_bounded(cancelled, budget_seconds=BUDGET)
    assert outcome.status == SHADOW_ERROR
    assert outcome.caller_status == CALLER_CANCELLED
    assert outcome.reason == "isolated:cancelled"


# ------------------------------------------- process signals are not swallowed

def test_keyboard_interrupt_is_not_swallowed_as_a_shadow_error() -> None:
    """Business failure isolation is not the same as masking process control."""

    def interrupt() -> object:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_shadow_bounded(interrupt, budget_seconds=BUDGET)


def test_system_exit_is_not_swallowed_as_a_shadow_error() -> None:
    def exit_now() -> object:
        raise SystemExit(3)

    with pytest.raises(SystemExit):
        run_shadow_bounded(exit_now, budget_seconds=BUDGET)


# ------------------------------------------------------- resource boundedness

def test_worker_count_stays_bounded_under_repeated_stalls() -> None:
    release = threading.Event()

    def stall() -> object:
        release.wait(timeout=5)
        return None

    for _ in range(12):
        run_shadow_bounded(stall, budget_seconds=0.02)

    state = shadow_resource_state()
    assert state["live_threads"] <= SHADOW_WORKERS, state
    release.set()


def test_saturation_is_rejected_promptly_instead_of_queueing() -> None:
    held = [iso._capacity.acquire(blocking=False) for _ in range(SHADOW_CAPACITY)]
    assert all(held)
    try:
        started = time.monotonic()
        outcome = run_shadow_bounded(lambda: "queued?", budget_seconds=1.0)
        elapsed = time.monotonic() - started
        assert outcome.status == SHADOW_UNAVAILABLE
        assert outcome.reason == "capacity_exhausted"
        assert outcome.caller_status == CALLER_REJECTED
        assert elapsed < 0.2, elapsed
    finally:
        for _ in held:
            iso._capacity.release()


def test_capacity_is_released_after_each_call() -> None:
    before = shadow_resource_state()["capacity_available"]
    run_shadow_bounded(lambda: "x", budget_seconds=BUDGET)
    assert shadow_resource_state()["capacity_available"] == before


def test_default_budget_is_a_named_constant_not_a_tuned_parameter() -> None:
    assert isinstance(DEFAULT_SHADOW_BUDGET_SECONDS, float)
    assert 0 < DEFAULT_SHADOW_BUDGET_SECONDS <= 1.0


# --------------------------------------------------------- bounded telemetry

def test_slow_telemetry_does_not_block_the_caller() -> None:
    telemetry = BestEffortTelemetry(LearnerStateParityCollector())
    started = time.monotonic()
    outcome = run_shadow_bounded(
        lambda: "observation", budget_seconds=BUDGET,
        on_telemetry=lambda value: telemetry.record(value),
    )
    elapsed = time.monotonic() - started
    assert outcome.status == SHADOW_OK
    assert elapsed < 0.5, elapsed
    assert telemetry.flush(timeout=1.0) is True
    telemetry.close()


def test_telemetry_saturation_drops_instead_of_growing_a_backlog() -> None:
    class StalledSink:
        def __init__(self) -> None:
            self.release = threading.Event()

        def record(self, observation: object) -> None:
            self.release.wait(timeout=2)

    sink = StalledSink()
    telemetry = BestEffortTelemetry(sink, capacity=4)
    for index in range(50):
        telemetry.record(index)

    assert telemetry.pending <= 4
    assert telemetry.dropped >= 40
    sink.release.set()
    telemetry.close()


def test_telemetry_failure_is_counted_not_raised() -> None:
    class BrokenSink:
        def record(self, observation: object) -> None:
            raise RuntimeError("collector is down")

    telemetry = BestEffortTelemetry(BrokenSink())
    telemetry.record({"turn_id": "t1"})
    assert telemetry.flush(timeout=1.0) is True
    assert telemetry.recorded == 0
    assert telemetry.dropped == 1
    telemetry.close()


def test_missing_sink_is_a_legal_drop() -> None:
    """chat turn success + parity artifact missing is a legal state."""
    telemetry = BestEffortTelemetry(None)
    telemetry.record("observation")
    assert telemetry.flush(timeout=1.0) is True
    assert telemetry.recorded == 0
    assert telemetry.dropped == 1
    telemetry.close()


def test_closed_telemetry_drops_without_raising() -> None:
    telemetry = BestEffortTelemetry(LearnerStateParityCollector())
    telemetry.close()
    telemetry.record("late")
    assert telemetry.dropped == 1


# ------------------------------------------------------ caller always resumes

@pytest.mark.parametrize("scenario", ["normal", "throws", "stalls", "rejected"])
def test_production_path_always_continues(scenario: str) -> None:
    release = threading.Event()

    def work() -> object:
        if scenario == "normal":
            return "ok"
        if scenario == "throws":
            raise ValueError("boom")
        release.wait(timeout=5)
        return "late"

    budget = 0.0 if scenario == "rejected" else BUDGET
    outcome = run_shadow_bounded(work, budget_seconds=budget)
    assert isinstance(outcome, ShadowOutcome)
    if scenario == "normal":
        assert outcome.status == SHADOW_OK
    elif scenario == "stalls":
        assert outcome.status == SHADOW_UNAVAILABLE
    else:
        assert outcome.status in (SHADOW_ERROR, SHADOW_UNAVAILABLE)
    release.set()
