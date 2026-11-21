"""Current Wigolo reader policy, budget isolation and native-adapter contracts.

The hidden in-reader escalation implementation is retired. These tests cover
live tier enablement, run-envelope isolation, read adequacy and the real
Wigolo backend's timeout binding without running network or paid models.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
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
    TIER_BROWSER,
    TIER_HTTP,
    browser_tier_allowed,
    charge_run_envelope,
    escalation_mode,
    reset_run_envelope,
    run_envelope_remaining_ms,
    run_envelope_spent_ms,
)
from src.web.research.retrieval_backends import ReadRequest

ADEQUATE_TEXT = "x" * (SHORT_CHAR_THRESHOLD + 200)


@pytest.fixture(autouse=True)
def _fresh_envelope():
    """Each test starts with a full per-run envelope."""

    reset_run_envelope(TIER_HTTP)
    yield
    reset_run_envelope(TIER_HTTP)


def test_envelope_reset_preserves_the_other_tier() -> None:
    reset_run_envelope(TIER_HTTP)
    reset_run_envelope(TIER_BROWSER)
    charge_run_envelope(125.0, TIER_HTTP)
    charge_run_envelope(300.0, TIER_BROWSER)

    reset_run_envelope(TIER_HTTP)
    assert run_envelope_spent_ms(TIER_HTTP) == 0.0
    assert run_envelope_spent_ms(TIER_BROWSER) == 300.0


def test_two_concurrent_research_threads_cannot_reset_each_others_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second run's reset must not erase the first run's physical debit."""
    monkeypatch.setenv("RESEARCH_WIGOLO_HTTP_RUN_ENVELOPE_SECONDS", "3.0")
    first_charged = Event()
    second_charged = Event()

    def first_run() -> tuple[float, float, float]:
        reset_run_envelope(TIER_HTTP)
        reset_run_envelope(TIER_BROWSER)
        charge_run_envelope(240.0, TIER_HTTP)
        charge_run_envelope(70.0, TIER_BROWSER)
        first_charged.set()
        assert second_charged.wait(timeout=10)
        return (
            run_envelope_spent_ms(TIER_HTTP),
            run_envelope_spent_ms(TIER_BROWSER),
            run_envelope_remaining_ms(TIER_HTTP),
        )

    def second_run() -> tuple[float, float, float]:
        assert first_charged.wait(timeout=10)
        reset_run_envelope(TIER_HTTP)
        reset_run_envelope(TIER_BROWSER)
        charge_run_envelope(800.0, TIER_HTTP)
        charge_run_envelope(310.0, TIER_BROWSER)
        second_charged.set()
        return (
            run_envelope_spent_ms(TIER_HTTP),
            run_envelope_spent_ms(TIER_BROWSER),
            run_envelope_remaining_ms(TIER_HTTP),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_run)
        second = pool.submit(second_run)
        assert first.result(timeout=15) == (240.0, 70.0, 2760.0)
        assert second.result(timeout=15) == (800.0, 310.0, 2200.0)


def test_sibling_async_tasks_have_independent_envelope_updates() -> None:
    """Copied task contexts must not share a mutable ledger dict."""
    async def worker(debit: float) -> float:
        reset_run_envelope(TIER_HTTP)
        await asyncio.sleep(0)
        charge_run_envelope(debit, TIER_HTTP)
        await asyncio.sleep(0)
        return run_envelope_spent_ms(TIER_HTTP)

    async def concurrent() -> list[float]:
        return list(await asyncio.gather(worker(140.0), worker(650.0)))

    assert asyncio.run(concurrent()) == [140.0, 650.0]


def _reader_ok(text: str = ADEQUATE_TEXT) -> dict[str, Any]:
    return {"ok": True, "content": text, "title": "t", "url": "https://x.example/"}


def _reader_failed() -> dict[str, Any]:
    return {"ok": False, "content": "", "error": "unsafe_or_empty_url"}


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


class _UnexpectedWigoloBackend:
    """A native adapter read must never call the second chain backend."""

    def __init__(self) -> None:
        self.calls: list[ReadRequest] = []

    def fetch(self, request: ReadRequest) -> None:
        self.calls.append(request)
        raise AssertionError("native adapter bypassed the explicit reader chain")


def test_adapter_never_escalates_even_when_the_mode_allows_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§105 A2d-4: the reader chain owns escalation, the adapter never does.

    Before the cutover this asserted the adapter *did* escalate. It is inverted
    here because the hidden path is retired: even with ``ESCALATION_ENV=http``
    the adapter is a plain native delegation.
    """

    from src.web.research.active_adapter import ActiveResearchGateway

    class _Inner:
        def __init__(self, payload: Mapping[str, Any]) -> None:
            self.payload = payload
            self.calls = 0

        def read(self, url: str, *, max_chars: int = 6000):
            self.calls += 1
            return dict(self.payload)

    monkeypatch.setenv(ESCALATION_ENV, "http")
    backend = _UnexpectedWigoloBackend()

    inner = _Inner(_reader_ok("z" * 120))
    gateway = ActiveResearchGateway(read_gateway=inner)
    gateway.set_escalation_backend(backend)
    result = gateway.read("https://x.example/", max_chars=20000)
    assert inner.calls == 1
    # the backend is never executed and no escalation signal is written
    assert backend.calls == []
    assert len(result["content"]) == 120
    assert "escalation" not in result


def test_backend_enforces_the_binding_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """§71B2: a slow call must not punch through the caller's envelope."""

    import json as _json
    import urllib.request

    from src.web.research.wigolo_backend import WigoloShadowReadBackend

    seen: dict = {}

    class _Response:
        status = 200

        def read(self) -> bytes:
            return _json.dumps({"markdown": "x" * 900, "fetch_method": "http"}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _fake_urlopen(request, timeout=None, **kwargs):
        seen["timeout"] = timeout
        return _Response()

    monkeypatch.setenv("WIGOLO_RERANKER", "off")
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    backend = WigoloShadowReadBackend(tier="http", timeout_seconds=8.0)
    backend._preflight_status = "ready"

    # the caller's 3s envelope binds
    artifact = backend.fetch(ReadRequest(url="https://x.example/", max_chars=100, timeout_seconds=3.0))
    assert seen["timeout"] == 3.0
    assert artifact.usable is True

    # a caller requesting more than the backend cap stays capped at 8s
    backend.fetch(ReadRequest(url="https://x.example/", max_chars=100, timeout_seconds=30.0))
    assert seen["timeout"] == 8.0

    # no caller value -> backend default
    backend.fetch(ReadRequest(url="https://x.example/", max_chars=100))
    assert seen["timeout"] == 8.0

    # a tiny envelope is respected as-is (the escalation refuses below 1s first)
    backend.fetch(ReadRequest(url="https://x.example/", max_chars=100, timeout_seconds=1.0))
    assert seen["timeout"] == 1.0

