"""Offline controls for the free community browser/fast retrieval probe."""

from __future__ import annotations

import time
from unittest.mock import patch

from tools.probe_community_gap import CASES, ProbeCase, run
from src.web.research.facet_coverage import community_hosts_for
from src.web.tool_gateway import GeneralWebGateway


def _row(title: str, url: str) -> dict[str, str]:
    return {"title": title, "url": url, "snippet": title}


class _Gateway:
    searches: list[str] = []
    browser_hosts: list[str] = []
    reads: list[str] = []

    def search_exact(self, query: str, *, max_results: int):
        self.searches.append(query)
        time.sleep(0.04)
        return {
            "status": "ok",
            "reason": "results_found",
            "results": [_row("Notion Obsidian 对比", "https://www.v2ex.com/t/1")],
            "provider_outcomes": [{"provider": "searxng", "status": "ok"}],
        }

    def search_community_site(self, query: str, *, host: str, max_results: int):
        self.browser_hosts.append(host)
        time.sleep(0.005)
        return {
            "status": "ok",
            "reason": "results_found",
            "results": [
                _row("Notion Obsidian 对比", "https://v2ex.com/t/1"),
                _row("Notion Obsidian 用户经验", "https://www.v2ex.com/t/2"),
            ],
            "site_outcomes": [{"site": "v2ex", "status": "ok"}],
        }

    def read(self, url: str, *, max_chars: int, timeout: float):
        self.reads.append(url)
        return {"ok": True, "content": "Real readable user experience.", "url": url}


def test_all_frozen_cases_match_the_existing_verified_community_route():
    for case in CASES:
        assert community_hosts_for(case.question)[0] == case.expected_host


def test_probe_starts_both_channels_and_counts_only_novel_browser_pages():
    _Gateway.searches, _Gateway.browser_hosts, _Gateway.reads = [], [], []
    case = ProbeCase("product", CASES[0].question, CASES[0].search,
                     "v2ex.com", ("notion", "obsidian"))
    report = run((case,), gateway_factory=_Gateway, read_limit=2)
    item = report["cases"][0]

    assert item["route_ok"] is True
    assert item["return_order"] == ["browser", "fast"]
    assert _Gateway.searches == [f"{case.search} site:v2ex.com"]
    assert _Gateway.browser_hosts == ["v2ex.com"]
    assert item["channels"]["fast"]["lexical_title_snippet_hits"] == 1
    assert item["channels"]["browser"]["lexical_title_snippet_hits"] == 2
    assert item["browser_unique_urls"] == ["https://www.v2ex.com/t/2"]
    assert len(_Gateway.reads) == 2  # cross-channel duplicate was read once
    assert all(row["ok"] for row in item["reads"])
    assert report["model_calls"] == 0


def test_search_hits_are_not_reported_as_read_evidence():
    class Unreadable(_Gateway):
        def read(self, url: str, *, max_chars: int, timeout: float):
            return {"ok": False, "error_code": "blocked", "url": url}

    report = run((CASES[0],), gateway_factory=Unreadable)
    item = report["cases"][0]
    assert item["channels"]["browser"]["result_count"] == 2
    assert item["reads"] and all(not row["ok"] for row in item["reads"])
    assert all(row["content_chars"] == 0 for row in item["reads"])


def test_default_read_limit_skips_duplicate_and_reads_novel_browser_page():
    report = run((CASES[0],), gateway_factory=_Gateway, read_limit=1)
    reads = report["cases"][0]["reads"]
    assert [item["url"] for item in reads] == [
        "https://www.v2ex.com/t/1", "https://www.v2ex.com/t/2"
    ]


def test_route_mismatch_is_reported_without_any_external_calls():
    wrong = ProbeCase("wrong", CASES[0].question, "irrelevant", "reddit.com", ())

    def forbidden():
        raise AssertionError("must not create a gateway")

    report = run((wrong,), gateway_factory=forbidden)
    assert report["cases"][0]["reason"] == "unexpected_community_route"
    assert report["cases"][0]["route_ok"] is False


def test_fast_control_forces_fallback_even_when_global_mode_is_browser(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_STRATEGY", "browse_sites")
    empty = {"status": "ok", "results": []}
    with (patch.object(GeneralWebGateway, "__init__", return_value=None) as init,
          patch.object(GeneralWebGateway, "search_exact", return_value=empty),
          patch.object(GeneralWebGateway, "search_community_site", return_value=empty)):
        report = run((CASES[0],), read_limit=0)
    assert report["cases"][0]["route_ok"]
    assert init.call_args_list[0].kwargs == {"search_strategy": "fallback"}


def test_probe_refuses_paid_provider_flags_before_creating_gateways(monkeypatch):
    def forbidden():
        raise AssertionError("probe must stop before gateway construction")

    for flag in ("WEB_DEEPSEEK_SEARCH_ENABLED", "WEB_DEEPSEEK_FETCH_ENABLED"):
        monkeypatch.setenv(flag, "true")
        try:
            run((CASES[0],), gateway_factory=forbidden)
        except RuntimeError as exc:
            assert str(exc) == "community_probe_requires_deepseek_tools_disabled"
        else:
            raise AssertionError(f"probe did not reject {flag}")
        monkeypatch.delenv(flag)
