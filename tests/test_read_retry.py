"""§48 bounded reader retry: policy, backoff and diagnostics contracts."""

from __future__ import annotations

import pytest

from src.web.research.read_retry import (
    READ_RETRY_ENV,
    is_fetch_layer_failure,
    read_retry_enabled,
    read_with_bounded_retry,
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
    monkeypatch.setenv(READ_RETRY_ENV, "on")
    assert read_retry_enabled() is True


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
        "retry_reasons": [FETCH_ERROR["error"]],
    }


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
    assert slept == [1.0, 2.0]
    assert result["ok"] is False
    assert result["read_retry"]["attempts"] == 3
    assert result["read_retry"]["retries"] == 2


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

    monkeypatch.delenv(READ_RETRY_ENV, raising=False)
    calls = {"count": 0}

    class _Inner:
        def read(self, url: str, *, max_chars: int = 6000):
            del url, max_chars
            calls["count"] += 1
            return {"ok": False, "error": "URLError: 10054"}

    gateway = ActiveResearchGateway(read_gateway=_Inner())
    gateway.read("https://x.example/a")
    assert calls["count"] == 1


def test_enabled_adapter_path_retries_fetch_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.web.research.active_adapter import ActiveResearchGateway

    monkeypatch.setenv(READ_RETRY_ENV, "on")
    calls = {"count": 0}

    class _Inner:
        def read(self, url: str, *, max_chars: int = 6000):
            del url, max_chars
            calls["count"] += 1
            if calls["count"] == 1:
                return {"ok": False, "error": "URLError: 10054"}
            return {"ok": True, "content": "page", "status": "read"}

    gateway = ActiveResearchGateway(read_gateway=_Inner())
    monkeypatch.setattr(
        "src.web.research.read_retry.time.sleep", lambda seconds: None
    )
    result = gateway.read("https://x.example/a")
    assert result["ok"] is True
    assert calls["count"] == 2
    assert result["read_retry"]["retries"] == 1
