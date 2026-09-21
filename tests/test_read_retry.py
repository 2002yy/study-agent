"""§48 bounded reader retry: policy, backoff and diagnostics contracts."""

from __future__ import annotations

import pytest

from src.web.research.read_retry import (
    READ_RETRY_ENV,
    READ_RETRY_FLOOR_ENV,
    is_fetch_layer_failure,
    read_retry_enabled,
    read_retry_mode,
    read_with_bounded_retry,
    retry_window_floor_seconds,
)

FETCH_ERROR = {
    "ok": False,
    "error": "exception:URLError:<urlopen error [WinError 10054] 远程主机强迫关闭了一个现有的连接>",
}
SHORT_OK = {"ok": True, "content": "tiny", "status": "read"}
POLICY_FAILURE = {"ok": False, "error": "unsafe_or_empty_url"}


def test_flag_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(READ_RETRY_ENV, raising=False)
    assert read_retry_enabled() is False
    assert read_retry_mode() == "off"
    monkeypatch.setenv(READ_RETRY_ENV, "on")
    assert read_retry_enabled() is True
    assert read_retry_mode() == "unbounded"
    monkeypatch.setenv(READ_RETRY_ENV, "window_aware")
    assert read_retry_mode() == "window_aware"


def test_window_floor_is_bounded_and_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(READ_RETRY_FLOOR_ENV, raising=False)
    assert retry_window_floor_seconds() == 18.0
    monkeypatch.setenv(READ_RETRY_FLOOR_ENV, "25")
    assert retry_window_floor_seconds() == 25.0
    monkeypatch.setenv(READ_RETRY_FLOOR_ENV, "junk")
    assert retry_window_floor_seconds() == 18.0
    monkeypatch.setenv(READ_RETRY_FLOOR_ENV, "0.2")
    assert retry_window_floor_seconds() == 1.0


def test_fetch_layer_failure_detection() -> None:
    assert is_fetch_layer_failure(FETCH_ERROR) is True
    assert is_fetch_layer_failure({"ok": False, "error": "RemoteDisconnected"}) is True
    assert is_fetch_layer_failure({"ok": False, "error": "request timed out"}) is True
    # Shape/policy failures and successful reads are never retried.
    assert is_fetch_layer_failure(SHORT_OK) is False
    assert is_fetch_layer_failure(POLICY_FAILURE) is False
    assert is_fetch_layer_failure(None) is False


def _sequence(outcomes):
    calls = {"count": 0}

    def read_fn(url: str):
        del url
        index = min(calls["count"], len(outcomes) - 1)
        calls["count"] += 1
        return outcomes[index]

    return read_fn, calls


def test_fetch_failure_recovers_on_retry() -> None:
    read_fn, calls = _sequence([FETCH_ERROR, SHORT_OK])
    slept: list[float] = []
    result = read_with_bounded_retry(
        "https://x.example/a", read_fn=read_fn, sleep=slept.append
    )
    assert result["ok"] is True
    assert calls["count"] == 2
    assert slept == [1.0]
    assert result["read_retry"] == {
        "attempts": 2,
        "retries": 1,
        "skipped_by_admission": 0,
        "skipped_due_to_budget": 0,
        "retry_reasons": [FETCH_ERROR["error"]],
        "admission_reasons": [],
        "retry_fetch_ms": result["read_retry"]["retry_fetch_ms"],
        "retry_backoff_ms": result["read_retry"]["retry_backoff_ms"],
        "suppressed_backoff_ms": result["read_retry"]["suppressed_backoff_ms"],
        "backoff_suppressed_reason": result["read_retry"]["backoff_suppressed_reason"],
        "retry_suppressed_reason": result["read_retry"]["retry_suppressed_reason"],
        "attempts_detail": result["read_retry"]["attempts_detail"],
    }
    detail = result["read_retry"]["attempts_detail"]
    assert [row["index"] for row in detail] == [1, 2]
    assert [row["ok"] for row in detail] == [False, True]
    assert all(row["fetch_ms"] >= 0 for row in detail)
    assert detail[0]["signature"] and not detail[1]["signature"]


def test_success_never_retries_even_when_text_is_short() -> None:
    read_fn, calls = _sequence([SHORT_OK])
    result = read_with_bounded_retry(
        "https://x.example/a", read_fn=read_fn, sleep=lambda s: None
    )
    assert calls["count"] == 1
    assert "read_retry" not in result


def test_policy_failure_never_retries() -> None:
    read_fn, calls = _sequence([POLICY_FAILURE])
    result = read_with_bounded_retry(
        "https://x.example/a", read_fn=read_fn, sleep=lambda s: None
    )
    assert calls["count"] == 1
    assert "read_retry" not in result


def test_retries_are_capped_at_two_with_1s_2s_backoff() -> None:
    read_fn, calls = _sequence([FETCH_ERROR, FETCH_ERROR, FETCH_ERROR, FETCH_ERROR])
    slept: list[float] = []
    result = read_with_bounded_retry(
        "https://x.example/a", read_fn=read_fn, sleep=slept.append
    )
    assert calls["count"] == 3
    # F2-O1b A': the third attempt still happens, but the identical repeated
    # signature makes its 2s wait pointless, so it is suppressed
    assert slept == [1.0]
    assert result["ok"] is False
    assert result["read_retry"]["attempts"] == 3
    assert result["read_retry"]["retries"] == 2
    assert result["read_retry"]["suppressed_backoff_ms"] == 2000.0
    assert (
        result["read_retry"]["backoff_suppressed_reason"]
        == "repeated_error_signature"
    )


def test_transport_exception_is_retried() -> None:
    calls = {"count": 0}

    def read_fn(url: str):
        del url
        calls["count"] += 1
        if calls["count"] == 1:
            raise ConnectionResetError("reset by peer")
        return SHORT_OK

    result = read_with_bounded_retry(
        "https://x.example/a", read_fn=read_fn, sleep=lambda s: None
    )
    assert result["ok"] is True
    assert calls["count"] == 2


def test_disabled_adapter_path_is_a_single_inner_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.web.research.active_adapter import ActiveResearchGateway

    monkeypatch.setenv(READ_RETRY_ENV, "window_aware")
    calls = {"count": 0}

    class _Inner:
        def read(self, url: str, *, max_chars: int = 6000):
            del url, max_chars
            calls["count"] += 1
            return {"ok": False, "error": "URLError: 10054"}

    # The adapter is a plain delegation now: retry lives in the runtime's
    # gateway_read (window-aware), so a read is never retried twice.
    gateway = ActiveResearchGateway(read_gateway=_Inner())
    gateway.read("https://x.example/a")
    assert calls["count"] == 1


def test_admission_can_skip_the_retry() -> None:
    read_fn, calls = _sequence([FETCH_ERROR, SHORT_OK])
    result = read_with_bounded_retry(
        "https://x.example/a",
        read_fn=read_fn,
        sleep=lambda s: None,
        admission=lambda retry_number: False,
    )
    assert calls["count"] == 1
    assert result["ok"] is False
    assert result["read_retry"] == {
        "attempts": 1,
        "retries": 0,
        "skipped_by_admission": 1,
        "skipped_due_to_budget": 1,
        "retry_reasons": [],
        "admission_reasons": ["insufficient_window"],
        "retry_fetch_ms": result["read_retry"]["retry_fetch_ms"],
        "retry_backoff_ms": result["read_retry"]["retry_backoff_ms"],
        "suppressed_backoff_ms": result["read_retry"]["suppressed_backoff_ms"],
        "backoff_suppressed_reason": result["read_retry"]["backoff_suppressed_reason"],
        "retry_suppressed_reason": result["read_retry"]["retry_suppressed_reason"],
        "attempts_detail": result["read_retry"]["attempts_detail"],
    }
    assert [row["index"] for row in result["read_retry"]["attempts_detail"]] == [1]


def test_admission_uses_the_retry_number() -> None:
    read_fn, calls = _sequence([FETCH_ERROR, FETCH_ERROR, SHORT_OK])
    seen: list[int] = []

    def admission(retry_number: int) -> bool:
        seen.append(retry_number)
        return retry_number < 2

    result = read_with_bounded_retry(
        "https://x.example/a",
        read_fn=read_fn,
        sleep=lambda s: None,
        admission=admission,
    )
    assert calls["count"] == 2
    assert seen == [1, 2]
    assert result["read_retry"]["skipped_by_admission"] == 1
    assert result["ok"] is False

# ---------------------------------------------------------------------------
# F2-O1b: repeated-signature backoff suppression (A') + window guard (B)
# ---------------------------------------------------------------------------


def test_signature_ignores_volatile_parts_but_separates_kinds() -> None:
    from src.web.research.read_retry import error_signature

    first = error_signature({"ok": False, "error": "URLError: [WinError 10054] reset a"})
    second = error_signature({"ok": False, "error": "URLError: [WinError 10054] reset b"})
    other = error_signature({"ok": False, "error": "URLError: timed out"})
    assert first == second
    assert first != other
    assert error_signature({"ok": True}) == ""


def test_first_backoff_is_always_paid_even_when_errors_repeat() -> None:
    """A' only removes *subsequent* waits: the first failure keeps its 1s."""

    read_fn, calls = _sequence([FETCH_ERROR, FETCH_ERROR, FETCH_ERROR, FETCH_ERROR])
    slept: list[float] = []
    result = read_with_bounded_retry(
        "https://x.example/a", read_fn=read_fn, sleep=slept.append
    )
    assert calls["count"] == 3
    assert slept == [1.0]
    assert result["read_retry"]["suppressed_backoff_ms"] == 2000.0


def test_different_signatures_keep_the_full_backoff_schedule() -> None:
    """Only *identical* repeated failures suppress the wait."""

    payloads = [
        {"ok": False, "error": "URLError: [WinError 10054] reset"},
        {"ok": False, "error": "URLError: timed out"},
        {"ok": False, "error": "URLError: [WinError 10054] reset"},
    ]
    read_fn, calls = _sequence(payloads)
    slept: list[float] = []
    result = read_with_bounded_retry(
        "https://x.example/a", read_fn=read_fn, sleep=slept.append
    )
    assert calls["count"] == 3
    assert slept == [1.0, 2.0]
    assert result["read_retry"]["backoff_suppressed_reason"] == ""


def test_window_guard_suppresses_a_retry_that_cannot_fit() -> None:
    """B: deadline-preserving retry suppression, recorded as its own reason."""

    read_fn, calls = _sequence([FETCH_ERROR, FETCH_ERROR, FETCH_ERROR])
    slept: list[float] = []
    result = read_with_bounded_retry(
        "https://x.example/a",
        read_fn=read_fn,
        sleep=slept.append,
        remaining_seconds=lambda: 0.5,
    )
    assert calls["count"] == 1  # the retry never started
    assert slept == []
    diagnostics = result["read_retry"]
    assert diagnostics["retry_suppressed_reason"] == "insufficient_remaining_window"
    assert diagnostics["skipped_due_to_budget"] == 1
    assert diagnostics["retries"] == 0


def test_window_guard_allows_a_retry_that_fits() -> None:
    read_fn, calls = _sequence([FETCH_ERROR, SHORT_OK])
    result = read_with_bounded_retry(
        "https://x.example/a",
        read_fn=read_fn,
        sleep=lambda seconds: None,
        remaining_seconds=lambda: 30.0,
    )
    assert calls["count"] == 2
    assert result["ok"] is True
    assert result["read_retry"]["retry_suppressed_reason"] == ""


def test_window_guard_uses_the_last_attempt_cost_as_its_estimate() -> None:
    """No latency model: the previous attempt's own elapsed time is the bound."""

    class _Clock:
        def __init__(self) -> None:
            self.value = 0.0

        def __call__(self) -> float:
            return self.value

    def _run(remaining: float) -> dict:
        clock = _Clock()

        def read_fn(url: str):
            del url
            clock.value += 1.0  # every attempt costs exactly 1s
            return dict(FETCH_ERROR)

        return read_with_bounded_retry(
            "https://x.example/a",
            read_fn=read_fn,
            sleep=lambda seconds: None,
            clock=clock,
            remaining_seconds=lambda: remaining,
        )

    # 1s backoff + 1s expected fetch = 2s: fits exactly
    allowed = _run(2.0)
    assert allowed["read_retry"]["attempts"] == 3
    assert allowed["read_retry"]["retry_suppressed_reason"] == ""

    # same estimate against a 1.5s window: the retry is refused
    refused = _run(1.5)
    assert refused["read_retry"]["attempts"] == 1
    assert (
        refused["read_retry"]["retry_suppressed_reason"]
        == "insufficient_remaining_window"
    )
