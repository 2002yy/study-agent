"""§50/B2 window-aware retry admission: deterministic failure injection.

The rule under test is a formula, not a magic number:

    retry_allowed = remaining_research_time
                    >= attempt_budget + next_backoff + finalization_reserve

18s is just its first instance (12 + 1 + 5). These tests pin the four
deterministic points: well above, just above, just below, and the second retry
(re-admission, so retry #1 never grants retry #2).
"""

from __future__ import annotations

import pytest

from src.web.research.read_retry import (
    READ_RETRY_ATTEMPT_BUDGET_SECONDS,
    READ_RETRY_RESERVE_SECONDS,
    make_window_admission,
    read_with_bounded_retry,
    retry_window_requirement,
)

FETCH_ERROR = {"ok": False, "error": "URLError: [WinError 10054] connection reset"}
OK_PAYLOAD = {"ok": True, "content": "text", "title": "t"}


def test_requirement_is_the_formula_first_instance() -> None:
    assert retry_window_requirement(1) == pytest.approx(
        READ_RETRY_ATTEMPT_BUDGET_SECONDS + 1.0 + READ_RETRY_RESERVE_SECONDS
    )
    assert retry_window_requirement(1) == pytest.approx(18.0)
    # retry #2 needs a longer window because its backoff is longer
    assert retry_window_requirement(2) == pytest.approx(19.0)


def _sequence(payloads: list[dict]):
    calls = {"count": 0}

    def read_fn(url: str):
        del url
        index = min(calls["count"], len(payloads) - 1)
        calls["count"] += 1
        return payloads[index]

    return read_fn, calls


def _clock(values: list[float]):
    """remaining_seconds() returning successive values, then the last one."""

    state = {"index": 0}

    def remaining() -> float:
        index = min(state["index"], len(values) - 1)
        state["index"] += 1
        return values[index]

    return remaining


def test_point_1_well_above_floor_retries_and_recovers() -> None:
    read_fn, calls = _sequence([FETCH_ERROR, OK_PAYLOAD])
    admission = make_window_admission(remaining_seconds=_clock([60.0, 60.0]))
    result = read_with_bounded_retry(
        "https://x.example/a",
        read_fn=read_fn,
        sleep=lambda seconds: None,
        admission=admission,
    )
    assert result["ok"] is True
    assert calls["count"] == 2
    assert result["read_retry"]["retries"] == 1
    assert result["read_retry"]["skipped_due_to_budget"] == 0


def test_point_2_just_above_floor_admits_without_eating_the_reserve() -> None:
    read_fn, calls = _sequence([FETCH_ERROR, OK_PAYLOAD])
    remaining = 18.05
    admission = make_window_admission(remaining_seconds=lambda: remaining)
    decision = admission(1)
    assert decision.allowed is True
    assert decision.required_seconds == pytest.approx(18.0)
    assert decision.remaining_seconds - decision.required_seconds == pytest.approx(0.05)
    result = read_with_bounded_retry(
        "https://x.example/a",
        read_fn=read_fn,
        sleep=lambda seconds: None,
        admission=admission,
    )
    assert calls["count"] == 2
    assert result["read_retry"]["admission_reasons"] == ["allowed"]


def test_point_3_just_below_floor_skips_the_retry() -> None:
    read_fn, calls = _sequence([FETCH_ERROR, OK_PAYLOAD])
    admission = make_window_admission(remaining_seconds=lambda: 17.9)
    result = read_with_bounded_retry(
        "https://x.example/a",
        read_fn=read_fn,
        sleep=lambda seconds: None,
        admission=admission,
    )
    assert calls["count"] == 1
    assert result["ok"] is False
    diagnostics = result["read_retry"]
    assert diagnostics["skipped_due_to_budget"] == 1
    assert diagnostics["retries"] == 0
    assert diagnostics["admission_reasons"] == ["insufficient_window"]


def test_point_4_second_retry_is_re_admitted_not_inherited() -> None:
    read_fn, calls = _sequence([FETCH_ERROR, FETCH_ERROR, OK_PAYLOAD])
    # First check sees 20s (retry #1 admitted), then the window shrinks to 15s
    # (retry #2 refused) - the first permission must not carry over.
    admission = make_window_admission(remaining_seconds=_clock([20.0, 15.0, 15.0]))
    slept: list[float] = []
    result = read_with_bounded_retry(
        "https://x.example/a",
        read_fn=read_fn,
        sleep=slept.append,
        admission=admission,
    )
    assert calls["count"] == 2
    assert slept == [1.0]
    diagnostics = result["read_retry"]
    assert diagnostics["attempts"] == 2
    assert diagnostics["retries"] == 1
    assert diagnostics["skipped_due_to_budget"] == 1
    assert diagnostics["admission_reasons"] == ["allowed", "insufficient_window"]


def test_floor_override_raises_the_requirement() -> None:
    admission = make_window_admission(
        remaining_seconds=lambda: 18.5, floor_seconds=25.0
    )
    decision = admission(1)
    assert decision.allowed is False
    assert decision.required_seconds == pytest.approx(25.0)


def test_inventory_channel_reports_under_its_own_key() -> None:
    read_fn, calls = _sequence([FETCH_ERROR, {"ok": True, "text": "<xml/>"}])
    result = read_with_bounded_retry(
        "https://x.example/sitemap.xml",
        read_fn=read_fn,
        sleep=lambda seconds: None,
        diagnostics_key="inventory_fetch",
    )
    assert calls["count"] == 2
    assert "read_retry" not in result
    assert result["inventory_fetch"]["retries"] == 1


# ---------------------------------------------------------------------------
# Runtime wiring: the sitemap inventory fetch uses the shared policy.
# ---------------------------------------------------------------------------


def _inventory_fetch(attempts: list[dict], calls: dict):
    def fetch(url: str, *, timeout: int, max_bytes: int):
        del timeout, max_bytes
        index = min(calls["count"], len(attempts) - 1)
        calls["count"] += 1
        payload = attempts[index]
        if "raise" in payload:
            raise ConnectionResetError("reset by peer")
        if payload.get("text"):
            return payload["text"], url, payload.get("content_type", "application/xml"), ""
        return "", url, "", payload.get("reason", "empty_response")

    return fetch


def test_inventory_fetch_is_retried_when_the_window_allows(monkeypatch) -> None:
    from src.application.active_research_runtime import (
        _inventory_fetch_with_retry,
    )
    from src.web.research.read_retry import READ_RETRY_ENV

    monkeypatch.setenv(READ_RETRY_ENV, "window_aware")
    calls = {"count": 0}
    fetch = _inventory_fetch(
        [{"raise": True}, {"text": "<urlset/>", "content_type": "application/xml"}],
        calls,
    )
    context: dict = {}
    text, final_url, content_type, reason = _inventory_fetch_with_retry(
        "https://x.example/sitemap.xml",
        context=context,
        remaining_seconds=lambda: 60.0,
        fetch=fetch,
    )
    assert calls["count"] == 2
    assert text == "<urlset/>"
    assert content_type == "application/xml"
    assert reason == ""
    assert final_url == "https://x.example/sitemap.xml"
    metrics = context["claim_engine_metrics"]["inventory_fetch"]
    assert metrics["fetches"] == 1
    assert metrics["attempts"] == 2
    assert metrics["retries"] == 1
    assert metrics["skipped_due_to_budget"] == 0
    assert "read_retry" not in context["claim_engine_metrics"]


def test_inventory_fetch_skips_the_retry_below_the_window(monkeypatch) -> None:
    from src.application.active_research_runtime import (
        _inventory_fetch_with_retry,
    )
    from src.web.research.read_retry import READ_RETRY_ENV

    monkeypatch.setenv(READ_RETRY_ENV, "window_aware")
    calls = {"count": 0}
    fetch = _inventory_fetch([{"raise": True}, {"text": "<urlset/>"}], calls)
    context: dict = {}
    text, _final_url, _content_type, reason = _inventory_fetch_with_retry(
        "https://x.example/sitemap.xml",
        context=context,
        remaining_seconds=lambda: 5.0,
        fetch=fetch,
    )
    assert calls["count"] == 1
    assert text == ""
    assert "URLError" in reason or "ConnectionReset" in reason
    metrics = context["claim_engine_metrics"]["inventory_fetch"]
    assert metrics["skipped_due_to_budget"] == 1
    assert metrics["retries"] == 0


def test_inventory_fetch_off_is_a_single_attempt(monkeypatch) -> None:
    from src.application.active_research_runtime import (
        _inventory_fetch_with_retry,
    )
    from src.web.research.read_retry import READ_RETRY_ENV

    monkeypatch.setenv(READ_RETRY_ENV, "off")
    calls = {"count": 0}
    fetch = _inventory_fetch([{"raise": True}, {"text": "<urlset/>"}], calls)
    context: dict = {}
    text, _final_url, _content_type, reason = _inventory_fetch_with_retry(
        "https://x.example/sitemap.xml",
        context=context,
        remaining_seconds=lambda: 60.0,
        fetch=fetch,
    )
    assert calls["count"] == 1
    assert text == ""
    assert reason
    assert "inventory_fetch" not in context.get("claim_engine_metrics", {})


def test_read_and_inventory_metrics_stay_separate() -> None:
    from src.application.active_research_runtime import _accumulate_fetch_metrics

    context: dict = {}
    _accumulate_fetch_metrics(
        context,
        "read_retry",
        {
            "attempts": 2,
            "retries": 1,
            "skipped_due_to_budget": 0,
            "retry_reasons": ["URLError"],
            "admission_reasons": ["allowed"],
        },
    )
    _accumulate_fetch_metrics(
        context,
        "inventory_fetch",
        {
            "attempts": 1,
            "retries": 0,
            "skipped_due_to_budget": 1,
            "retry_reasons": [],
            "admission_reasons": ["insufficient_window"],
        },
    )
    metrics = context["claim_engine_metrics"]
    assert metrics["read_retry"]["retries"] == 1
    assert metrics["read_retry"]["skipped_due_to_budget"] == 0
    assert metrics["inventory_fetch"]["retries"] == 0
    assert metrics["inventory_fetch"]["skipped_due_to_budget"] == 1
    assert metrics["read_retry"]["fetches"] == 1
    assert metrics["inventory_fetch"]["fetches"] == 1
