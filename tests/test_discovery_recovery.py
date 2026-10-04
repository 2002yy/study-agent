from __future__ import annotations

import threading
import time

from src.web.discovery import discovery_sufficient, pool_quality, rank_candidates
from src.web.tool_gateway import GeneralWebGateway
from src.web.research_recovery import recover_public_research, recovery_summary
from src.web.tool_evidence import evidence_tool_calls


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


def test_locale_variants_cannot_close_primary_discovery():
    rows = [item(f"https://docs.python.org/{locale}/3.14/release") for locale in ("en", "zh", "ja")]
    assert not discovery_sufficient(rows, "site:python.org Python 3.14", 12)


def test_release_intent_beats_tutorial_token_overlap():
    rows = rank_candidates([item("https://fastapi.org.cn/tutorial/", "FastAPI latest version tutorial"),
                            item("https://fastapi.tiangolo.com/release-notes/", "Release Notes")],
                           "FastAPI latest version", 24)
    assert rows[0]["url"] == "https://fastapi.tiangolo.com/release-notes/"


def test_large_tutorial_pool_without_official_source_is_insufficient():
    rows = [item(f"https://blog-{i}.test/tutorial", "FastAPI tutorial") for i in range(24)]
    quality = pool_quality(rows, "FastAPI latest version", ("fastapi.tiangolo.com",), standard=True)
    assert not quality["sufficient"]
    assert quality["unique_urls"] == 24
    assert "official_source_missing" in quality["reasons"]
    assert "weak_top_candidates" in quality["reasons"]


def test_all_degraded_providers_are_external_failure_not_missing_configuration(monkeypatch):
    monkeypatch.setattr("src.web.tool_gateway.searxng_enabled", lambda: True)
    result = GeneralWebGateway().search_exact("Python", excluded_providers=frozenset(
        {"searxng", "bing_rss", "duckduckgo_html"}))
    assert result["status"] == "unavailable"
    assert result["reason"] == "providers_degraded_for_run"
    assert result["providers_attempted"] == []


def test_adaptive_second_query_preserves_reads_for_discovered_official_release(monkeypatch):
    query = "FastAPI当前最新版本及发布日期是什么？"
    monkeypatch.setattr("src.web.tool_gateway.searxng_enabled", lambda: True)
    searx_calls = []
    monkeypatch.setattr("src.web.tool_gateway.search_searxng", lambda *args, **kwargs: searx_calls.append(args) or [])
    monkeypatch.setattr("src.web.tool_gateway.get_last_searxng_error", lambda: "CAPTCHA")
    gateway = GeneralWebGateway()
    ddg_calls = []
    limits = []

    def bing(search, limit, timeout):
        limits.append(limit)
        return ([item("https://fastapi.tiangolo.com/release-notes/", query)] if search.startswith("site:")
                else [item("https://blog.test/tutorial", "FastAPI latest version tutorial")]), ""

    monkeypatch.setattr(gateway, "_search_bing_rss", bing)
    monkeypatch.setattr(gateway, "_search_duckduckgo", lambda *args: ddg_calls.append(args) or ([], "duckduckgo_html:challenge"))
    read_urls = []

    def read(url, **kwargs):
        read_urls.append(url)
        return {"ok": True, "url": url, "content": query + " official release 0.x, dated today"}

    monkeypatch.setattr(gateway, "read", read)
    calls = recover_public_research(gateway, query, query_plan=[
        {"rq_id": "rq-version", "query": "FastAPI latest version release"},
        {"rq_id": "rq-version", "query": "site:fastapi.tiangolo.com FastAPI release"},
    ])
    assert limits == [12, 24]
    assert len(searx_calls) == len(ddg_calls) == 1
    assert read_urls == ["https://fastapi.tiangolo.com/release-notes/"]
    assert len(evidence_tool_calls(calls)) == 1
    assert recovery_summary(calls)["candidate_pool_cap"] == 25
    assert recovery_summary(calls)["limits"]["reads"] == 3
