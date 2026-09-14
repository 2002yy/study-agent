from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

import src.web.tool_gateway as tool_gateway
from src.web.research.provider_search import PROVIDER_ORDER, ResearchProviderSearch
from src.web.tool_gateway import GeneralWebGateway


class _Clock:
    def __init__(self) -> None:
        self.value = 10.0

    def __call__(self) -> float:
        self.value += 0.1
        return self.value


def _item(url: str, title: str, snippet: str = "") -> dict[str, str]:
    return {"url": url, "title": title, "snippet": snippet, "source": "fixture"}


def test_legacy_gateway_still_stops_after_first_nonempty_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tool_gateway, "searxng_enabled", lambda: True)
    monkeypatch.setattr(
        tool_gateway,
        "search_searxng",
        lambda *args, **kwargs: [
            {"title": "first", "link": "https://example.test/first"}
        ],
    )
    monkeypatch.setenv("WEB_ENABLE_BING_RSS", "1")
    monkeypatch.setenv("WEB_ENABLE_DUCKDUCKGO", "1")

    def must_not_run(*args: Any, **kwargs: Any) -> tuple[list[dict[str, str]], str]:
        raise AssertionError("legacy fallback ran after a non-empty provider")

    monkeypatch.setattr(
        GeneralWebGateway, "_search_bing_rss", staticmethod(must_not_run)
    )
    monkeypatch.setattr(
        GeneralWebGateway, "_search_duckduckgo", staticmethod(must_not_run)
    )

    payload = GeneralWebGateway().search_exact("query")
    assert payload["status"] == "ok"
    assert payload["providers_attempted"] == ["searxng"]


def test_research_search_runs_all_providers_and_merges_duplicate_provenance() -> None:
    calls: list[str] = []

    def call(provider: str, query: str, limit: int, timeout: float):
        calls.append(provider)
        if provider == "searxng":
            return [
                _item("https://example.test/shared?utm_source=x", "shared"),
                _item("https://example.test/searx", "searx"),
            ], ""
        if provider == "bing_rss":
            return [
                _item(
                    "https://example.test/shared",
                    "shared",
                    "richer duplicate snippet",
                )
            ], ""
        return [_item("https://example.test/ddg", "ddg")], ""

    payload = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: True,
        monotonic=_Clock(),
        provider_timeout_seconds=4.0,
    ).search_exact("query", max_results=5)

    assert calls == list(PROVIDER_ORDER)
    assert payload["status"] == "ok"
    assert payload["providers_attempted"] == list(PROVIDER_ORDER)
    assert len(payload["provider_audits"]) == 3
    shared = next(
        item for item in payload["results"] if item["url"] == "https://example.test/shared"
    )
    assert shared["providers"] == ["searxng", "bing_rss"]
    assert shared["snippet"] == "richer duplicate snippet"


def test_transient_failure_retries_once_then_recovers() -> None:
    calls = 0

    def call(provider: str, query: str, limit: int, timeout: float):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [], "bing_rss:TimeoutError:temporary"
        return [_item("https://example.test/recovered", "recovered")], ""

    payload = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: provider == "bing_rss",
        monotonic=_Clock(),
    ).search_exact("query")

    assert calls == 2
    assert payload["status"] == "ok"
    assert [item["status"] for item in payload["provider_audits"]] == [
        "failed",
        "ok",
    ]
    assert payload["provider_audits"][0]["reason"] == "timeout"
    assert payload["provider_outcomes"][0]["attempts"] == 2


def test_empty_is_not_failure_and_is_not_retried() -> None:
    calls = 0

    def call(provider: str, query: str, limit: int, timeout: float):
        nonlocal calls
        calls += 1
        return [], "duckduckgo_html:empty_response"

    payload = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: provider == "duckduckgo_html",
        monotonic=_Clock(),
    ).search_exact("query")

    assert calls == 1
    assert payload["status"] == "empty"
    assert payload["provider_errors"] == []


def test_mixed_failure_and_empty_is_partial_not_empty() -> None:
    def call(provider: str, query: str, limit: int, timeout: float):
        if provider == "bing_rss":
            return [], "bing_rss:http_status:403"
        return [], "duckduckgo_html:empty_response"

    payload = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: provider in {"bing_rss", "duckduckgo_html"},
        monotonic=_Clock(),
    ).search_exact("query")

    assert payload["status"] == "partial"
    assert payload["provider_outcomes"][0]["status"] == "failed"
    assert payload["provider_outcomes"][0]["reason"] == "http_status:403"
    assert payload["provider_outcomes"][1]["status"] == "empty"


def test_all_failures_are_unavailable_without_retry_for_403() -> None:
    calls: list[str] = []

    def call(provider: str, query: str, limit: int, timeout: float):
        calls.append(provider)
        return [], f"{provider}:http_status:403"

    payload = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: True,
        monotonic=_Clock(),
    ).search_exact("query")

    assert calls == list(PROVIDER_ORDER)
    assert payload["status"] == "unavailable"
    assert all(item["attempts"] == 1 for item in payload["provider_outcomes"])


def test_attempt_audit_is_bounded_and_excludes_result_text() -> None:
    marker = "PAGE-CONTENT-MARKER"

    def call(provider: str, query: str, limit: int, timeout: float):
        return [_item("https://example.test/page", "result", marker)], ""

    payload = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: provider == "searxng",
        monotonic=_Clock(),
    ).search_exact("research query")

    audit_text = str(payload["provider_audits"])
    assert marker not in audit_text
    assert "research query" not in audit_text
    audit = payload["provider_audits"][0]
    assert audit["query_chars"] == len("research query")
    assert len(audit["query_sha256"]) == 64


def test_raw_provider_error_and_exception_messages_are_not_persisted() -> None:
    marker = "PRIVATE-QUERY-OR-URL-MARKER"
    calls = 0

    def call(provider: str, query: str, limit: int, timeout: float):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [], f"bing_rss:TimeoutError:{marker}"
        raise TimeoutError(marker)

    payload = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: provider == "bing_rss",
        monotonic=_Clock(),
    ).search_exact("query")

    assert calls == 2
    durable_text = str(
        {
            "provider_errors": payload["provider_errors"],
            "provider_audits": payload["provider_audits"],
            "provider_outcomes": payload["provider_outcomes"],
        }
    )
    assert marker not in durable_text
    assert payload["status"] == "unavailable"
    assert payload["provider_errors"] == ["bing_rss:timeout"]
    assert all(item["reason"] == "timeout" for item in payload["provider_audits"])


def test_b1_module_does_not_import_eval_code() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "web"
        / "research"
        / "provider_search.py"
    )
    assert "src.evals" not in path.read_text(encoding="utf-8")


class _ManualClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_deadline_skips_all_providers_when_budget_insufficient() -> None:
    calls: list[str] = []
    clock = _ManualClock(100.0)

    def call(provider: str, query: str, limit: int, timeout: float):
        calls.append(provider)
        return [_item(f"https://example.test/{provider}", provider)], ""

    payload = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: True,
        monotonic=clock,
        provider_timeout_seconds=6.0,
    ).search_exact("query", deadline=100.5)

    assert calls == []
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "skipped_insufficient_budget"
    assert payload["provider_errors"] == []
    assert [item["status"] for item in payload["provider_outcomes"]] == [
        "skipped",
        "skipped",
        "skipped",
    ]
    assert all(
        item["reason"] == "skipped_insufficient_budget"
        and item["attempts"] == 0
        for item in payload["provider_outcomes"]
    )
    assert [item["status"] for item in payload["provider_audits"]] == [
        "skipped",
        "skipped",
        "skipped",
    ]


def test_deadline_stops_transient_retry_and_preserves_failure_reason() -> None:
    calls: list[str] = []
    clock = _ManualClock(100.0)

    def call(provider: str, query: str, limit: int, timeout: float):
        calls.append(provider)
        clock.advance(6.0)
        return [], "bing_rss:TimeoutError:timed out"

    payload = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: provider == "bing_rss",
        monotonic=clock,
        provider_timeout_seconds=6.0,
    ).search_exact("query", deadline=100.0 + 7.0)

    assert calls == ["bing_rss"]
    outcome = payload["provider_outcomes"][0]
    assert outcome["status"] == "failed"
    assert outcome["reason"] == "timeout"
    assert outcome["attempts"] == 1
    assert payload["provider_errors"] == ["bing_rss:timeout"]


def test_deadline_caps_attempt_timeout_to_remaining_budget() -> None:
    seen_timeouts: list[float] = []
    clock = _ManualClock(100.0)

    def call(provider: str, query: str, limit: int, timeout: float):
        seen_timeouts.append(timeout)
        return [_item("https://example.test/a", "a")], ""

    payload = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: provider == "bing_rss",
        monotonic=clock,
        provider_timeout_seconds=6.0,
    ).search_exact("query", deadline=100.0 + 3.0)

    assert seen_timeouts == [3.0]
    assert payload["status"] == "ok"


def test_deadline_skip_after_success_is_partial_with_results() -> None:
    clock = _ManualClock(100.0)

    def call(provider: str, query: str, limit: int, timeout: float):
        if provider == "searxng":
            clock.advance(9.0)
            return [_item("https://example.test/searx", "searx")], ""
        return [_item(f"https://example.test/{provider}", provider)], ""

    payload = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: True,
        monotonic=clock,
        provider_timeout_seconds=6.0,
    ).search_exact("query", deadline=100.0 + 10.0)

    assert payload["status"] == "partial"
    assert payload["reason"] == "results_with_provider_failures"
    assert [item["url"] for item in payload["results"]] == [
        "https://example.test/searx"
    ]
    statuses = [item["status"] for item in payload["provider_outcomes"]]
    assert statuses == ["ok", "skipped", "skipped"]


def test_provider_wallclock_timeout_is_enforced() -> None:
    """Timeout Invariant: the configured provider budget bounds wall-clock."""

    def slow_call(provider: str, query: str, limit: int, timeout: float):
        time.sleep(3.0)
        return [], "bing_rss:TimeoutError:timed out"

    started = time.monotonic()
    payload = ResearchProviderSearch(
        provider_call=slow_call,
        provider_enabled=lambda provider: provider == "bing_rss",
        provider_timeout_seconds=2.0,
    ).search_exact("query")
    elapsed = time.monotonic() - started

    outcome = payload["provider_outcomes"][0]
    assert outcome["status"] == "failed"
    assert outcome["reason"] == "wallclock_timeout"
    assert outcome["attempts"] == 1
    # The abandoned worker keeps running in the background, but the provider
    # lifetime itself is bounded (with a small scheduling margin).
    assert elapsed < 2.6


def test_retry_is_not_started_without_provider_budget() -> None:
    """A transient failure that spends the aggregate budget must not retry."""

    calls: list[float] = []

    def slow_transient(provider: str, query: str, limit: int, timeout: float):
        calls.append(timeout)
        time.sleep(1.8)
        return [], "bing_rss:TimeoutError:timed out"

    payload = ResearchProviderSearch(
        provider_call=slow_transient,
        provider_enabled=lambda provider: provider == "bing_rss",
        provider_timeout_seconds=2.0,
    ).search_exact("query")

    assert len(calls) == 1
    outcome = payload["provider_outcomes"][0]
    assert outcome["status"] == "failed"
    assert outcome["attempts"] == 1
    # The skipped retry is observable in the audit trail.
    assert any(
        audit["reason"] == "retry_budget_exhausted"
        for audit in payload["provider_audits"]
    )


def test_no_deadline_preserves_legacy_retry_behavior() -> None:
    calls = 0

    def call(provider: str, query: str, limit: int, timeout: float):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [], "bing_rss:TimeoutError:temporary"
        return [_item("https://example.test/recovered", "recovered")], ""

    payload = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: provider == "bing_rss",
        monotonic=_Clock(),
    ).search_exact("query")

    assert calls == 2
    assert payload["status"] == "ok"


def test_fault_injection_bad_providers_do_not_starve_healthy_provider() -> None:
    """A timeout + B challenge must not stop the runtime from reaching C."""

    clock = _ManualClock(0.0)

    def call(provider: str, query: str, limit: int, timeout: float):
        clock.advance(timeout)  # every attempt consumes its full attempt timeout
        if provider == "searxng":
            return [], "searxng:TimeoutError:timed out"
        if provider == "duckduckgo_html":
            return [], "duckduckgo_html:challenge"
        return [_item("https://example.test/bing", "bing")], ""

    payload = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: True,
        monotonic=clock,
        provider_timeout_seconds=6.0,
    ).search_exact("query", deadline=30.0)

    # The aggregate provider budget (6s) bounds each provider's whole lifetime:
    # searxng spends 6s on one attempt and does not get a second one;
    # bing_rss succeeds after 6s; duckduckgo_html challenges after 6s.
    # Total 18s < 30s stage deadline.
    assert clock.value == 18.0
    assert payload["status"] == "partial"
    assert [item["url"] for item in payload["results"]] == [
        "https://example.test/bing"
    ]
    by_provider = {item["provider"]: item for item in payload["provider_outcomes"]}
    assert by_provider["searxng"]["status"] == "failed"
    assert by_provider["searxng"]["reason"] == "timeout"
    assert by_provider["searxng"]["attempts"] == 1
    assert by_provider["bing_rss"]["status"] == "ok"
    assert by_provider["duckduckgo_html"]["status"] == "failed"
    assert by_provider["duckduckgo_html"]["reason"] == "challenge"
    assert by_provider["duckduckgo_html"]["attempts"] == 1


def test_deadline_prevents_bad_provider_from_consuming_whole_stage() -> None:
    clock = _ManualClock(0.0)
    calls: list[str] = []

    def call(provider: str, query: str, limit: int, timeout: float):
        calls.append(provider)
        clock.advance(timeout)
        return [], "searxng:TimeoutError:timed out"

    payload = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: True,
        monotonic=clock,
        provider_timeout_seconds=6.0,
    ).search_exact("query", deadline=8.0)

    # The aggregate provider budget (6s) bounds each provider's WHOLE lifetime,
    # so a bad provider can no longer burn two full attempts: searxng spends its
    # 6s once, bing_rss is capped to the 2s left by the 8s stage deadline, and
    # the remaining provider is skipped instead of eating the stage.
    assert calls == ["searxng", "bing_rss"]
    assert clock.value == 8.0
    assert payload["status"] == "partial"
    assert payload["reason"] == "providers_partially_failed_without_results"
    statuses = [item["status"] for item in payload["provider_outcomes"]]
    assert statuses == ["failed", "failed", "skipped"]


def test_challenge_opens_circuit_and_skips_provider_on_later_queries() -> None:
    calls: list[tuple[str, str]] = []

    def call(provider: str, query: str, limit: int, timeout: float):
        calls.append((provider, query))
        if provider == "searxng":
            return [], "searxng:challenge"
        return [_item(f"https://example.test/{query}", query)], ""

    search = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: True,
        monotonic=_Clock(),
        provider_timeout_seconds=6.0,
    )

    first = search.search_exact("q1")
    assert first["status"] == "partial"
    searxng_first = next(
        item for item in first["provider_outcomes"] if item["provider"] == "searxng"
    )
    assert searxng_first["status"] == "failed"
    assert searxng_first["reason"] == "challenge"
    assert searxng_first["attempts"] == 1

    calls.clear()
    second = search.search_exact("q2")
    assert ("searxng", "q2") not in calls
    searxng_second = next(
        item for item in second["provider_outcomes"] if item["provider"] == "searxng"
    )
    assert searxng_second["status"] == "skipped"
    assert searxng_second["reason"] == "skipped_provider_degraded"
    assert searxng_second["attempts"] == 0
    assert search.degraded_providers() == ("searxng",)


def test_429_is_not_retried_and_opens_circuit() -> None:
    calls: list[str] = []

    def call(provider: str, query: str, limit: int, timeout: float):
        calls.append(provider)
        return [], "searxng:http_status:429"

    search = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: provider == "searxng",
        monotonic=_Clock(),
        provider_timeout_seconds=6.0,
    )
    payload = search.search_exact("q1")

    assert calls == ["searxng"]
    outcome = payload["provider_outcomes"][0]
    assert outcome["status"] == "failed"
    assert outcome["reason"] == "http_status:429"
    assert outcome["attempts"] == 1
    assert search.degraded_providers() == ("searxng",)


def test_timeout_failure_opens_circuit_for_later_queries() -> None:
    calls: list[str] = []

    def call(provider: str, query: str, limit: int, timeout: float):
        calls.append(provider)
        return [], "searxng:TimeoutError:timed out"

    search = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: provider == "searxng",
        monotonic=_Clock(),
        provider_timeout_seconds=6.0,
    )
    search.search_exact("q1")
    assert calls == ["searxng", "searxng"]  # transient retry once, then circuit opens

    calls.clear()
    payload = search.search_exact("q2")
    assert calls == []
    assert payload["provider_outcomes"][0]["reason"] == "skipped_provider_degraded"


def test_empty_response_does_not_open_circuit() -> None:
    calls: list[str] = []

    def call(provider: str, query: str, limit: int, timeout: float):
        calls.append(provider)
        return [], "searxng:empty_response"

    search = ResearchProviderSearch(
        provider_call=call,
        provider_enabled=lambda provider: provider == "searxng",
        monotonic=_Clock(),
        provider_timeout_seconds=6.0,
    )
    first = search.search_exact("q1")
    assert first["provider_outcomes"][0]["status"] == "empty"
    assert search.degraded_providers() == ()

    search.search_exact("q2")
    assert calls == ["searxng", "searxng"]
