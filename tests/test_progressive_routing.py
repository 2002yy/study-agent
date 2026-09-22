"""§99 P2-A2b progressive routing authority tests.

The authority answers one question - what does this candidate do next - and these
tests pin the matrix, the capability contract and the single-decision rule.
"""

from __future__ import annotations

import pytest

from src.web.research.progressive_routing import (
    ACTION_BLOCK_RUN,
    ACTION_DEFER,
    ACTION_EXHAUST,
    ACTION_RESOLVE,
    ACTION_TRY_BACKEND,
    CAP_ANTI_BOT_RECOVERY,
    CAP_CONTENT_EXTRACTION,
    CAP_JS_RENDER,
    CAP_SESSION,
    DEFAULT_BACKENDS,
    REASON_ALL_TRIED,
    REASON_NO_CAPABLE,
    REASON_SESSION_NEEDED,
    REASON_UNSUPPORTED_CONTENT,
    ROUTING_ACTIONS,
    BackendCapability,
    RoutingContext,
    assert_no_authority_fields,
    capability_registry,
    route,
)
from src.web.research.retrieval_backends import FORBIDDEN_AUTHORITY_FIELDS

CHAIN = ("native_http", "wigolo_http", "wigolo_browser")


def _context(state: str, **overrides: object) -> RoutingContext:
    params: dict[str, object] = {
        "candidate_id": "c1",
        "current_backend": "native_http",
        "retrieval_state": state,
        "attempted_backends": ("native_http",),
        "available_backends": CHAIN,
    }
    params.update(overrides)
    return RoutingContext(**params)  # type: ignore[arg-type]


# --------------------------------------------------------------- settled


def test_success_resolves_with_usable_content() -> None:
    decision = route(_context("success"))
    assert decision.action == ACTION_RESOLVE
    assert decision.terminal is True
    assert decision.usable_content is True


def test_not_found_is_terminal_without_usable_content() -> None:
    """A 404 is a terminal resource outcome, not a successful read."""

    decision = route(_context("not_found"))
    assert decision.action == ACTION_RESOLVE
    assert decision.terminal is True
    assert decision.usable_content is False


def test_a_terminal_outcome_never_routes_onwards() -> None:
    for state in ("success", "not_found"):
        decision = route(_context(state))
        assert decision.next_backend == ""
        assert decision.action != ACTION_TRY_BACKEND


# --------------------------------------------------------------- transport


@pytest.mark.parametrize(
    "state", ["reset", "connect_failure", "dns_failure", "tls_failure", "timeout", "backend_failure"]
)
def test_transport_failure_routes_to_an_alternate(state: str) -> None:
    decision = route(_context(state))
    assert decision.action == ACTION_TRY_BACKEND
    assert decision.next_backend in CHAIN
    assert decision.next_backend != "native_http"


def test_an_attempted_backend_is_never_selected_again() -> None:
    decision = route(
        _context("reset", attempted_backends=("native_http", "wigolo_http"))
    )
    assert decision.next_backend == "wigolo_browser"


# --------------------------------------------------------------- capability routing


@pytest.mark.parametrize("state", ["shell_page", "js_required"])
def test_shell_states_require_a_rendered_backend(state: str) -> None:
    decision = route(_context(state))
    assert decision.action == ACTION_TRY_BACKEND
    assert CAP_JS_RENDER in decision.required_capabilities
    registry = capability_registry()
    assert registry[decision.next_backend].supports(decision.required_capabilities)


def test_a_plain_http_backend_is_not_offered_for_a_shell() -> None:
    """Only a rendered backend may take a JS shell."""

    decision = route(
        _context(
            "shell_page",
            available_backends=("native_http", "plain_only"),
            attempted_backends=("native_http",),
        ),
        backends=(
            *DEFAULT_BACKENDS,
            BackendCapability(name="plain_only", capabilities=frozenset({"plain_http"})),
        ),
    )
    assert decision.action == ACTION_EXHAUST
    assert decision.reason == REASON_NO_CAPABLE


def test_anti_bot_requires_anti_bot_recovery() -> None:
    decision = route(_context("anti_bot"))
    assert CAP_ANTI_BOT_RECOVERY in decision.required_capabilities
    assert decision.next_backend == "wigolo_browser"


def test_login_required_only_routes_to_a_session_capable_backend() -> None:
    """Ordinary HTTP readers must not be thrown at a login wall."""

    decision = route(_context("login_required"))
    assert decision.reason == REASON_SESSION_NEEDED
    assert decision.next_backend == "wigolo_browser"
    assert CAP_SESSION in decision.required_capabilities

    # With only plain-HTTP alternates available there is nothing to try.
    exhausted = route(
        _context("login_required", available_backends=("native_http", "wigolo_http"))
    )
    assert exhausted.action == ACTION_EXHAUST
    assert exhausted.next_backend == ""


# --------------------------------------------------------------- explicit policies


@pytest.mark.parametrize("state", ["http_denied", "rate_limited"])
def test_access_denied_and_rate_limited_may_try_an_alternate(state: str) -> None:
    """A denial is about this path, not about the resource being unreadable."""

    decision = route(_context(state))
    assert decision.action == ACTION_TRY_BACKEND
    assert decision.next_backend != "native_http"


def test_rate_limited_does_not_touch_health_by_itself() -> None:
    """Health accounting stays with the breaker; routing only picks a backend."""

    decision = route(_context("rate_limited"))
    assert decision.action == ACTION_TRY_BACKEND
    assert decision.to_dict()["reason"] == "rate_limited_alternate"


# ------------------------------------------------------- invalid_content refinement


def test_invalid_content_short_doc_wants_extraction() -> None:
    decision = route(_context("invalid_content", adequacy_reason="short_doc"))
    assert decision.action == ACTION_TRY_BACKEND
    assert decision.required_capabilities == frozenset({CAP_CONTENT_EXTRACTION})
    assert decision.next_backend == "wigolo_http"


def test_invalid_content_js_shell_wants_rendering() -> None:
    decision = route(_context("invalid_content", adequacy_reason="js_shell"))
    assert decision.required_capabilities == frozenset({CAP_JS_RENDER})
    assert decision.next_backend in ("wigolo_http", "wigolo_browser")


def test_invalid_content_anti_bot_wants_anti_bot_recovery() -> None:
    decision = route(_context("invalid_content", adequacy_reason="anti_bot_or_error"))
    assert decision.required_capabilities == frozenset({CAP_ANTI_BOT_RECOVERY})
    assert decision.next_backend == "wigolo_browser"


def test_malformed_binary_is_unrecoverable() -> None:
    decision = route(_context("invalid_content", adequacy_reason="malformed_binary"))
    assert decision.action == ACTION_EXHAUST
    assert decision.reason == REASON_UNSUPPORTED_CONTENT
    assert decision.terminal is True


def test_the_same_state_routes_differently_by_adequacy_reason() -> None:
    """``invalid_content`` alone is too coarse - the reason decides."""

    actions = {
        reason: route(
            _context("invalid_content", adequacy_reason=reason)
        ).next_backend
        for reason in ("short_doc", "js_shell", "anti_bot_or_error")
    }
    assert actions["short_doc"] != actions["anti_bot_or_error"]


# --------------------------------------------------------------- policy skip


def test_a_circuit_skip_skips_the_backend_but_keeps_the_candidate() -> None:
    decision = route(
        _context(
            "backend_failure",
            attempted=False,
            attempted_backends=(),
            current_backend="native_http",
        )
    )
    assert decision.action == ACTION_TRY_BACKEND
    assert decision.next_backend != "native_http"
    assert decision.terminal is False


def test_budget_exhausted_blocks_the_run() -> None:
    decision = route(_context("budget_exhausted"))
    assert decision.action == ACTION_BLOCK_RUN
    assert decision.terminal is False
    assert decision.usable_content is False


# --------------------------------------------------------------- exhaustion / deferral


def test_all_backends_tried_exhausts_the_chain() -> None:
    decision = route(
        _context("reset", attempted_backends=CHAIN)
    )
    assert decision.action == ACTION_EXHAUST
    assert decision.reason == REASON_ALL_TRIED
    assert decision.terminal is True


def test_an_unhealthy_alternate_defers_instead_of_exhausting() -> None:
    decision = route(
        _context("reset", host="x.example"),
        health_state_for=lambda backend, host: "open",
    )
    assert decision.action == ACTION_DEFER
    assert decision.terminal is False


def test_a_half_open_alternate_is_still_usable() -> None:
    decision = route(
        _context("reset", host="x.example"),
        health_state_for=lambda backend, host: "half_open",
    )
    assert decision.action == ACTION_TRY_BACKEND
    assert decision.next_backend == "wigolo_http"


def test_health_is_only_consulted_for_untried_capable_backends() -> None:
    seen: list[str] = []

    def health(backend: str, host: str) -> str:
        seen.append(backend)
        return "closed"

    route(_context("shell_page", host="x.example"), health_state_for=health)
    assert "native_http" not in seen  # already tried
    assert set(seen) <= {"wigolo_http", "wigolo_browser"}


# --------------------------------------------------------------- single decision


def test_every_decision_is_exactly_one_action() -> None:
    states = (
        "success",
        "not_found",
        "reset",
        "timeout",
        "shell_page",
        "js_required",
        "anti_bot",
        "login_required",
        "http_denied",
        "rate_limited",
        "invalid_content",
        "budget_exhausted",
        "backend_failure",
    )
    for state in states:
        decision = route(_context(state))
        assert decision.action in ROUTING_ACTIONS
        if decision.action == ACTION_TRY_BACKEND:
            assert decision.next_backend
        else:
            assert decision.next_backend == ""


def test_the_decision_is_pure_and_repeatable() -> None:
    first = route(_context("shell_page")).to_dict()
    second = route(_context("shell_page")).to_dict()
    assert first == second


# --------------------------------------------------------------- capabilities


def test_backends_declare_capabilities_rather_than_names() -> None:
    registry = capability_registry()
    assert registry["native_http"].capabilities == frozenset(
        {"plain_http", "content_extraction"}
    )
    assert CAP_JS_RENDER in registry["wigolo_http"].capabilities
    assert CAP_SESSION in registry["wigolo_browser"].capabilities


def test_a_new_backend_can_be_added_without_touching_the_matrix() -> None:
    """A3's browser backend plugs in by declaration alone."""

    decision = route(
        _context("shell_page", available_backends=("native_http", "future_browser")),
        backends=(
            BackendCapability(name="native_http", capabilities=frozenset({"plain_http"})),
            BackendCapability(
                name="future_browser", capabilities=frozenset({CAP_JS_RENDER})
            ),
        ),
    )
    assert decision.action == ACTION_TRY_BACKEND
    assert decision.next_backend == "future_browser"


# --------------------------------------------------------------- no authority


def test_routing_payload_carries_no_authority() -> None:
    payload = route(_context("success")).to_dict()
    assert not set(payload).intersection(FORBIDDEN_AUTHORITY_FIELDS)
    assert_no_authority_fields(payload)
    with pytest.raises(ValueError):
        assert_no_authority_fields({**payload, "evidence": "x"})


def test_routing_context_payload_is_serialisable() -> None:
    payload = _context("reset").to_dict()
    assert payload["current_backend"] == "native_http"
    assert payload["attempted_backends"] == ["native_http"]
