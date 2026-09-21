"""§94 P2-A0 retrieval outcome contract tests.

The contract exists so every backend can describe what happened in one
language. These tests pin the parts that must never drift: raw -> canonical
mapping, fail-closed behaviour for anything unrecognised, fidelity of the raw
provenance, the ``host health != URL truth`` invariant, and the absence of any
evidence authority in the taxonomy.
"""

from __future__ import annotations

import pytest

from src.web.research.failure_taxonomy import (
    BREAKER_STATES,
    CONTENT_JUDGEMENT_STATES,
    RETRIEVAL_STATES,
    SKIP_REASON_CIRCUIT_OPEN,
    SKIP_REASON_DISABLED,
    SKIP_REASON_INSUFFICIENT_WINDOW,
    SKIP_REASON_PREFLIGHT,
    SKIP_REASONS,
    SUCCESS_STATE,
    UNKNOWN_STATE,
    BackendHealthPolicy,
    RetrievalOutcome,
    assert_no_authority_fields,
    assert_no_url_truth_from_skip,
    assert_retrieval_outcome,
    classify,
    counts_towards_health,
    from_invocation_state,
    from_read_adequacy,
    health_key,
    is_success,
    state_for_status,
    state_for_text,
)
from src.web.research.retrieval_backends import (
    FORBIDDEN_AUTHORITY_FIELDS,
    RAW_READ_ARTIFACT_FIELDS,
    RawReadArtifact,
    RetrievalContractError,
    validate_backend_payload,
    validate_read_artifact,
)


# --------------------------------------------------------------- raw -> canonical


def test_first_batch_mappings_from_observed_failures() -> None:
    """The mappings frozen in §94.8, taken from failures F2 actually observed."""

    # WinError 10054 was the dominant docker failure signature in F2-O1/O3.
    assert (
        classify(
            backend="native_http",
            raw_state="read_failed",
            detail="URLError: <urlopen error [WinError 10054] reset>",
        ).state
        == "reset"
    )
    # The 403 signature observed on zhuanlan.zhihu.com in F2-O3.
    assert (
        classify(backend="native_http", detail="HTTPError: 403 Forbidden").state
        == "http_denied"
    )
    # §71C-3a adequacy shapes.
    assert from_read_adequacy("ok").state == SUCCESS_STATE
    assert from_read_adequacy("js_shell").state == "shell_page"
    assert from_read_adequacy("anti_bot_or_error").state == "anti_bot"
    assert from_read_adequacy("short_doc").state == "invalid_content"
    # B2 budget refusals are not URL observations.
    assert (
        classify(
            backend="wigolo_http",
            raw_state="run_envelope_exhausted",
            detail="run_envelope_exhausted",
        ).state
        == "budget_exhausted"
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (404, "not_found"),
        (410, "not_found"),
        (401, "http_denied"),
        (403, "http_denied"),
        (451, "http_denied"),
        (429, "rate_limited"),
        (500, "backend_failure"),
        (503, "backend_failure"),
        (400, "invalid_content"),
        (422, "invalid_content"),
    ],
)
def test_status_mapping(status: int, expected: str) -> None:
    assert state_for_status(status) == expected
    assert classify(backend="native_http", http_status=status).state == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("getaddrinfo failed", "dns_failure"),
        ("Name or service not known", "dns_failure"),
        ("SSLCertVerificationError", "tls_failure"),
        ("ssl handshake failed", "tls_failure"),
        ("connection reset by peer", "reset"),
        ("RemoteDisconnected", "reset"),
        ("read timed out", "timeout"),
        ("Connection refused", "connect_failure"),
        ("unusual traffic from your network", "anti_bot"),
        ("Please enable JavaScript", "shell_page"),
        ("login required", "login_required"),
        ("", ""),
        ("completely unrelated detail", ""),
    ],
)
def test_text_mapping(text: str, expected: str) -> None:
    assert state_for_text(text) == expected


def test_page_content_words_never_become_failure_claims() -> None:
    """``state_for_text`` is for error text; content is not an error signal."""

    # These markers only fire from error/detail text. A healthy read carries no
    # detail, so its shape decides - and the shape is ``ok``.
    outcome = from_read_adequacy("ok", backend="native_http")
    assert outcome.state == SUCCESS_STATE
    assert not outcome.is_policy_skip


# ------------------------------------------------------- fail closed, never success


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"raw_state": "wat"},
        {"raw_state": "read_failed"},
        {"detail": "something nobody has ever seen"},
        {"raw_state": "unsupported", "detail": "unknown_reason"},
        {"raw_state": "http_error"},
        {"adequacy_shape": "brand_new_shape"},
    ],
)
def test_unknown_failures_fail_closed_to_backend_failure(kwargs: dict) -> None:
    outcome = classify(backend="mystery_backend", **kwargs)
    assert outcome.state == UNKNOWN_STATE
    assert outcome.state != SUCCESS_STATE
    assert not outcome.is_success


def test_only_an_explicit_positive_signal_yields_success() -> None:
    """Success needs the reader to say ``ok``; nothing else may produce it."""

    assert from_read_adequacy("ok").state == SUCCESS_STATE
    for shape in ("read_failed", "js_shell", "anti_bot_or_error", "short_doc", ""):
        assert from_read_adequacy(shape).state != SUCCESS_STATE
    assert from_invocation_state("ok").state == SUCCESS_STATE
    for state in (
        "empty",
        "timeout",
        "http_error",
        "transport_error",
        "unsupported",
        "blocked",
        "aborted",
        "skipped_no_budget",
        "invalid_response",
        "",
    ):
        assert from_invocation_state(state).state != SUCCESS_STATE


# --------------------------------------------------------------- provenance fidelity


def test_raw_provenance_survives_classification() -> None:
    outcome = classify(
        backend="native_http",
        raw_state="transport_error",
        detail="URLError: <urlopen error [WinError 10054]>",
    )
    payload = outcome.to_dict()
    assert payload["retrieval_state"] == "reset"
    # The dialect is preserved, not overwritten.
    assert payload["raw_state"] == "transport_error"
    assert "10054" in payload["detail"]
    assert payload["backend"] == "native_http"
    assert payload["attempted"] is True
    assert payload["skip_reason"] == ""


def test_invocation_state_bridge_keeps_the_raw_state() -> None:
    outcome = from_invocation_state("http_error", backend="wigolo_http", detail="boom")
    assert outcome.state == UNKNOWN_STATE
    assert outcome.raw_state == "http_error"


def test_every_invocation_state_maps_into_the_canonical_set() -> None:
    for state in (
        "ok",
        "empty",
        "timeout",
        "http_error",
        "transport_error",
        "unsupported",
        "blocked",
        "aborted",
        "skipped_no_budget",
        "invalid_response",
    ):
        assert from_invocation_state(state).state in RETRIEVAL_STATES


# ----------------------------------------------------------- host health != URL truth


def test_circuit_skip_is_a_policy_outcome_not_a_url_judgement() -> None:
    outcome = classify(
        backend="wigolo_http",
        raw_state="unsupported",
        detail="circuit_open",
        skip_reason=SKIP_REASON_CIRCUIT_OPEN,
        breaker_state="open",
        attempted=False,
    )
    assert outcome.state == UNKNOWN_STATE
    assert outcome.skip_reason == SKIP_REASON_CIRCUIT_OPEN
    assert outcome.breaker_state == "open"
    assert outcome.attempted is False
    assert outcome.state not in CONTENT_JUDGEMENT_STATES


def test_existing_backend_circuit_skip_bridges_to_a_policy_skip() -> None:
    """The live §71C-3b shape (``unsupported`` + ``circuit_open``) is a skip."""

    outcome = from_invocation_state(
        "unsupported", backend="wigolo_http", detail="circuit_open"
    )
    assert outcome.attempted is False
    assert outcome.skip_reason == SKIP_REASON_CIRCUIT_OPEN
    assert outcome.breaker_state == "open"
    assert outcome.state not in CONTENT_JUDGEMENT_STATES


def test_preflight_failure_is_a_policy_skip() -> None:
    outcome = from_invocation_state(
        "unsupported", backend="wigolo_http", detail="preflight:backend_unavailable"
    )
    assert outcome.attempted is False
    assert outcome.skip_reason == SKIP_REASON_PREFLIGHT


def test_budget_skip_says_budget_not_url_truth() -> None:
    outcome = classify(
        backend="native_http",
        skip_reason=SKIP_REASON_INSUFFICIENT_WINDOW,
        attempted=False,
    )
    assert outcome.state == "budget_exhausted"
    assert outcome.state not in CONTENT_JUDGEMENT_STATES


def test_a_skip_can_never_claim_anything_about_the_url() -> None:
    for state in sorted(CONTENT_JUDGEMENT_STATES):
        with pytest.raises(RetrievalContractError):
            assert_no_url_truth_from_skip(
                RetrievalOutcome(state=state, attempted=False, skip_reason="circuit_open")
            )


def test_a_skip_must_be_a_policy_state() -> None:
    for state in ("success", "timeout", "reset", "connect_failure"):
        with pytest.raises(RetrievalContractError):
            assert_no_url_truth_from_skip(
                RetrievalOutcome(state=state, attempted=False, skip_reason="circuit_open")
            )


def test_a_skip_must_record_why() -> None:
    with pytest.raises(RetrievalContractError):
        assert_retrieval_outcome(RetrievalOutcome(state=UNKNOWN_STATE, attempted=False))
    with pytest.raises(RetrievalContractError):
        assert_retrieval_outcome(
            RetrievalOutcome(state=UNKNOWN_STATE, attempted=False, skip_reason="made_up")
        )


def test_circuit_skip_requires_an_open_breaker_state() -> None:
    with pytest.raises(RetrievalContractError):
        assert_retrieval_outcome(
            RetrievalOutcome(
                state=UNKNOWN_STATE,
                attempted=False,
                skip_reason=SKIP_REASON_CIRCUIT_OPEN,
                breaker_state="",
            )
        )
    for breaker_state in ("open", "half_open", "cooldown"):
        assert_retrieval_outcome(
            RetrievalOutcome(
                state=UNKNOWN_STATE,
                attempted=False,
                skip_reason=SKIP_REASON_CIRCUIT_OPEN,
                breaker_state=breaker_state,
            )
        )


def test_an_attempted_outcome_carries_no_skip_reason() -> None:
    with pytest.raises(RetrievalContractError):
        assert_retrieval_outcome(
            RetrievalOutcome(state="reset", attempted=True, skip_reason="circuit_open")
        )


def test_content_judgements_never_count_towards_backend_health() -> None:
    """A 404 says the page is gone, not that the backend is sick."""

    for state in CONTENT_JUDGEMENT_STATES:
        assert counts_towards_health(state) is False
    for state in ("connect_failure", "dns_failure", "tls_failure", "timeout", "reset"):
        assert counts_towards_health(state) is True


def test_a_policy_skip_never_counts_towards_backend_health() -> None:
    """Health counting follows ``attempted``, not the state name.

    ``backend_failure`` is both a genuine backend-sick state and the state a
    circuit-open skip carries. Only the attempted one may feed a breaker, or one
    breaker would feed the next.
    """

    assert counts_towards_health("backend_failure") is True
    assert counts_towards_health("backend_failure", attempted=False) is False
    assert counts_towards_health("budget_exhausted", attempted=False) is False
    for state in RETRIEVAL_STATES:
        assert counts_towards_health(state, attempted=False) is False


def test_health_key_separates_backends_for_the_same_host() -> None:
    assert health_key("native_http", "Example.COM") == "native_http::example.com"
    assert health_key("native_http", "example.com") != health_key(
        "browser", "example.com"
    )


# ------------------------------------------------------------------ no authority


def test_taxonomy_states_are_closed_and_contain_no_authority() -> None:
    for state in RETRIEVAL_STATES:
        assert not FORBIDDEN_AUTHORITY_FIELDS.intersection({state})
    payload = classify(backend="native_http", http_status=404).to_dict()
    assert_no_authority_fields(payload)
    for forbidden in ("evidence", "support", "gate", "relevance", "confidence"):
        with pytest.raises(RetrievalContractError):
            assert_no_authority_fields({**payload, forbidden: "x"})


def test_outcome_dict_has_no_authority_keys() -> None:
    keys = set(classify(backend="native_http", http_status=200).to_dict())
    assert not keys.intersection(FORBIDDEN_AUTHORITY_FIELDS)
    assert keys == {
        "retrieval_state",
        "attempted",
        "skip_reason",
        "breaker_state",
        "backend",
        "raw_state",
        "detail",
    }


# ------------------------------------------------------- backend health policy model


def test_health_policy_thresholds_are_parameterised() -> None:
    policy = BackendHealthPolicy()
    payload = policy.to_dict()
    assert payload["scope"] == "per_run"
    assert payload["key"] == "backend+host"
    assert all(
        key in payload
        for key in (
            "failure_threshold",
            "open_seconds",
            "half_open_probes",
            "cooldown_seconds",
        )
    )
    assert set(BREAKER_STATES) == {"closed", "open", "half_open", "cooldown"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"failure_threshold": 0},
        {"open_seconds": 0},
        {"half_open_probes": 0},
        {"cooldown_seconds": -1},
    ],
)
def test_health_policy_rejects_degenerate_thresholds(kwargs: dict) -> None:
    with pytest.raises(RetrievalContractError):
        BackendHealthPolicy(**kwargs)


def test_skip_reasons_are_a_closed_set() -> None:
    assert SKIP_REASONS == {
        SKIP_REASON_CIRCUIT_OPEN,
        SKIP_REASON_INSUFFICIENT_WINDOW,
        SKIP_REASON_PREFLIGHT,
        SKIP_REASON_DISABLED,
    }


# --------------------------------------------------- artifact compatibility (§71B)


def test_raw_read_artifact_defaults_are_backwards_compatible() -> None:
    artifact = RawReadArtifact(url="https://example.test/a", content="hello")
    assert artifact.retrieval_state == ""
    assert artifact.retrieval_policy == {}
    # Unclassified is never success.
    assert is_success(artifact.retrieval_state) is False
    # An ordinary artifact counts as attempted.
    assert artifact.attempted is True
    validate_read_artifact(artifact)


def test_artifact_declares_the_new_optional_fields() -> None:
    assert "retrieval_state" in RAW_READ_ARTIFACT_FIELDS
    assert "retrieval_policy" in RAW_READ_ARTIFACT_FIELDS
    validate_backend_payload(
        {"url": "https://example.test/a", "retrieval_state": "reset"},
        allowed_fields=RAW_READ_ARTIFACT_FIELDS,
    )


def test_artifact_rejects_an_unknown_canonical_state() -> None:
    with pytest.raises(RetrievalContractError):
        validate_read_artifact(
            RawReadArtifact(url="https://example.test/a", retrieval_state="kinda_failed")
        )


def test_artifact_rejects_a_skip_that_judges_the_url() -> None:
    with pytest.raises(RetrievalContractError):
        validate_read_artifact(
            RawReadArtifact(
                url="https://example.test/a",
                retrieval_state="not_found",
                retrieval_policy={
                    "attempted": False,
                    "skip_reason": SKIP_REASON_CIRCUIT_OPEN,
                    "breaker_state": "open",
                    "backend": "native_http",
                },
            )
        )


def test_artifact_accepts_a_well_formed_policy_skip() -> None:
    artifact = RawReadArtifact(
        url="https://example.test/a",
        backend="native_http",
        retrieval_state=UNKNOWN_STATE,
        retrieval_policy={
            "attempted": False,
            "skip_reason": SKIP_REASON_CIRCUIT_OPEN,
            "breaker_state": "open",
            "backend": "native_http",
        },
    )
    validate_read_artifact(artifact)
    assert artifact.attempted is False
    assert artifact.usable is False


def test_artifact_rejects_authority_in_the_policy_half() -> None:
    with pytest.raises(RetrievalContractError):
        validate_read_artifact(
            RawReadArtifact(
                url="https://example.test/a",
                retrieval_state="reset",
                retrieval_policy={
                    "attempted": True,
                    "skip_reason": "",
                    "breaker_state": "",
                    "backend": "native_http",
                    "confidence": 0.9,
                },
            )
        )


def test_backend_payload_still_rejects_undeclared_fields() -> None:
    """The §71B rule is unchanged by A0."""

    with pytest.raises(RetrievalContractError):
        validate_backend_payload(
            {"url": "https://example.test/a", "brand_new_thing": 1},
            allowed_fields=RAW_READ_ARTIFACT_FIELDS,
        )
    with pytest.raises(RetrievalContractError):
        validate_backend_payload(
            {"url": "https://example.test/a", "evidence": "trust me"},
            allowed_fields=RAW_READ_ARTIFACT_FIELDS,
        )
