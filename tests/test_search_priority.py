"""Default search order: DeepSeek, then the paired browser, then free engines."""

from __future__ import annotations

import pytest

from src.web import tool_gateway
from src.web.tool_gateway import GeneralWebGateway


def _row(url: str) -> dict[str, str]:
    return {"title": url, "url": url, "snippet": ""}


@pytest.fixture()
def providers(monkeypatch):
    """All five providers are available and record their call order."""

    calls: list[tuple[str, float]] = []

    def make(name: str, rows):
        def search(_query, _limit, timeout):
            calls.append((name, timeout))
            return rows(), ""

        return staticmethod(search)

    monkeypatch.setattr(tool_gateway, "searxng_enabled", lambda: True)
    monkeypatch.setattr(tool_gateway, "_browse_read_available", lambda: True)
    monkeypatch.setenv("WEB_DEEPSEEK_SEARCH_ENABLED", "true")
    monkeypatch.setenv("WEB_DEEPSEEK_SEARCH_MAX_REQUESTS", "10")
    monkeypatch.setenv("WEB_ENABLE_BING_RSS", "true")
    monkeypatch.setenv("WEB_ENABLE_DUCKDUCKGO", "true")
    return calls, make


def _install(monkeypatch, providers, rows, timeout_seen=None):
    calls, make = providers
    monkeypatch.setattr(GeneralWebGateway, "_search_deepseek", make("deepseek", lambda: rows["deepseek"]))
    monkeypatch.setattr(GeneralWebGateway, "_search_browse", make("browse", lambda: rows["browse"]))
    monkeypatch.setattr(GeneralWebGateway, "_search_searxng", make("searxng", lambda: rows["searxng"]))
    monkeypatch.setattr(GeneralWebGateway, "_search_bing_rss", make("bing_rss", lambda: rows["bing_rss"]))
    monkeypatch.setattr(GeneralWebGateway, "_search_duckduckgo", make("duckduckgo_html", lambda: rows["duckduckgo_html"]))
    return calls


def test_default_order_is_deepseek_browse_then_free_engines(monkeypatch, providers):
    calls = _install(monkeypatch, providers, {
        "deepseek": [], "browse": [], "searxng": [],
        "bing_rss": [], "duckduckgo_html": [],
    })

    payload = GeneralWebGateway().search_exact("question", max_results=5)

    assert [name for name, _timeout in calls] == [
        "deepseek", "browse", "searxng", "bing_rss", "duckduckgo_html",
    ]
    assert payload["search_strategy"] == "research"


def test_thin_deepseek_results_still_let_browse_run(monkeypatch, providers):
    calls = _install(monkeypatch, providers, {
        "deepseek": [_row("https://a.example/1")],
        "browse": [_row("https://b.example/1")],
        "searxng": [], "bing_rss": [], "duckduckgo_html": [],
    })

    _payload = GeneralWebGateway().search_exact("question", max_results=5)

    assert [name for name, _timeout in calls][:2] == ["deepseek", "browse"]


def test_sufficient_deepseek_results_stop_before_browse(monkeypatch, providers):
    calls = _install(monkeypatch, providers, {
        "deepseek": [_row(f"https://a.example/{i}") for i in range(3)],
        "browse": [_row("https://b.example/1")],
        "searxng": [], "bing_rss": [], "duckduckgo_html": [],
    })

    _payload = GeneralWebGateway().search_exact("question", max_results=5)

    assert [name for name, _timeout in calls] == ["deepseek"]


def test_deepseek_failure_falls_through_to_browse(monkeypatch, providers):
    calls = _install(monkeypatch, providers, {
        "deepseek": [],
        "browse": [_row(f"https://b.example/{i}") for i in range(3)],
        "searxng": [], "bing_rss": [], "duckduckgo_html": [],
    })

    _payload = GeneralWebGateway().search_exact("question", max_results=5)

    assert [name for name, _timeout in calls] == ["deepseek", "browse"]


def test_deepseek_keeps_a_reserve_for_the_later_providers(monkeypatch, providers):
    monkeypatch.setenv("WEB_RESEARCH_SEARCH_TOTAL_SECONDS", "12")
    calls = _install(monkeypatch, providers, {
        "deepseek": [], "browse": [], "searxng": [],
        "bing_rss": [], "duckduckgo_html": [],
    })

    GeneralWebGateway().search_exact("question", max_results=5)

    deepseek_timeout = dict(calls)["deepseek"]
    assert deepseek_timeout <= 8.1  # 12s total minus the 4s reserve


def test_explicit_fallback_strategy_keeps_its_legacy_order(monkeypatch, providers):
    calls = _install(monkeypatch, providers, {
        "deepseek": [], "browse": [], "searxng": [],
        "bing_rss": [_row("https://b.example/1")],
        "duckduckgo_html": [],
    })

    GeneralWebGateway(search_strategy="fallback").search_exact("question")

    assert [name for name, _timeout in calls][0] == "searxng"
    assert "deepseek" not in [name for name, _timeout in calls]
