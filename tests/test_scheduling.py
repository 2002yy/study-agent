"""§100 P2-A2c health-aware scheduling tests.

Scheduling answers "which backend may run now" before any attempt exists. These
tests pin that it is a separate phase from post-outcome routing, that it shares
the eligibility primitive with it, and that a scheduling decision is never a read
outcome.
"""

from __future__ import annotations

import pytest

from src.web.research.progressive_routing import (
    ACTION_BLOCK_RUN,
    ACTION_DEFER,
    ACTION_EXHAUST,
    ACTION_SCHEDULE,
    ACTION_TRY_BACKEND,
    CAP_JS_RENDER,
    CAP_SESSION,
    REASON_NO_ELIGIBLE,
    SCHEDULING_ACTIONS,
    BackendAvailability,
    EligibilityInputs,
    RoutingContext,
    SchedulingContext,
    assert_no_authority_fields,
    backend_eligibility,
    route,
    schedulable_now,
)
from src.web.research.retrieval_backends import FORBIDDEN_AUTHORITY_FIELDS

CHAIN = ("native_http", "wigolo_http", "wigolo_browser")


def _sched(**overrides: object) -> SchedulingContext:
    params: dict[str, object] = {
        "candidate_id": "c1",
        "available_backends": CHAIN,
        "attempted_backends": (),
        "host": "x.example",
    }
    params.update(overrides)
    return SchedulingContext(**params)  # type: ignore[arg-type]


def _closed(backend: str, host: str) -> str:
    return "closed"


# --------------------------------------------------------------- the happy path


def test_scheduling_picks_the_first_eligible_backend() -> None:
    decision = schedulable_now(_sched())
    assert decision.action == ACTION_SCHEDULE
    assert decision.backend == "native_http"
    assert decision.executable is True


def test_an_open_backend_is_skipped_without_a_breaker_skip_outcome() -> None:
    """The point of A2c: no meaningless native skip, go straight to the alternate."""

    decision = schedulable_now(
        _sched(attempted_backends=("native_http",)),
        health_state_for=(
            lambda backend, host: "open" if backend == "native_http" else "closed"
        ),
    )
    assert decision.action == ACTION_SCHEDULE
    assert decision.backend == "wigolo_http"
    verdict = next(
        item
        for item in decision.to_dict()["verdicts"]
        if item["backend"] == "native_http"
    )
    # The backend that already produced an outcome is not the next backend, and
    # its health is still reported for provenance.
    assert verdict["reason"] == "already_attempted"
    assert verdict["health_state"] == "open"


def test_an_open_untried_backend_is_reported_as_blocked() -> None:
    decision = schedulable_now(
        _sched(),
        health_state_for=(
            lambda backend, host: "open" if backend == "native_http" else "closed"
        ),
    )
    assert decision.action == ACTION_SCHEDULE
    assert decision.backend == "wigolo_http"
    assert decision.blocked_backends == ("native_http",)


def test_a_single_open_backend_defers_instead_of_exhausting() -> None:
    decision = schedulable_now(
        _sched(available_backends=("native_http",)),
        health_state_for=lambda backend, host: "open",
    )
    assert decision.action == ACTION_DEFER
    assert decision.blocked_backends == ("native_http",)
    assert decision.executable is False


def test_a_half_open_backend_may_be_scheduled() -> None:
    decision = schedulable_now(
        _sched(available_backends=("native_http",)),
        health_state_for=lambda backend, host: "half_open",
    )
    assert decision.action == ACTION_SCHEDULE
    assert decision.backend == "native_http"


# --------------------------------------------------------------- isolation


def test_backend_health_does_not_leak_across_backends() -> None:
    decision = schedulable_now(
        _sched(attempted_backends=("native_http",)),
        health_state_for=(
            lambda backend, host: "open" if backend == "native_http" else "closed"
        ),
    )
    assert decision.backend == "wigolo_http"


def test_host_health_does_not_leak_across_hosts() -> None:
    def health(backend: str, host: str) -> str:
        return "open" if host == "bad.example" else "closed"

    assert (
        schedulable_now(_sched(host="good.example"), health_state_for=health).action
        == ACTION_SCHEDULE
    )
    assert (
        schedulable_now(_sched(host="bad.example"), health_state_for=health).action
        == ACTION_DEFER
    )


# ------------------------------------------------- availability vs target health


def test_a_disabled_backend_is_never_scheduled_and_is_not_health() -> None:
    decision = schedulable_now(
        _sched(
            availability={
                "native_http": BackendAvailability(
                    backend="native_http", configured=False, reason="switch_off"
                )
            }
        )
    )
    assert decision.action == ACTION_SCHEDULE
    assert decision.backend == "wigolo_http"
    # A configuration switch is not a health block.
    assert "native_http" not in decision.blocked_backends


def test_an_unavailable_provider_does_not_pollute_target_health() -> None:
    """A daemon outage is provider availability, never target-host health."""

    def health(backend: str, host: str) -> str:
        return "closed"

    decision = schedulable_now(
        _sched(
            availability={
                "native_http": BackendAvailability(
                    backend="native_http", available=False, reason="daemon_down"
                )
            }
        ),
        health_state_for=health,
    )
    assert decision.backend == "wigolo_http"
    assert "native_http" in decision.blocked_backends
    verdict = next(
        item
        for item in decision.to_dict()["verdicts"]
        if item["backend"] == "native_http"
    )
    assert verdict["reason"] == "provider_unavailable"
    assert verdict["provider_available"] is False
    assert verdict["health_state"] == "closed"


def test_provider_unavailable_is_not_recorded_as_a_target_host_verdict() -> None:
    """The target was never contacted, so nothing may claim it is unhealthy."""

    decision = schedulable_now(
        _sched(
            availability={
                "native_http": BackendAvailability(
                    backend="native_http", available=False, reason="daemon_down"
                )
            }
        )
    )
    verdict = next(
        item
        for item in decision.to_dict()["verdicts"]
        if item["backend"] == "native_http"
    )
    assert verdict["health_state"] == ""
    assert verdict["reason"] != "target_health_open"


# --------------------------------------------------------------- eligibility


def test_an_attempted_backend_is_never_rescheduled() -> None:
    decision = schedulable_now(_sched(attempted_backends=CHAIN))
    assert decision.action == ACTION_EXHAUST
    assert decision.executable is False


def test_a_backend_without_the_required_capability_is_not_scheduled() -> None:
    decision = schedulable_now(_sched(required_capabilities=frozenset({CAP_SESSION})))
    assert decision.action == ACTION_SCHEDULE
    assert decision.backend == "wigolo_browser"


def test_no_eligible_backend_exhausts() -> None:
    decision = schedulable_now(_sched(required_capabilities=frozenset({"telepathy"})))
    assert decision.action == ACTION_EXHAUST
    assert decision.reason == REASON_NO_ELIGIBLE


def test_a_blocked_run_blocks_scheduling() -> None:
    decision = schedulable_now(_sched(run_blocked=True))
    assert decision.action == ACTION_BLOCK_RUN
    assert decision.executable is False


def test_eligibility_precedence_is_capability_then_attempt_then_availability() -> None:
    """One verdict per backend, with a documented reason precedence."""

    open_health = lambda backend, host: "open"  # noqa: E731

    incapable = backend_eligibility(
        EligibilityInputs(
            backend="native_http",
            required_capabilities=frozenset({CAP_JS_RENDER}),
            attempted_backends=("native_http",),
            host="x.example",
        ),
        health_state_for=open_health,
    )
    assert incapable.reason == "capability_not_satisfied"

    attempted = backend_eligibility(
        EligibilityInputs(
            backend="native_http",
            attempted_backends=("native_http",),
            host="x.example",
        ),
        health_state_for=open_health,
    )
    assert attempted.reason == "already_attempted"
    assert attempted.health_state == "open"  # still reported for provenance

    unavailable = backend_eligibility(
        EligibilityInputs(
            backend="wigolo_http",
            host="x.example",
            availability={
                "wigolo_http": BackendAvailability(
                    backend="wigolo_http", available=False, reason="daemon_down"
                )
            },
        )
    )
    assert unavailable.reason == "provider_unavailable"

    unhealthy = backend_eligibility(
        EligibilityInputs(backend="wigolo_http", host="x.example"),
        health_state_for=open_health,
    )
    assert unhealthy.reason == "target_health_open"

    assert (
        backend_eligibility(
            EligibilityInputs(backend="wigolo_http", host="x.example")
        ).eligible
        is True
    )


# ------------------------------------------------- shared primitive, separate phases


def test_scheduling_and_routing_share_the_eligibility_primitive() -> None:
    """Both phases must agree about what makes a backend usable."""

    verdict = backend_eligibility(
        EligibilityInputs(
            backend="wigolo_http",
            attempted_backends=("native_http",),
            current_backend="native_http",
            host="x.example",
        ),
        health_state_for=_closed,
    )
    scheduled = schedulable_now(
        _sched(attempted_backends=("native_http",)),
        health_state_for=_closed,
    )
    assert verdict.eligible is True
    assert scheduled.backend == "wigolo_http"

    routed = route(
        RoutingContext(
            candidate_id="c1",
            current_backend="native_http",
            retrieval_state="shell_page",
            attempted_backends=("native_http",),
            available_backends=CHAIN,
            host="x.example",
        ),
        health_state_for=_closed,
    )
    assert routed.action == ACTION_TRY_BACKEND
    # §111 A3-1R: a shell page needs js_render, which only the browser tier
    # really has; routing must not send it to the non-rendering http tier.
    assert routed.next_backend == "wigolo_browser"


def test_scheduling_is_a_different_phase_from_routing() -> None:
    """Pre-attempt has no outcome to interpret, and needs none."""

    decision = schedulable_now(_sched())
    payload = decision.to_dict()
    assert "retrieval_state" not in payload
    assert "adequacy_reason" not in payload
    assert set(payload) == {
        "candidate_id",
        "action",
        "backend",
        "reason",
        "considered_backends",
        "blocked_backends",
        "verdicts",
    }


# ------------------------------------------------- no outcome, no authority


def test_a_scheduling_decision_is_not_a_read_outcome() -> None:
    """defer / block_run / exhaust must never look like a read."""

    for decision in (
        schedulable_now(_sched(available_backends=())),
        schedulable_now(_sched(run_blocked=True)),
    ):
        payload = decision.to_dict()
        assert decision.executable is False
        assert "retrieval_state" not in payload
        assert "evidence" not in payload
        assert "status" not in payload


def test_scheduling_actions_are_a_closed_set() -> None:
    assert set(SCHEDULING_ACTIONS) == {
        ACTION_SCHEDULE,
        ACTION_DEFER,
        ACTION_BLOCK_RUN,
        ACTION_EXHAUST,
    }


def test_scheduling_payload_carries_no_authority() -> None:
    payload = schedulable_now(_sched()).to_dict()
    assert not set(payload).intersection(FORBIDDEN_AUTHORITY_FIELDS)
    assert_no_authority_fields(payload)
    with pytest.raises(ValueError):
        assert_no_authority_fields({**payload, "support": "x"})


def test_scheduling_is_pure_and_repeatable() -> None:
    first = schedulable_now(_sched()).to_dict()
    second = schedulable_now(_sched()).to_dict()
    assert first == second


def test_scheduling_does_not_mutate_its_context() -> None:
    context = _sched(attempted_backends=("native_http",))
    before = context.to_dict()
    schedulable_now(context, health_state_for=lambda backend, host: "open")
    assert context.to_dict() == before
