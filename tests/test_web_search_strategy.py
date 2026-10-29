"""The E2 search strategy: ask both engines, merge, then rank.

The fallback strategy answers with whichever engine replied first. These tests
pin the properties the Quality-0 candidate arm needs from a *different* path:
both providers are really attempted, duplicates are counted rather than silently
absorbed, the final order is produced by the production scorer, and the default
production behaviour is untouched.
"""

from __future__ import annotations

import pytest

from src.web import tool_gateway
from src.web.tool_gateway import GeneralWebGateway


def _row(title: str, url: str, snippet: str = "") -> dict[str, str]:
    return {"title": title, "url": url, "snippet": snippet, "source": "test"}


@pytest.fixture(autouse=True)
def _no_searxng(monkeypatch):
    monkeypatch.setattr(tool_gateway, "searxng_enabled", lambda: False)


def _patch_providers(monkeypatch, bing, ddg):
    monkeypatch.setattr(
        GeneralWebGateway, "_search_bing_rss", staticmethod(lambda *a, **k: bing())
    )
    monkeypatch.setattr(
        GeneralWebGateway, "_search_duckduckgo", staticmethod(lambda *a, **k: ddg())
    )


def test_the_default_strategy_is_the_unchanged_fallback():
    """Production must not switch paths because the experiment exists."""

    assert GeneralWebGateway().search_strategy == "fallback"


def test_an_unknown_strategy_is_rejected():
    with pytest.raises(ValueError, match="unknown search strategy"):
        GeneralWebGateway(search_strategy="merge-sort")


def test_fallback_still_stops_at_the_first_engine_that_answers(monkeypatch):
    calls: list[str] = []

    def bing():
        calls.append("bing")
        return [_row("python asyncio timeout", "https://a.example/1")], ""

    def ddg():
        calls.append("ddg")
        return [_row("other", "https://b.example/2")], ""

    _patch_providers(monkeypatch, bing, ddg)

    payload = GeneralWebGateway().search_exact("python asyncio timeout", max_results=5)

    assert calls == ["bing"]
    assert [item["url"] for item in payload["results"]] == ["https://a.example/1"]
    assert "merged_count" not in payload


def test_merge_asks_both_engines_even_when_the_first_answers(monkeypatch):
    calls: list[str] = []

    def bing():
        calls.append("bing")
        return [_row("python asyncio timeout", "https://a.example/1")], ""

    def ddg():
        calls.append("ddg")
        return [_row("asyncio timeout notes", "https://b.example/2")], ""

    _patch_providers(monkeypatch, bing, ddg)

    payload = GeneralWebGateway(search_strategy="merge").search_exact(
        "python asyncio timeout", max_results=5
    )

    assert calls == ["bing", "ddg"]
    assert payload["providers_attempted"] == ["bing_rss", "duckduckgo_html"]
    assert payload["merged_count"] == 2
    assert {item["url"] for item in payload["results"]} == {
        "https://a.example/1",
        "https://b.example/2",
    }


def test_merge_counts_a_url_seen_by_both_engines_as_one_duplicate(monkeypatch):
    shared = _row("python asyncio timeout", "https://same.example/1")

    def bing():
        return [shared, _row("python asyncio", "https://a.example/1")], ""

    def ddg():
        return [shared, _row("asyncio tip", "https://b.example/2")], ""

    _patch_providers(monkeypatch, bing, ddg)

    payload = GeneralWebGateway(search_strategy="merge").search_exact(
        "python asyncio timeout", max_results=10
    )

    assert payload["merged_count"] == 4
    # One URL appeared twice; the other two are unique. Counting occurrences
    # (2) would overstate how much either engine contributed.
    assert payload["duplicate_count"] == 1
    assert payload["provider_counts"] == {"bing_rss": 2, "duckduckgo_html": 2}
    assert len(payload["results"]) == 3


def test_merge_ranks_a_more_relevant_second_provider_first(monkeypatch):
    def bing():
        return [_row("cooking pasta", "https://b.example/2", "pasta water salt")], ""

    def ddg():
        return [
            _row(
                "Python asyncio timeout handling",
                "https://a.example/1",
                "python asyncio timeout handling guide",
            )
        ], ""

    _patch_providers(monkeypatch, bing, ddg)

    payload = GeneralWebGateway(search_strategy="merge").search_exact(
        "python asyncio timeout", max_results=5
    )

    assert payload["ranked_urls"] == ["https://a.example/1", "https://b.example/2"]
    assert [item["url"] for item in payload["results"]] == payload["ranked_urls"]


def test_merge_keeps_results_when_one_provider_fails(monkeypatch):
    def bing():
        return [], "bing_rss:TimeoutError:timed out"

    def ddg():
        return [_row("asyncio timeout", "https://b.example/2")], ""

    _patch_providers(monkeypatch, bing, ddg)

    payload = GeneralWebGateway(search_strategy="merge").search_exact(
        "asyncio timeout", max_results=5
    )

    assert payload["status"] == "ok"
    assert "bing_rss:TimeoutError:timed out" in payload["provider_errors"]
    assert [item["url"] for item in payload["results"]] == ["https://b.example/2"]


def test_merge_records_a_disabled_provider_instead_of_pretending(monkeypatch):
    calls: list[str] = []

    def bing():
        calls.append("bing")
        return [], ""

    def ddg():
        calls.append("ddg")
        return [_row("asyncio timeout", "https://b.example/2")], ""

    _patch_providers(monkeypatch, bing, ddg)
    monkeypatch.setenv("WEB_ENABLE_BING_RSS", "0")

    payload = GeneralWebGateway(search_strategy="merge").search_exact(
        "asyncio timeout", max_results=5
    )

    assert calls == ["ddg"]
    assert "bing_rss:provider_disabled" in payload["provider_errors"]
    assert payload["provider_counts"] == {"duckduckgo_html": 1}
    # Only the engine that was actually called may appear as attempted.
    assert payload["providers_attempted"] == ["duckduckgo_html"]
    assert payload["providers_skipped"] == [
        {"provider": "bing_rss", "reason": "provider_disabled"}
    ]


def test_the_trace_reaches_the_variant_level_api(monkeypatch):
    def bing():
        return [_row("python asyncio timeout", "https://a.example/1")], ""

    def ddg():
        return [_row("python asyncio", "https://b.example/2")], ""

    _patch_providers(monkeypatch, bing, ddg)

    payload = GeneralWebGateway(search_strategy="merge").search_detailed(
        "python asyncio timeout", max_results=5
    )

    assert "bing_rss" in payload["providers_attempted"]
    assert "duckduckgo_html" in payload["providers_attempted"]
    assert payload["search_strategy"] == "merge"
    assert payload["merged_count"] >= 2
    assert payload["ranked_urls"]
    assert payload["adopted_query"] == "python asyncio timeout"


class _FakeNormalization:
    def __init__(self, raw_query: str, variants: list[str]) -> None:
        self.raw_query = raw_query
        self.query_variants = variants

    def to_dict(self) -> dict[str, object]:
        return {"query": self.raw_query, "query_variants": self.query_variants}


def test_a_later_variant_cannot_be_described_by_the_first_variant_trace(monkeypatch):
    """The trace must describe the variant whose results were actually returned."""

    monkeypatch.setattr(
        tool_gateway,
        "normalize_web_query",
        lambda query, now=None: _FakeNormalization(
            "python asyncio timeout",
            ["python asyncio timeout (missing)", "python asyncio timeout"],
        ),
    )

    seen: list[str] = []

    def bing():
        return [], ""

    def ddg():
        seen.append("ddg")
        if len(seen) == 1:
            return [], ""  # the first variant finds nothing
        return [_row("python asyncio timeout", "https://a.example/1")], ""

    _patch_providers(monkeypatch, bing, ddg)

    payload = GeneralWebGateway(search_strategy="merge").search_detailed(
        "python asyncio timeout", max_results=5
    )

    assert payload["status"] == "ok"
    assert payload["adopted_query"] == "python asyncio timeout"
    assert payload["ranked_urls"] == [item["url"] for item in payload["results"]]
    assert [trace["query"] for trace in payload["merge_traces"]] == [
        "python asyncio timeout (missing)",
        "python asyncio timeout",
    ]
    # The first trace is kept as evidence, but it is not the one describing the
    # delivered results.
    assert payload["merge_traces"][0]["ranked_urls"] == []
    assert payload["merge_traces"][1]["ranked_urls"] == ["https://a.example/1"]


def test_domain_filtering_updates_the_delivered_ranking(monkeypatch):
    """A filtered-out URL must not survive in the trace the caller stores."""

    def bing():
        return [
            _row("python asyncio timeout", "https://a.example/1"),
            _row("python asyncio timeout copy", "https://other.example/2"),
        ], ""

    def ddg():
        return [], ""

    _patch_providers(monkeypatch, bing, ddg)

    payload = GeneralWebGateway(search_strategy="merge").search_exact(
        "site:a.example python asyncio timeout", max_results=5
    )

    assert payload["domain_filtered_count"] == 1
    assert payload["ranked_urls"] == ["https://a.example/1"]
    assert [item["url"] for item in payload["results"]] == payload["ranked_urls"]


def test_no_results_leaves_no_aggregate_that_pretends_a_merge_succeeded(monkeypatch):
    def bing():
        return [], "bing_rss:TimeoutError:timed out"

    def ddg():
        return [], "duckduckgo_html:HTTPError:503"

    _patch_providers(monkeypatch, bing, ddg)

    payload = GeneralWebGateway(search_strategy="merge").search_detailed(
        "python asyncio timeout", max_results=5
    )

    assert payload["status"] == "unavailable"
    assert payload["adopted_query"] is None
    assert payload["ranked_urls"] == []
    assert payload["providers_attempted"] == []
    assert "merged_count" not in payload
