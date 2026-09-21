"""§71C-3a reader escalation: adequacy gate, isolation, tier policy, ledger.

All tests are deterministic and never touch the daemon: the backend is injected
as a fake, so the suite can assert exactly when the escalation is *not* called
(already-adequate reads, disabled mode, misconfigured preflight) and that a
failing escalation never changes the current reader's result.
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from src.web.research.read_adequacy import (
    SHORT_CHAR_THRESHOLD,
    classify_reader_result,
    is_adequate,
)
from src.web.research.read_escalation import (
    BROWSER_TIER_ENV,
    ESCALATION_ENV,
    EscalationOutcome,
    browser_tier_allowed,
    escalate_read,
    escalation_mode,
    reset_http_envelope,
)
from src.web.research.retrieval_backends import RawReadArtifact, ReadRequest

ADEQUATE_TEXT = "x" * (SHORT_CHAR_THRESHOLD + 200)


@pytest.fixture(autouse=True)
def _fresh_envelope():
    """Each test starts with a full per-run envelope."""

    reset_http_envelope()
    yield
    reset_http_envelope()


def _reader_ok(text: str = ADEQUATE_TEXT) -> dict[str, Any]:
    return {"ok": True, "content": text, "title": "t", "url": "https://x.example/"}


def _reader_failed() -> dict[str, Any]:
    return {"ok": False, "content": "", "error": "unsafe_or_empty_url"}


class _FakeBackend:
    name = "wigolo"

    def __init__(
        self,
        *,
        content: str = "",
        preflight: str = "ready",
        state: str = "",
        raise_error: Exception | None = None,
    ) -> None:
        self.content = content
        self.preflight_status = preflight
        self.state = state
        self.raise_error = raise_error
        self.calls: list[ReadRequest] = []
        self.tier = "http"

    def preflight(self) -> str:
        return self.preflight_status

    def fetch(self, request: ReadRequest) -> RawReadArtifact:
        self.calls.append(request)
        if self.raise_error is not None:
            raise self.raise_error
        return RawReadArtifact(
            url=request.url,
            content=self.content,
            content_type="text/markdown",
            retrieval_mode="http",
            backend=self.name,
            latency_ms=912.0,
            bytes=len(self.content.encode("utf-8")),
            rendered=False,
            cache_hit=False,
            external_metadata={
                "state": self.state,
                "tier": self.tier,
                "max_chars_requested": request.max_chars if False else 20000,
                "chars_returned": len(self.content),
            },
        )


# ---------------------------------------------------------------------------
# adequacy gate
# ---------------------------------------------------------------------------


def test_adequacy_classification() -> None:
    assert classify_reader_result(_reader_ok()).shape == "ok"
    assert is_adequate(_reader_ok()) is True
    short = classify_reader_result(_reader_ok("tiny"))
    assert short.shape == "short_doc" and short.adequate is False
    shell = classify_reader_result(_reader_ok("Please enable JavaScript to continue"))
    assert shell.shape == "js_shell" and shell.adequate is False
    blocked = classify_reader_result(_reader_ok("Checking your browser before access"))
    assert blocked.shape == "anti_bot_or_error" and blocked.adequate is False
    assert classify_reader_result(_reader_failed()).shape == "read_failed"
    assert is_adequate(None) is False


# ---------------------------------------------------------------------------
# gate items 1-3: when the escalation runs (and when it must not)
# ---------------------------------------------------------------------------


def test_mode_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ESCALATION_ENV, raising=False)
    assert escalation_mode() == "off"
    monkeypatch.setenv(ESCALATION_ENV, "http")
    assert escalation_mode() == "http"
    monkeypatch.setenv(ESCALATION_ENV, "browser")
    assert escalation_mode() == "browser"
    monkeypatch.setenv(ESCALATION_ENV, "junk")
    assert escalation_mode() == "off"


def test_browser_tier_requires_its_own_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ESCALATION_ENV, "http")
    monkeypatch.setenv(BROWSER_TIER_ENV, "on")
    assert browser_tier_allowed() is False  # mode must be browser too
    monkeypatch.setenv(ESCALATION_ENV, "browser")
    monkeypatch.delenv(BROWSER_TIER_ENV, raising=False)
    assert browser_tier_allowed() is False  # default off
    monkeypatch.setenv(BROWSER_TIER_ENV, "on")
    assert browser_tier_allowed() is True


def test_gate_1_already_adequate_never_calls_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ESCALATION_ENV, "http")
    backend = _FakeBackend(content=ADEQUATE_TEXT)
    result, outcome = escalate_read(
        url="https://x.example/",
        current=_reader_ok(),
        http_backend=backend,
        max_chars=20000,
    )
    assert backend.calls == []
    assert outcome.attempted is False
    assert outcome.reason == "already_adequate"
    assert result["content"] == ADEQUATE_TEXT


def test_gate_2_3_inadequate_read_is_rescued(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ESCALATION_ENV, "http")
    rescued_text = "y" * 10_793
    backend = _FakeBackend(content=rescued_text)
    current = _reader_ok("z" * 520)
    result, outcome = escalate_read(
        url="https://docs.docker.com/docker-hub/usage/pulls/",
        current=current,
        http_backend=backend,
        max_chars=20000,
    )
    assert len(backend.calls) == 1
    assert result["content"] == rescued_text
    assert outcome.attempted is True
    assert outcome.tier == "http"
    assert outcome.shape_before == "short_doc"
    assert outcome.shape_after == "ok"
    assert outcome.rescued is True
    assert outcome.chars_before == 520
    assert outcome.chars_after == 10_793


def test_gate_4_escalation_failure_keeps_current_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ESCALATION_ENV, "http")
    current = _reader_ok("z" * 520)
    for backend in (
        _FakeBackend(state="timeout"),
        _FakeBackend(state="http_error"),
        _FakeBackend(content=""),
        _FakeBackend(raise_error=TimeoutError("boom")),
    ):
        reset_http_envelope()  # this test isolates failure isolation, not budget
        result, outcome = escalate_read(
            url="https://x.example/",
            current=current,
            http_backend=backend,
            max_chars=20000,
        )
        assert result is current  # untouched
        assert outcome.attempted is True
        assert outcome.rescued is False
        assert outcome.reason


def test_gate_5_browser_tier_is_not_used_by_the_http_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ESCALATION_ENV, "http")
    monkeypatch.setenv(BROWSER_TIER_ENV, "on")
    backend = _FakeBackend(content=ADEQUATE_TEXT)
    _result, outcome = escalate_read(
        url="https://x.example/",
        current=_reader_ok("z" * 100),
        http_backend=backend,
        max_chars=20000,
    )
    assert outcome.tier == "http"
    assert all(request.retrieval_mode == "http" for request in backend.calls)


def test_gate_6_misconfigured_preflight_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ESCALATION_ENV, "http")
    current = _reader_ok("z" * 100)
    backend = _FakeBackend(content=ADEQUATE_TEXT, preflight="misconfigured")
    result, outcome = escalate_read(
        url="https://x.example/",
        current=current,
        http_backend=backend,
        max_chars=20000,
    )
    assert backend.calls == []  # never "try and see"
    assert result is current
    assert outcome.reason == "misconfigured"
    assert outcome.attempted is False


def test_missing_backend_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ESCALATION_ENV, "http")
    current = _reader_ok("z" * 100)
    result, outcome = escalate_read(
        url="https://x.example/", current=current, http_backend=None, max_chars=20000
    )
    assert result is current
    assert outcome.reason == "backend_unavailable"


# ---------------------------------------------------------------------------
# gate items 7 and 10: ledger + provenance, model budget untouched
# ---------------------------------------------------------------------------


class _Metrics(dict):
    pass


def test_gate_7_10_ledger_records_tier_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ESCALATION_ENV, "http")
    metrics: _Metrics = {}
    backend = _FakeBackend(content="y" * 5000)
    _result, outcome = escalate_read(
        url="https://x.example/",
        current=_reader_ok("z" * 100),
        http_backend=backend,
        metrics_provider=lambda: metrics,
        claim_id="claim_1",
        wave_index=2,
        max_chars=20000,
    )
    attempts = metrics["retrieval_attempts"]
    assert attempts and attempts[-1]["tier"] == "http"
    assert attempts[-1]["transition"] == "short_doc -> ok"
    assert attempts[-1]["latency_ms"] == 912.0
    invocations = metrics["retrieval_invocations"]
    assert invocations and invocations[-1]["state"] == "ok"
    assert invocations[-1]["tier"] == "http"
    assert invocations[-1]["invocation_id"] == "claim_1:2:wigolo:fetch:1"
    # provenance for the frozen max_chars contract
    assert outcome.max_chars_requested == 20000
    assert outcome.to_dict()["chars_after"] == 5000


def test_gate_8_escalation_spends_no_model_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ESCALATION_ENV, "http")
    metrics: _Metrics = {"orchestration_model_calls": 3}
    _result, _outcome = escalate_read(
        url="https://x.example/",
        current=_reader_ok("z" * 100),
        http_backend=_FakeBackend(content="y" * 5000),
        metrics_provider=lambda: metrics,
        claim_id="claim_1",
        wave_index=1,
        max_chars=20000,
    )
    assert metrics["orchestration_model_calls"] == 3
    assert "model" not in str(metrics.get("retrieval_attempts"))


def test_outcome_serialization_has_no_authority_fields() -> None:
    outcome = EscalationOutcome(
        attempted=True, tier="http", state="ok", shape_before="short_doc", shape_after="ok"
    )
    payload = outcome.to_dict()
    assert payload["rescued"] is True
    assert payload["tier"] == "http"
    for forbidden in ("evidence", "support", "gate", "relevance", "confidence"):
        assert forbidden not in payload


# ---------------------------------------------------------------------------
# adapter wiring
# ---------------------------------------------------------------------------


def test_adapter_escalates_only_when_the_reader_is_inadequate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.web.research.active_adapter import ActiveResearchGateway

    class _Inner:
        def __init__(self, payload: Mapping[str, Any]) -> None:
            self.payload = payload
            self.calls = 0

        def read(self, url: str, *, max_chars: int = 6000):
            self.calls += 1
            return dict(self.payload)

    monkeypatch.setenv(ESCALATION_ENV, "http")
    backend = _FakeBackend(content="y" * 9000)

    inner = _Inner(_reader_ok("z" * 120))
    gateway = ActiveResearchGateway(read_gateway=inner)
    gateway.set_escalation_backend(backend)
    result = gateway.read("https://x.example/", max_chars=20000)
    assert inner.calls == 1
    assert len(backend.calls) == 1
    assert len(result["content"]) == 9000
    assert result["escalation"]["rescued"] is True

    inner_ok = _Inner(_reader_ok())
    gateway_ok = ActiveResearchGateway(read_gateway=inner_ok)
    gateway_ok.set_escalation_backend(_FakeBackend(content=ADEQUATE_TEXT))
    result_ok = gateway_ok.read("https://x.example/", max_chars=20000)
    assert result_ok["content"] == ADEQUATE_TEXT
    # adequate reads are untouched and the reason is recorded, not a call
    assert result_ok["escalation"]["attempted"] is False
    assert result_ok["escalation"]["reason"] == "already_adequate"


def test_adapter_default_mode_is_plain_delegation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.web.research.active_adapter import ActiveResearchGateway

    class _Inner:
        def read(self, url: str, *, max_chars: int = 6000):
            return {"ok": True, "content": "short", "title": "t"}

    monkeypatch.delenv(ESCALATION_ENV, raising=False)
    backend = _FakeBackend(content=ADEQUATE_TEXT)
    gateway = ActiveResearchGateway(read_gateway=_Inner())
    gateway.set_escalation_backend(backend)
    result = gateway.read("https://x.example/", max_chars=20000)
    assert backend.calls == []
    assert result["content"] == "short"
    assert "escalation" not in result
