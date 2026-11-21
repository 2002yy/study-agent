"""Contract regressions for the production Wigolo HTTP chain executor.

Tests target the real execution path, not a historical hidden escalation
implementation. They freeze budget admission, single debit, timeout binding,
provider failures, adequacy projection, chain ordering and evidence boundaries.
"""

from __future__ import annotations

from functools import partial
from typing import Any

import pytest

from src.web.research.chain_executor import ChainAttemptRequest, run_chain
from src.web.research.read_escalation import (
    TIER_HTTP,
    charge_run_envelope,
    reset_run_envelope,
    run_envelope_spent_ms,
    wigolo_http_execution_plan,
)
from src.web.research.retrieval_backends import RawReadArtifact
from src.web.research.wigolo_http_executor import WigoloHttpBackendExecutor

GOOD_TEXT = "A" * 1200


class _FakeWigoloHttp:
    """Deterministic stand-in for the Wigolo HTTP backend."""

    def __init__(
        self,
        *,
        content: str = GOOD_TEXT,
        latency_ms: float = 120.0,
        preflight: str = "ready",
        raises: Exception | None = None,
        raw_state: str = "",
        cache_hit: bool | None = False,
        rendered: bool | None = False,
    ) -> None:
        self.name = "wigolo_http"
        self.content = content
        self.latency_ms = latency_ms
        self._preflight = preflight
        self.raises = raises
        self.raw_state = raw_state
        self.cache_hit = cache_hit
        self.rendered = rendered
        self.requests: list[Any] = []

    def preflight(self) -> str:
        return self._preflight

    def fetch(self, request: Any) -> RawReadArtifact:
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        return RawReadArtifact(
            url=request.url,
            content=self.content,
            content_type="text/html",
            retrieval_mode="http",
            backend=self.name,
            latency_ms=self.latency_ms,
            bytes=len(self.content.encode("utf-8")),
            rendered=self.rendered,
            cache_hit=self.cache_hit,
            external_metadata={
                "state": self.raw_state,
                "title": "T",
                "max_chars_requested": request.max_chars,
            },
        )


def _explicit(
    backend: _FakeWigoloHttp,
    *,
    hard_seconds_left: float | None,
    max_chars: int = 6000,
) -> Any:
    executor = WigoloHttpBackendExecutor(
        backend=backend,
        max_chars=max_chars,
        hard_seconds_left=(lambda: hard_seconds_left),
        charge_envelope=partial(charge_run_envelope, tier=TIER_HTTP),
    )
    return executor.execute(
        ChainAttemptRequest(
            candidate_id="c1",
            url="https://x.example/a",
            host="x.example",
            backend="wigolo_http",
            chain_step=1,
            outer_attempt_number=17,
        )
    )


@pytest.fixture(autouse=True)
def _escalation_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_WIGOLO_ESCALATION", "http")
    monkeypatch.delenv("RESEARCH_WIGOLO_HTTP_MIN_HARD_SECONDS_LEFT", raising=False)
    monkeypatch.delenv("RESEARCH_WIGOLO_HTTP_RUN_ENVELOPE_SECONDS", raising=False)
    reset_run_envelope(TIER_HTTP)


def test_success_charges_one_real_wigolo_call() -> None:
    backend = _FakeWigoloHttp(latency_ms=120.0)
    result = _explicit(backend, hard_seconds_left=40.0)
    assert result.attempted is True
    assert result.retrieval_state == "success"
    assert result.usable_content is True
    assert result.content == GOOD_TEXT
    assert len(backend.requests) == 1
    assert run_envelope_spent_ms(TIER_HTTP) == 120.0


def test_low_hard_budget_refuses_without_fetch_or_debit() -> None:
    backend = _FakeWigoloHttp()
    result = _explicit(backend, hard_seconds_left=1.0)
    assert result.attempted is False
    assert result.retrieval_state == "budget_exhausted"
    assert result.adequacy_reason == "hard_headroom_insufficient"
    assert backend.requests == []
    assert run_envelope_spent_ms(TIER_HTTP) == 0.0


def test_exhausted_envelope_refuses_without_double_charge() -> None:
    charge_run_envelope(3000.0, TIER_HTTP)
    backend = _FakeWigoloHttp()
    result = _explicit(backend, hard_seconds_left=40.0)
    assert result.attempted is False
    assert result.adequacy_reason == "run_envelope_exhausted"
    assert backend.requests == []
    assert run_envelope_spent_ms(TIER_HTTP) == 3000.0


def test_timeout_is_clamped_by_remaining_envelope() -> None:
    charge_run_envelope(1500.0, TIER_HTTP)
    backend = _FakeWigoloHttp()
    result = _explicit(backend, hard_seconds_left=40.0)
    assert result.cost["effective_timeout_seconds"] == 1.5
    assert backend.requests[0].timeout_seconds == 1.5


def test_timeout_is_clamped_by_hard_headroom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_WIGOLO_HTTP_MIN_HARD_SECONDS_LEFT", "1.0")
    backend = _FakeWigoloHttp()
    result = _explicit(backend, hard_seconds_left=2.0)
    assert result.cost["effective_timeout_seconds"] == 2.0
    assert backend.requests[0].timeout_seconds == 2.0


def test_wigolo_request_has_the_expected_identity_and_size() -> None:
    backend = _FakeWigoloHttp()
    _explicit(backend, hard_seconds_left=40.0, max_chars=6000)
    (request,) = backend.requests
    assert request.url == "https://x.example/a"
    assert request.max_chars == 6000
    assert request.timeout_seconds == 3.0


def test_unavailable_preflight_fails_closed() -> None:
    backend = _FakeWigoloHttp(preflight="unavailable")
    result = _explicit(backend, hard_seconds_left=40.0)
    assert result.attempted is False
    assert result.policy["skip_reason"] == "preflight"
    assert "unavailable" in result.adequacy_reason
    assert backend.requests == []
    assert run_envelope_spent_ms(TIER_HTTP) == 0.0


def test_disabled_wigolo_never_fetches_or_spends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARCH_WIGOLO_ESCALATION", "off")
    backend = _FakeWigoloHttp()
    result = _explicit(backend, hard_seconds_left=40.0)
    assert result.attempted is False
    assert result.policy["skip_reason"] == "disabled"
    assert backend.requests == []
    assert run_envelope_spent_ms(TIER_HTTP) == 0.0


def test_transport_failure_is_a_canonical_unusable_step() -> None:
    backend = _FakeWigoloHttp(raises=TimeoutError("boom"))
    result = _explicit(backend, hard_seconds_left=40.0)
    assert result.attempted is True
    assert result.usable_content is False
    assert result.retrieval_state == "timeout"
    assert result.cost["error_type"] == "TimeoutError"
    assert result.cost["fetch_ms"] == 0.0
    assert run_envelope_spent_ms(TIER_HTTP) == 0.0


def test_short_page_is_not_evidence_usable() -> None:
    result = _explicit(_FakeWigoloHttp(content="tiny"), hard_seconds_left=40.0)
    assert result.attempted is True
    assert result.usable_content is False
    assert result.retrieval_state == "invalid_content"
    assert result.adequacy_reason == "short_doc"


def test_empty_page_is_not_evidence_usable() -> None:
    result = _explicit(
        _FakeWigoloHttp(content="", raw_state="empty"), hard_seconds_left=40.0
    )
    assert result.attempted is True
    assert result.usable_content is False


def test_cache_and_rendered_flags_survive() -> None:
    reset_run_envelope(TIER_HTTP)
    backend = _FakeWigoloHttp(cache_hit=True, rendered=False)
    result = _explicit(backend, hard_seconds_left=40.0)
    assert result.cost["cache_hit"] is True
    assert result.cost["rendered"] is False
    assert result.cost["bytes"] == len(GOOD_TEXT.encode("utf-8"))
    assert result.cost["content_type"] == "text/html"


def test_executor_uses_the_shared_budget_plan() -> None:
    plan = wigolo_http_execution_plan(
        hard_seconds_left=1.0, envelope_remaining_ms=3000.0
    )
    assert plan.allowed is False
    assert plan.deny_reason == "hard_headroom_insufficient"
    assert plan.deny_layer == "hard_headroom"
    # The executor must surface the shared plan's exact reason.
    result = _explicit(_FakeWigoloHttp(), hard_seconds_left=1.0)
    assert result.adequacy_reason == plan.deny_reason
    assert result.policy["skip_reason"] == "insufficient_remaining_window"
    assert result.policy["attempted"] is False


def test_the_executor_never_touches_outcomes_or_lifecycle() -> None:
    """It returns a result; the chain executor owns history and routing."""

    result = _explicit(_FakeWigoloHttp(), hard_seconds_left=40.0)
    payload = result.to_dict()
    assert "candidate_id" not in payload
    assert "chain_step" not in payload
    from src.web.research.retrieval_backends import FORBIDDEN_AUTHORITY_FIELDS

    assert not set(payload).intersection(FORBIDDEN_AUTHORITY_FIELDS)


def test_the_executor_plugs_into_run_chain() -> None:
    """The A2d-2 skeleton can drive it as a real second chain step."""

    from src.web.research.chain_executor import ChainStepResult

    class _Native:
        name = "native_http"

        def execute(self, request: ChainAttemptRequest) -> ChainStepResult:
            # §111 A3-1R: a transport-shaped state the plain http tier can serve
            # (shell_page needs js_render, which it no longer claims).
            return ChainStepResult(
                backend="native_http", retrieval_state="reset"
            )

    reset_run_envelope(TIER_HTTP)
    executor = WigoloHttpBackendExecutor(
        backend=_FakeWigoloHttp(),
        max_chars=6000,
        hard_seconds_left=(lambda: 40.0),
        charge_envelope=partial(charge_run_envelope, tier=TIER_HTTP),
    )
    recorded: list[ChainStepResult] = []
    run = run_chain(
        candidate_id="c1",
        url="https://x.example/a",
        host="x.example",
        outer_attempt_number=3,
        chain=("native_http", "wigolo_http"),
        executors={"native_http": _Native(), "wigolo_http": executor},
        record_outcome=recorded.append,
    )
    assert [step.backend for step in run.steps] == ["native_http", "wigolo_http"]
    assert [step.chain_step for step in run.steps] == [0, 1]
    assert run.action == "resolve"
    assert run.usable_content is True
    assert [item.backend for item in recorded] == ["native_http", "wigolo_http"]
    assert {step.outer_attempt_number for step in run.steps} == {3}


