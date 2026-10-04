from __future__ import annotations

import threading
import time

from src.web.discovery import rank_candidates
from src.web.tool_gateway import GeneralWebGateway


def item(url, title="Python 3.14 release", provider="bing_rss"):
    return {"url": url, "title": title, "snippet": "", "providers": [provider]}


def test_weak_bing_does_not_block_ddg_and_official_scoped_results_win(monkeypatch):
    monkeypatch.setattr("src.web.tool_gateway.searxng_enabled", lambda: False)
    gateway = GeneralWebGateway()
    monkeypatch.setattr(gateway, "_search_bing_rss", lambda *_: (
        [item("https://python.org/", "Python"), item("https://python.org.evil.test/release")], ""))
    monkeypatch.setattr(gateway, "_search_duckduckgo", lambda *_: (
        [item("https://www.python.org/downloads/release/python-3140/", provider="duckduckgo_html")], ""))
    result = gateway.search_exact("site:python.org Python 3.14", max_results=12)
    assert result["providers_attempted"] == ["bing_rss", "duckduckgo_html"]
    assert result["results"][0]["url"].endswith("python-3140/")
    assert len(result["provider_stats"]) == 2
    assert all("evil" not in row["url"] for row in result["results"])


def test_dedup_preserves_both_providers_without_collapsing_distinct_queries():
    rows = rank_candidates([item("https://python.org/release?utm_source=bing"),
                            item("https://python.org/release", provider="duckduckgo_html"),
                            item("https://python.org/release?id=2")], "Python 3.14", 12)
    assert len(rows) == 2
    assert rows[0]["providers"] == ["bing_rss", "duckduckgo_html"]


def test_primary_timeout_preserves_rescue_and_late_result_cannot_mutate_payload(monkeypatch):
    monkeypatch.setattr("src.web.tool_gateway.searxng_enabled", lambda: True)
    # Fast unit clock bound, avoiding slow real providers.
    monkeypatch.setattr("src.web.tool_gateway._env_float", lambda name, *args, **kw: .08 if "TOTAL" in name else .04)
    release = threading.Event()
    started = threading.Event()

    def blocked(*args, **kwargs):
        started.set()
        release.wait(1)
        return [{"title": "late", "link": "https://late.test/body"}]

    monkeypatch.setattr("src.web.tool_gateway.search_searxng", blocked)
    gateway = GeneralWebGateway()
    monkeypatch.setattr(gateway, "_search_bing_rss", lambda *_: ([item("https://python.org/release")], ""))
    monkeypatch.setattr(gateway, "_search_duckduckgo", lambda *_: ([], "duckduckgo_html:challenge"))
    begin = time.monotonic()
    try:
        payload = gateway.search_exact("Python 3.14")
        assert started.is_set()
        assert time.monotonic() - begin < .3
        assert payload["results"][0]["url"] == "https://python.org/release"
        snapshot = repr(payload)
    finally:
        release.set()
    time.sleep(.02)
    assert repr(payload) == snapshot
    assert "late.test" not in snapshot
    assert "searxng:search_budget_exhausted" in payload["provider_errors"]


def test_nonversion_homepage_cannot_outrank_exact_release():
    rows = rank_candidates([item("https://python.org/", "Python"),
                            item("https://python.org/downloads/python-3140/", "Python 3.14 release"),
                            item("https://python.org/downloads/python-3130/", "Python 3.13 release")], "Python 3.14", 12)
    assert "3140" in rows[0]["url"]
