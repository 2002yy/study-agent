"""Offline user-facing search regressions: useful scoped results, no extra calls."""

import pytest

from src.web import tool_gateway
from src.web.tool_gateway import GeneralWebGateway


def row(url):
    return {"url": url, "title": "Python reference", "snippet": "Python documentation"}


@pytest.fixture(autouse=True)
def providers(monkeypatch):
    monkeypatch.setattr(tool_gateway, "searxng_enabled", lambda: False)
    monkeypatch.setenv("WEB_ENABLE_BING_RSS", "1")
    monkeypatch.setenv("WEB_ENABLE_DUCKDUCKGO", "1")


@pytest.mark.parametrize("strategy", ["fallback", "ddg_first"])
def test_out_of_scope_first_engine_does_not_suppress_fallback(monkeypatch, strategy):
    calls = []

    def fetch(*args):
        calls.append(args)
        url = (
            "https://unrelated.example/post"
            if len(calls) == 1
            else "https://docs.python.org/3/"
        )
        return [row(url)], ""

    monkeypatch.setattr(GeneralWebGateway, "_search_bing_rss", staticmethod(fetch))
    monkeypatch.setattr(GeneralWebGateway, "_search_duckduckgo", staticmethod(fetch))
    result = GeneralWebGateway(search_strategy=strategy).search_exact(
        "site:python.org Python"
    )
    assert result["status"] == "ok"
    assert [item["url"] for item in result["results"]] == ["https://docs.python.org/3/"]
    assert len(calls) == 2
    assert result["domain_filtered_count"] == 1


@pytest.mark.parametrize("strategy", ["fallback", "ddg_first", "merge"])
def test_search_keeps_case_sensitive_paths_and_queries(monkeypatch, strategy):
    urls = [
        "https://docs.example/Guide",
        "https://docs.example/guide",
        "https://docs.example/?q=A",
        "https://docs.example/?q=a",
    ]
    monkeypatch.setattr(
        GeneralWebGateway,
        "_search_bing_rss",
        staticmethod(lambda *a: ([row(u) for u in urls], "")),
    )
    monkeypatch.setattr(
        GeneralWebGateway,
        "_search_duckduckgo",
        staticmethod(lambda *a: ([row(u) for u in urls], "")),
    )
    result = GeneralWebGateway(search_strategy=strategy).search_exact(
        "Python reference", max_results=8
    )
    assert {item["url"] for item in result["results"]} == set(urls)


def test_merge_applies_domain_constraint_before_result_limit(monkeypatch):
    monkeypatch.setattr(
        GeneralWebGateway,
        "_search_bing_rss",
        staticmethod(lambda *a: ([row("https://other.example/")], "")),
    )
    monkeypatch.setattr(
        GeneralWebGateway,
        "_search_duckduckgo",
        staticmethod(lambda *a: ([row("https://docs.python.org/3/")], "")),
    )
    # The unrelated result ranks first; it must not consume the only delivery slot.
    monkeypatch.setattr(tool_gateway, "_rank_merged", lambda rows, query: rows)
    result = GeneralWebGateway(search_strategy="merge").search_exact(
        "site:python.org Python", max_results=1
    )
    assert result["status"] == "ok"
    assert result["ranked_urls"] == ["https://docs.python.org/3/"]
    assert result["domain_filtered_count"] == 1


@pytest.mark.parametrize("strategy", ["fallback", "ddg_first"])
def test_useful_first_engine_stops_without_speculative_requests(monkeypatch, strategy):
    calls = []

    def fetch(*args):
        calls.append(args)
        return [row("https://docs.python.org/3/")], ""

    monkeypatch.setattr(GeneralWebGateway, "_search_bing_rss", staticmethod(fetch))
    monkeypatch.setattr(GeneralWebGateway, "_search_duckduckgo", staticmethod(fetch))
    result = GeneralWebGateway(search_strategy=strategy).search_exact(
        "site:python.org Python"
    )
    assert result["status"] == "ok"
    assert len(calls) == 1


def test_searxng_off_domain_rows_continue_to_bing(monkeypatch):
    monkeypatch.setattr(tool_gateway, "searxng_enabled", lambda: True)
    monkeypatch.setattr(
        tool_gateway,
        "search_searxng",
        lambda *a, **kw: [{"title": "Python", "link": "https://other.example/"}],
    )
    monkeypatch.setattr(
        GeneralWebGateway,
        "_search_bing_rss",
        staticmethod(lambda *a: ([row("https://python.org/")], "")),
    )
    monkeypatch.setattr(
        GeneralWebGateway,
        "_search_duckduckgo",
        staticmethod(lambda *a: pytest.fail("unnecessary provider")),
    )
    result = GeneralWebGateway(search_strategy="fallback").search_exact(
        "site:python.org Python"
    )
    assert result["status"] == "ok"
    assert result["providers_attempted"] == ["searxng", "bing_rss"]


@pytest.mark.parametrize(
    "query",
    [
        "site:python.org OR site:example.org Python",
        "site:python.org -site:docs.python.org Python",
    ],
)
def test_complex_domain_queries_are_left_to_provider(monkeypatch, query):
    monkeypatch.setattr(
        GeneralWebGateway,
        "_search_duckduckgo",
        staticmethod(lambda *a: ([row("https://example.org/")], "")),
    )
    result = GeneralWebGateway(search_strategy="ddg_first").search_exact(query)
    assert result["status"] == "ok"
    assert result["domain_filtered_count"] == 0


@pytest.mark.parametrize("strategy", ["fallback", "ddg_first", "merge"])
def test_scope_rejection_does_not_bypass_shared_deadline(monkeypatch, strategy):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(tool_gateway.time, "monotonic", lambda: clock[0])
    monkeypatch.setenv("WEB_SEARCH_TOTAL_TIMEOUT_SECONDS", "3")

    def fetch(query, limit, timeout):
        calls.append(timeout)
        clock[0] += 3
        return [row("https://other.example/")], ""

    monkeypatch.setattr(GeneralWebGateway, "_search_bing_rss", staticmethod(fetch))
    monkeypatch.setattr(GeneralWebGateway, "_search_duckduckgo", staticmethod(fetch))
    result = GeneralWebGateway(search_strategy=strategy).search_exact(
        "site:python.org Python"
    )
    assert calls == [3.0]
    assert len(result["providers_attempted"]) == 1
    assert result["results"] == []
    assert any(
        "search_budget_exhausted" in error for error in result["provider_errors"]
    )


def test_host_case_and_fragment_duplicates_do_not_consume_slots(monkeypatch):
    urls = [
        "https://Docs.example/Guide#intro",
        "https://docs.example/Guide#more",
        "https://docs.example/guide",
    ]
    monkeypatch.setattr(
        GeneralWebGateway,
        "_search_duckduckgo",
        staticmethod(lambda *a: ([row(u) for u in urls], "")),
    )
    result = GeneralWebGateway(search_strategy="ddg_first").search_exact("Python")
    assert [item["url"] for item in result["results"]] == [urls[0], urls[2]]
