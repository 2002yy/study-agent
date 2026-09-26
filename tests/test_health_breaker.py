"""§96 P2-A1a per-run health breaker and deadline preflight tests.

These pin the state machine, the accounting rules and the cross-key isolation
that A2 Progressive Reader will depend on.
"""

from __future__ import annotations

import pytest

from src.web.research.failure_taxonomy import (
    SKIP_REASON_CIRCUIT_OPEN,
    SKIP_REASON_INSUFFICIENT_WINDOW,
    BackendHealthPolicy,
)
from src.web.research.health_breaker import (
    NATIVE_HTTP_BACKEND,
    STATE_CLOSED,
    STATE_COOLDOWN,
    STATE_HALF_OPEN,
    STATE_OPEN,
    WILDCARD_HOST,
    PerRunBreaker,
    breaker_policy_from_env,
    deadline_preflight,
    host_of,
    read_breaker_enabled,
)


class Clock:
    """Controllable monotonic clock in milliseconds."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds) * 1000.0


def _breaker(
    *, threshold: int = 3, open_seconds: float = 30.0, cooldown_seconds: float = 5.0
) -> tuple[PerRunBreaker, Clock]:
    clock = Clock()
    policy = BackendHealthPolicy(
        failure_threshold=threshold,
        open_seconds=open_seconds,
        half_open_probes=1,
        cooldown_seconds=cooldown_seconds,
    )
    return PerRunBreaker(policy=policy, now_ms=clock), clock


def _fail(breaker: PerRunBreaker, *, host: str = "bad.example", times: int = 1) -> None:
    for _ in range(times):
        breaker.record(
            backend=NATIVE_HTTP_BACKEND, host=host, state="reset", attempted=True
        )


# ------------------------------------------------------------ closed -> open


def test_threshold_failures_open_the_breaker() -> None:
    breaker, _clock = _breaker(threshold=3)
    assert breaker.state_for(backend=NATIVE_HTTP_BACKEND, host="bad.example") == (
        STATE_CLOSED
    )
    _fail(breaker, times=2)
    assert breaker.state_for(backend=NATIVE_HTTP_BACKEND, host="bad.example") == (
        STATE_CLOSED
    )
    _fail(breaker, times=1)
    assert breaker.state_for(backend=NATIVE_HTTP_BACKEND, host="bad.example") == (
        STATE_OPEN
    )


def test_an_open_breaker_refuses_with_a_policy_skip() -> None:
    breaker, _clock = _breaker(threshold=2)
    _fail(breaker, times=2)
    decision = breaker.allow(backend=NATIVE_HTTP_BACKEND, host="bad.example")
    assert decision.allowed is False
    assert decision.attempted is False
    assert decision.skip_reason == SKIP_REASON_CIRCUIT_OPEN
    assert decision.state_after == STATE_OPEN
    # Provenance can explain why this request was not sent.
    policy = decision.to_policy_dict()
    assert policy["health_key"] == "native_http::bad.example"
    assert policy["breaker_state"] == STATE_OPEN
    assert policy["breaker_state_before"] == STATE_OPEN
    assert policy["failure_streak"] == 2
    assert policy["eligible_probe_at_ms"] is not None


def test_a_skip_never_increases_the_failure_streak() -> None:
    breaker, _clock = _breaker(threshold=2)
    _fail(breaker, times=2)
    before = breaker.allow(backend=NATIVE_HTTP_BACKEND, host="bad.example")
    breaker.record(
        backend=NATIVE_HTTP_BACKEND, host="bad.example", state="backend_failure",
        attempted=False,
    )
    after = breaker.allow(backend=NATIVE_HTTP_BACKEND, host="bad.example")
    assert after.failure_streak == before.failure_streak == 2


def test_open_before_the_window_elapses_keeps_skipping() -> None:
    breaker, clock = _breaker(threshold=1, open_seconds=30.0)
    _fail(breaker, times=1)
    clock.advance(29.0)
    decision = breaker.allow(backend=NATIVE_HTTP_BACKEND, host="bad.example")
    assert decision.allowed is False
    assert decision.state_after == STATE_OPEN


def test_open_after_the_window_elapses_becomes_half_open() -> None:
    breaker, clock = _breaker(threshold=1, open_seconds=30.0)
    _fail(breaker, times=1)
    clock.advance(30.0)
    decision = breaker.allow(backend=NATIVE_HTTP_BACKEND, host="bad.example")
    assert decision.allowed is True
    assert decision.state_before == STATE_HALF_OPEN
    assert decision.is_probe is True
    assert decision.probe_index == 1


def test_half_open_allows_only_the_configured_probe_count() -> None:
    breaker, clock = _breaker(threshold=1, open_seconds=1.0)
    _fail(breaker, times=1)
    clock.advance(1.0)
    first = breaker.allow(backend=NATIVE_HTTP_BACKEND, host="bad.example")
    second = breaker.allow(backend=NATIVE_HTTP_BACKEND, host="bad.example")
    assert first.allowed is True and first.is_probe is True
    assert second.allowed is False
    assert second.skip_reason == SKIP_REASON_CIRCUIT_OPEN


# ------------------------------------------------- half_open outcomes


def test_probe_success_closes_and_resets() -> None:
    breaker, clock = _breaker(threshold=1, open_seconds=1.0)
    _fail(breaker, times=1)
    clock.advance(1.0)
    breaker.allow(backend=NATIVE_HTTP_BACKEND, host="bad.example")
    decision = breaker.record(
        backend=NATIVE_HTTP_BACKEND, host="bad.example",
        state="success", attempted=True,
    )
    assert decision.state_before == STATE_HALF_OPEN
    assert decision.state_after == STATE_CLOSED
    assert decision.failure_streak == 0
    assert breaker.allow(backend=NATIVE_HTTP_BACKEND, host="bad.example").allowed is True


def test_probe_failure_enters_cooldown() -> None:
    breaker, clock = _breaker(threshold=1, open_seconds=1.0, cooldown_seconds=5.0)
    _fail(breaker, times=1)
    clock.advance(1.0)
    breaker.allow(backend=NATIVE_HTTP_BACKEND, host="bad.example")
    decision = breaker.record(
        backend=NATIVE_HTTP_BACKEND, host="bad.example",
        state="timeout", attempted=True,
    )
    assert decision.state_before == STATE_HALF_OPEN
    assert decision.state_after == STATE_COOLDOWN
    assert decision.eligible_probe_at_ms is not None


def test_cooldown_before_it_ends_keeps_skipping() -> None:
    breaker, clock = _breaker(threshold=1, open_seconds=1.0, cooldown_seconds=5.0)
    _fail(breaker, times=1)
    clock.advance(1.0)
    breaker.allow(backend=NATIVE_HTTP_BACKEND, host="bad.example")
    breaker.record(
        backend=NATIVE_HTTP_BACKEND, host="bad.example",
        state="connect_failure", attempted=True,
    )
    clock.advance(4.0)
    decision = breaker.allow(backend=NATIVE_HTTP_BACKEND, host="bad.example")
    assert decision.allowed is False
    assert decision.state_after == STATE_COOLDOWN
    assert decision.skip_reason == SKIP_REASON_CIRCUIT_OPEN


def test_cooldown_expiry_allows_another_probe() -> None:
    breaker, clock = _breaker(threshold=1, open_seconds=1.0, cooldown_seconds=5.0)
    _fail(breaker, times=1)
    clock.advance(1.0)
    breaker.allow(backend=NATIVE_HTTP_BACKEND, host="bad.example")
    breaker.record(
        backend=NATIVE_HTTP_BACKEND, host="bad.example",
        state="connect_failure", attempted=True,
    )
    clock.advance(5.0)
    decision = breaker.allow(backend=NATIVE_HTTP_BACKEND, host="bad.example")
    assert decision.allowed is True
    assert decision.state_before == STATE_HALF_OPEN
    assert decision.is_probe is True
    assert decision.probe_index == 2


# --------------------------------------------------------- accounting rules


def test_a_policy_skip_never_counts_as_a_health_failure() -> None:
    breaker, _clock = _breaker(threshold=1)
    breaker.record(
        backend=NATIVE_HTTP_BACKEND, host="bad.example",
        state="backend_failure", attempted=False,
    )
    assert breaker.state_for(backend=NATIVE_HTTP_BACKEND, host="bad.example") == (
        STATE_CLOSED
    )


def test_budget_exhausted_does_not_imply_an_unhealthy_host() -> None:
    breaker, _clock = _breaker(threshold=1)
    breaker.record(
        backend=NATIVE_HTTP_BACKEND, host="slow.example",
        state="budget_exhausted", attempted=True,
    )
    assert breaker.state_for(backend=NATIVE_HTTP_BACKEND, host="slow.example") == (
        STATE_CLOSED
    )


def test_url_truth_does_not_trip_the_breaker() -> None:
    breaker, _clock = _breaker(threshold=1)
    for state in ("not_found", "http_denied", "invalid_content", "shell_page"):
        breaker.record(
            backend=NATIVE_HTTP_BACKEND, host="content.example",
            state=state, attempted=True,
        )
    assert breaker.state_for(backend=NATIVE_HTTP_BACKEND, host="content.example") == (
        STATE_CLOSED
    )


def test_a_healthy_observation_resets_the_streak() -> None:
    breaker, _clock = _breaker(threshold=3)
    _fail(breaker, times=2)
    breaker.record(
        backend=NATIVE_HTTP_BACKEND, host="bad.example",
        state="success", attempted=True,
    )
    assert breaker.allow(backend=NATIVE_HTTP_BACKEND, host="bad.example").failure_streak == 0


def test_deadline_skip_is_not_a_breaker_failure() -> None:
    """A window refusal is a policy skip and must not feed health."""

    breaker, _clock = _breaker(threshold=1)
    decision = deadline_preflight(
        remaining_seconds=2.0, timeout_seconds=12.0, reserve_seconds=5.0
    )
    assert decision.allowed is False
    assert decision.skip_reason == SKIP_REASON_INSUFFICIENT_WINDOW
    breaker.record(
        backend=NATIVE_HTTP_BACKEND, host="any.example",
        state="budget_exhausted", attempted=False,
    )
    assert breaker.state_for(backend=NATIVE_HTTP_BACKEND, host="any.example") == (
        STATE_CLOSED
    )


def test_deadline_preflight_allows_when_the_window_fits() -> None:
    allowed = deadline_preflight(
        remaining_seconds=20.0, timeout_seconds=12.0, reserve_seconds=5.0
    )
    assert allowed.allowed is True
    assert allowed.skip_reason == ""
    refused = deadline_preflight(
        remaining_seconds=16.0, timeout_seconds=12.0, reserve_seconds=5.0
    )
    assert refused.allowed is False


# ------------------------------------------------------------ cross-key isolation


def test_a_different_backend_for_the_same_host_is_unaffected() -> None:
    """native HTTP being sick says nothing about the browser backend."""

    breaker, _clock = _breaker(threshold=1)
    _fail(breaker, times=1)
    assert breaker.state_for(backend=NATIVE_HTTP_BACKEND, host="bad.example") == (
        STATE_OPEN
    )
    assert breaker.state_for(backend="browser", host="bad.example") == STATE_CLOSED
    assert breaker.allow(backend="browser", host="bad.example").allowed is True


def test_a_different_host_for_the_same_backend_is_unaffected() -> None:
    breaker, _clock = _breaker(threshold=1)
    _fail(breaker, times=1)
    assert breaker.allow(backend=NATIVE_HTTP_BACKEND, host="good.example").allowed is True
    assert breaker.state_for(backend=NATIVE_HTTP_BACKEND, host="good.example") == (
        STATE_CLOSED
    )


def test_health_keys_are_case_normalised() -> None:
    assert host_of("HTTPS://Example.COM/path?q=1") == "example.com"
    assert host_of("") == ""


# ------------------------------------------------------ legacy compatibility shell


def test_legacy_mark_open_uses_the_same_authority() -> None:
    """No second breaker state: the host-less mark lands in the same model."""

    breaker, _clock = _breaker(threshold=3)
    decision = breaker.mark_open(backend=NATIVE_HTTP_BACKEND)
    assert decision.legacy is True
    assert decision.health_key == f"{NATIVE_HTTP_BACKEND}::{WILDCARD_HOST}"
    # It refuses through the model, and it is visible as legacy.
    refused = breaker.allow(backend=NATIVE_HTTP_BACKEND, host="any.example")
    assert refused.allowed is False
    assert refused.skip_reason == SKIP_REASON_CIRCUIT_OPEN
    assert refused.legacy is True


def test_legacy_mark_with_a_host_stays_specific() -> None:
    breaker, _clock = _breaker(threshold=3)
    breaker.mark_open(backend=NATIVE_HTTP_BACKEND, host="only.example", legacy=False)
    assert breaker.allow(backend=NATIVE_HTTP_BACKEND, host="only.example").allowed is False
    assert breaker.allow(backend=NATIVE_HTTP_BACKEND, host="other.example").allowed is True


def test_legacy_mark_expires_into_half_open() -> None:
    breaker, clock = _breaker(threshold=3, open_seconds=10.0)
    breaker.mark_open(backend=NATIVE_HTTP_BACKEND)
    clock.advance(10.0)
    decision = breaker.allow(backend=NATIVE_HTTP_BACKEND, host="any.example")
    assert decision.allowed is True
    assert decision.is_probe is True


# --------------------------------------------------------------------- snapshot


def test_snapshot_exposes_bounded_provenance() -> None:
    breaker, _clock = _breaker(threshold=1)
    _fail(breaker, times=1)
    snapshot = breaker.snapshot()
    assert len(snapshot) == 1
    record = snapshot[0]
    assert record["health_key"] == "native_http::bad.example"
    assert record["state"] == STATE_OPEN
    assert record["failure_streak"] == 1
    assert record["transitions"]
    assert record["transitions"][-1]["transition"] == "failures_reached_threshold"


def test_switch_defaults_off_and_policy_comes_from_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RESEARCH_READ_BREAKER", raising=False)
    assert read_breaker_enabled() is False
    monkeypatch.setenv("RESEARCH_READ_BREAKER", "on")
    assert read_breaker_enabled() is True

    monkeypatch.delenv("RESEARCH_BREAKER_FAILURE_THRESHOLD", raising=False)
    default_policy = breaker_policy_from_env()
    assert default_policy.failure_threshold == BackendHealthPolicy().failure_threshold
    monkeypatch.setenv("RESEARCH_BREAKER_FAILURE_THRESHOLD", "1")
    monkeypatch.setenv("RESEARCH_BREAKER_OPEN_SECONDS", "0.5")
    harness_policy = breaker_policy_from_env()
    assert harness_policy.failure_threshold == 1
    assert harness_policy.open_seconds == 0.5
