"""§164-C1b-0: the shadow read must be bounded in workers, queue and telemetry."""

from __future__ import annotations

import threading
import time

from concurrent.futures import CancelledError

import pytest

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
    outcome = run_shadow_bounded(
        lambda: (_ for _ in ()).throw(CancelledError()), budget_seconds=BUDGET
    )
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

def test_admission_is_bound_to_the_future_not_the_caller() -> None:
    """Two stuck workers must block new admissions; caller return must not free them."""
    started = threading.Event()
    release = threading.Event()

    def stall() -> object:
        started.set()
        release.wait(timeout=5)
        return None

    # Occupy every worker, and let each caller time out while the worker runs on.
    run_shadow_bounded(stall, budget_seconds=0.02)
    assert started.wait(timeout=1.0)
    run_shadow_bounded(stall, budget_seconds=0.02)
    started.clear()

    state = shadow_resource_state()
    assert state["outstanding_work"] == SHADOW_CAPACITY, state
    assert state["capacity_available"] == 0

    outcomes = [run_shadow_bounded(lambda: "x", budget_seconds=0.05) for _ in range(100)]
    assert all(item.reason == "capacity_exhausted" for item in outcomes)
    assert shadow_resource_state()["outstanding_work"] == SHADOW_CAPACITY
    release.set()


def test_caller_timeout_does_not_release_running_capacity() -> None:
    release = threading.Event()

    def stall() -> object:
        release.wait(timeout=5)
        return None

    before = shadow_resource_state()["capacity_available"]
    outcome = run_shadow_bounded(stall, budget_seconds=0.02)
    assert outcome.caller_status == CALLER_TIMED_OUT
    # The worker is still running, so the token is still held.
    assert shadow_resource_state()["capacity_available"] == before - 1
    release.set()


def test_capacity_is_restored_when_the_worker_actually_finishes() -> None:
    release = threading.Event()

    def stall() -> object:
        release.wait(timeout=5)
        return "done"

    run_shadow_bounded(stall, budget_seconds=0.02)
    assert shadow_resource_state()["capacity_available"] < SHADOW_CAPACITY

    release.set()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if shadow_resource_state()["capacity_available"] == SHADOW_CAPACITY:
            break
        time.sleep(0.01)
    assert shadow_resource_state()["capacity_available"] == SHADOW_CAPACITY
    assert run_shadow_bounded(lambda: "x", budget_seconds=0.2).status == SHADOW_OK


def test_token_is_released_exactly_once() -> None:
    """No double release: capacity must never exceed its total."""
    for _ in range(20):
        run_shadow_bounded(lambda: "x", budget_seconds=0.2)
        run_shadow_bounded(_raiser, budget_seconds=0.2)
        run_shadow_bounded(lambda: (_ for _ in ()).throw(CancelledError()), budget_seconds=0.2)
        state = shadow_resource_state()
        assert state["capacity_available"] <= state["capacity_total"]
    assert shadow_resource_state()["capacity_available"] == SHADOW_CAPACITY


def _raiser() -> object:
    raise RuntimeError("boom")


def test_no_intentional_backlog_by_construction() -> None:
    state = shadow_resource_state()
    assert state["intentional_backlog"] == 0
    assert state["max_workers"] == SHADOW_CAPACITY


def test_runtime_limitation_is_machine_visible() -> None:
    """The outer budget bounds caller latency, not worker termination."""
    limitation = shadow_resource_state()["known_runtime_limitation"]
    assert "survive caller timeout" in limitation
    assert "not worker termination" in limitation


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
