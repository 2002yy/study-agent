from __future__ import annotations

from typing import Any

from src.web import tool_gateway
from src.web.search_router import DUAL, FAST, route_search
from src.web.tool_gateway import GeneralWebGateway


def _outcome(results: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "results": results,
        "provider_errors": [],
        "providers_attempted": ["searxng"],
        "provider_outcomes": [
            {"provider": "searxng", "status": "ok", "reason": "results_found",
             "result_count": len(results)},
        ],
    }


def _row(title: str, url: str) -> dict[str, str]:
    return {"title": title, "url": url, "snippet": title}


def test_multi_constraint_cjk_queries_route_to_both_channels() -> None:
    assert route_search("劳动合同 试用期 最长 规定") == DUAL
    assert route_search("法国大革命 起因 三级会议") == DUAL
    assert route_search("PostgreSQL MVCC 多版本并发控制") == DUAL
    assert route_search("Notion Obsidian 对比 笔记软件") == DUAL


def test_english_or_domain_constrained_queries_stay_on_the_fast_path() -> None:
    assert route_search("FastAPI background task best practice") == FAST
    assert route_search("site:sqlite.org Sqlite WAL") == FAST
    assert route_search("SQLite 为什么快") == FAST
    assert route_search("") == FAST


def test_browser_rows_lead_and_duplicate_urls_are_dropped(monkeypatch) -> None:
    monkeypatch.setenv("WEB_SEARCH_DUAL_CHANNEL", "on")
    monkeypatch.setattr(
        tool_gateway,
        "_browser_search",
        lambda query, limit, timeout: (
            [_row("试用期规定", "https://example.gov/a"),
             _row("劳动合同法", "https://example.com/b")],
            "",
        ),
    )
    gateway = GeneralWebGateway(search_strategy="fallback")
    monkeypatch.setattr(
        GeneralWebGateway,
        "_search_single",
        lambda self, query, limit: _outcome(
            [_row("旧结果", "https://example.com/b"),
             _row("劳动百科", "https://baike.example/c")]
        ),
    )

    outcome = gateway.search_exact("劳动合同 试用期 最长 规定", max_results=5)

    assert [row["url"] for row in outcome["results"]] == [
        "https://example.com/b",
        "https://baike.example/c",
        "https://example.gov/a",
    ]
    assert outcome["results"][2]["source"] == "browser_bing"
    browser = [
        row for row in outcome["provider_outcomes"]
        if row["provider"] == "browser_bing"
    ]
    assert browser and browser[0]["status"] == "ok"
    assert browser[0]["result_count"] == 2
    assert "browser_bing" in outcome["providers_attempted"]
    assert outcome["dual_channel"]["route"] == DUAL


def test_a_failed_browser_lane_is_diagnostic_not_fatal(monkeypatch) -> None:
    monkeypatch.setenv("WEB_SEARCH_DUAL_CHANNEL", "on")
    monkeypatch.setattr(
        tool_gateway,
        "_browser_search",
        lambda query, limit, timeout: ([], "browse:browser_timeout"),
    )
    gateway = GeneralWebGateway(search_strategy="fallback")
    monkeypatch.setattr(
        GeneralWebGateway,
        "_search_single",
        lambda self, query, limit: _outcome([_row("旧结果", "https://example.com/a")]),
    )

    outcome = gateway.search_exact("劳动合同 试用期 最长 规定", max_results=5)

    assert [row["url"] for row in outcome["results"]] == ["https://example.com/a"]
    browser = [
        row for row in outcome["provider_outcomes"]
        if row["provider"] == "browser_bing"
    ]
    assert browser and browser[0]["status"] == "failed"
    assert browser[0]["reason"] == "timeout"
    assert any("browser_bing:browse:browser_timeout" == error
               for error in outcome["provider_errors"])


def test_browser_lane_rescues_an_empty_fast_channel(monkeypatch) -> None:
    """When the aggregate returns nothing, the browser rows still make a search."""

    monkeypatch.setenv("WEB_SEARCH_DUAL_CHANNEL", "on")
    monkeypatch.setattr(
        tool_gateway,
        "_browser_search",
        lambda query, limit, timeout: (
            [_row("试用期最长", "https://example.gov/a")], ""
        ),
    )
    gateway = GeneralWebGateway(search_strategy="fallback")
    monkeypatch.setattr(
        GeneralWebGateway,
        "_search_single",
        lambda self, query, limit: _outcome([]),
    )

    outcome = gateway.search_exact("劳动合同 试用期 最长 规定", max_results=5)

    assert outcome["status"] == "ok"
    assert [row["url"] for row in outcome["results"]] == ["https://example.gov/a"]


def test_the_lane_does_not_start_when_disabled_or_irrelevant(monkeypatch) -> None:
    calls: list[str] = []

    def fail(query: str, limit: int, timeout: float):
        calls.append(query)
        raise AssertionError("browser lane must not start")

    monkeypatch.setattr(tool_gateway, "_browser_search", fail)
    gateway = GeneralWebGateway(search_strategy="fallback")
    monkeypatch.setattr(
        GeneralWebGateway,
        "_search_single",
        lambda self, query, limit: _outcome([]),
    )

    monkeypatch.delenv("WEB_SEARCH_DUAL_CHANNEL", raising=False)
    gateway.search_exact("劳动合同 试用期 最长 规定", max_results=5)
    monkeypatch.setenv("WEB_SEARCH_DUAL_CHANNEL", "on")
    gateway.search_exact("FastAPI background task best practice", max_results=5)
    gateway.search_exact("site:sqlite.org Sqlite WAL", max_results=5)

    assert calls == []
