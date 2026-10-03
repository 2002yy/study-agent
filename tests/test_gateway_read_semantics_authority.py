"""§143-B0.1 read-semantics parity regressions.

The narrow measurement entry is only trustworthy when the *read function* it
drives is the exact same production read function ``execute()`` drives. B0
closed executor identity; these tests close behavioural identity:

* the shared primitive owns metrics sequencing, escalation runtime context, the
  bounded retry policy and the window-bounded read timeout;
* a caller can only inject the low-level gateway/clock, never a read function.

They exercise the real ``read_with_bounded_retry`` policy (no retry function is
stubbed); only the network gateway, the clock and the observer hooks are fakes.
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from src.application import active_research_runtime as runtime
from src.application.active_research_runtime import build_production_gateway_read
from src.web.research import read_retry

METRICS_KEY = runtime.ACTIVE_RESEARCH_METRICS_KEY


class _FakeGateway:
    """Records every underlying fetch; never touches the network."""

    def __init__(self, responses: list[Mapping[str, Any]] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def read(self, url: str, *, max_chars: int, timeout: float | None = None) -> Mapping[str, Any]:
        self.calls.append({"url": url, "max_chars": max_chars, "timeout": timeout})
        if self.responses:
            return self.responses.pop(0)
        return {"ok": True, "text": "x" * 40}


def _build(
    gateway: _FakeGateway,
    context: dict[str, Any],
    *,
    accepts_timeout: bool = True,
    research_left: float = 30.0,
    hard_left: float = 40.0,
    wave: int = 3,
    on_phase: list[str] | None = None,
    on_retry: list[dict[str, float]] | None = None,
):
    return build_production_gateway_read(
        gateway=gateway,
        accepts_timeout=accepts_timeout,
        get_context=lambda: context,
        research_seconds_left=lambda: research_left,
        hard_seconds_left=lambda: hard_left,
        wave_index=lambda: wave,
        on_phase_start=(on_phase.append if on_phase is not None else None),
        on_phase_end=(on_phase.append if on_phase is not None else None),
        on_retry=(lambda **kw: on_retry.append(kw)) if on_retry is not None else None,
    )


def test_off_mode_stamps_sequence_and_forwards_window_timeout(monkeypatch) -> None:
    monkeypatch.delenv(read_retry.READ_RETRY_ENV, raising=False)
    context: dict[str, Any] = {}
    gateway = _FakeGateway()
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(
        runtime,
        "set_escalation_runtime_context",
        lambda **kw: seen.append(kw),
    )
    phases: list[str] = []

    gateway_read = _build(gateway, context, on_phase=phases)
    first = gateway_read("http://example.test/a", max_chars=100)
    second = gateway_read("http://example.test/b", max_chars=100)

    assert first["ok"] is True and second["ok"] is True
    # timeout = min(READ_TIMEOUT_CAP_SECONDS, research window) == 10.0
    assert [c["timeout"] for c in gateway.calls] == [
        runtime.READ_TIMEOUT_CAP_SECONDS,
        runtime.READ_TIMEOUT_CAP_SECONDS,
    ]
    assert [c["max_chars"] for c in gateway.calls] == [100, 100]
    # attempt sequence is stamped and monotonic
    assert context[METRICS_KEY]["retrieval_attempt_seq"] == 2
    assert [s["attempt_seq"] for s in seen] == [1, 2]
    assert seen[0]["research_seconds_left"] == 30.0
    assert seen[0]["hard_seconds_left"] == 40.0
    # read phase is bracketed (start + end per read)
    assert phases == ["read", "read", "read", "read"]


def test_timeout_is_not_forwarded_when_gateway_does_not_accept_it(monkeypatch) -> None:
    monkeypatch.delenv(read_retry.READ_RETRY_ENV, raising=False)
    context: dict[str, Any] = {}
    gateway = _FakeGateway()

    gateway_read = _build(gateway, context, accepts_timeout=False)
    gateway_read("http://example.test/c", max_chars=50)

    assert gateway.calls == [
        {"url": "http://example.test/c", "max_chars": 50, "timeout": None}
    ]


def test_window_aware_mode_uses_real_bounded_retry_policy(monkeypatch) -> None:
    monkeypatch.setenv(read_retry.READ_RETRY_ENV, "window_aware")
    # keep the deterministic 1s/2s backoff from actually sleeping
    monkeypatch.setattr(read_retry.time, "sleep", lambda _seconds: None)

    context: dict[str, Any] = {}
    gateway = _FakeGateway(
        [
            {"ok": False, "error": "timed out"},
            {"ok": True, "text": "recovered content"},
        ]
    )
    retries: list[dict[str, float]] = []

    gateway_read = _build(gateway, context, on_retry=retries)
    payload = gateway_read("http://example.test/d", max_chars=80)

    assert payload["ok"] is True
    assert payload["text"] == "recovered content"
    diag = payload["read_retry"]
    assert diag["attempts"] == 2 and diag["retries"] == 1

    # the shared primitive accumulated the retry diagnostics itself
    assert context[METRICS_KEY]["read_retry"]["fetches"] == 1
    assert context[METRICS_KEY]["read_retry"]["attempts"] == 2
    # and surfaced the retry cost through the observer hook
    assert len(retries) == 1 and retries[0]["fetch_ms"] >= 0.0


def test_escalation_payload_routes_through_module_authority(monkeypatch) -> None:
    monkeypatch.delenv(read_retry.READ_RETRY_ENV, raising=False)
    context: dict[str, Any] = {METRICS_KEY: {"retrieval_attempts": []}}
    gateway = _FakeGateway([{"ok": True, "text": "body", "escalation": {"state": "ok"}}])
    recorded: list[tuple[Any, int]] = []
    monkeypatch.setattr(
        runtime,
        "_record_escalation_diagnostics",
        lambda ctx, escalation, *, wave_index: recorded.append((escalation, wave_index)),
    )

    gateway_read = _build(gateway, context, wave=7)
    gateway_read("http://example.test/e", max_chars=10)

    assert recorded == [({"state": "ok"}, 7)]


def test_retry_budget_refusal_is_observable(monkeypatch) -> None:
    """When the window cannot afford a retry the failure is preserved."""

    monkeypatch.setenv(read_retry.READ_RETRY_ENV, "window_aware")
    monkeypatch.setattr(read_retry.time, "sleep", lambda _seconds: None)

    context: dict[str, Any] = {}
    gateway = _FakeGateway([{"ok": False, "error": "connection refused"}])

    # remaining < attempt budget + backoff + reserve -> admission refuses
    gateway_read = build_production_gateway_read(
        gateway=gateway,
        accepts_timeout=False,
        get_context=lambda: context,
        research_seconds_left=lambda: 1.0,
        hard_seconds_left=lambda: 2.0,
        wave_index=lambda: 0,
    )
    payload = gateway_read("http://example.test/f", max_chars=10)

    assert payload["ok"] is False
    assert payload["read_retry"]["retries"] == 0
    assert payload["read_retry"]["skipped_by_admission"] == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
