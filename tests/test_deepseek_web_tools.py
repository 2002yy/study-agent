"""Offline contract tests for opt-in, separately billed DeepSeek Search/Fetch."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from src.web import deepseek_web_tools, tool_gateway
from src.web.tool_gateway import GeneralWebGateway


@pytest.fixture(autouse=True)
def no_paid_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    for kind in ("SEARCH", "FETCH"):
        monkeypatch.delenv(f"WEB_DEEPSEEK_{kind}_ENABLED", raising=False)
        monkeypatch.delenv(f"WEB_DEEPSEEK_{kind}_MAX_REQUESTS", raising=False)
    monkeypatch.setattr(deepseek_web_tools, "_used_requests", {"search": 0, "fetch": 0})


def _search_payload() -> dict:
    return {
        "results": [
            {
                "title": "  SQLite WAL details ",
                "url": "https://sqlite.org/wal.html",
                "snippet": "Short text",
                "summary": "Useful longer context on checkpointing",
                "date": "2026-11-01T00:00:00Z",
                "rerank_score": 2.8,
            },
            {"title": "internal", "url": "http://127.0.0.1/secrets", "summary": "x"},
        ]
    }


def test_default_search_has_no_network_or_paid_activity(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("WEB_DEEPSEEK_SEARCH_MAX_REQUESTS", "2")
    monkeypatch.setattr(
        deepseek_web_tools, "urlopen", lambda *a, **kw: pytest.fail("network called")
    )
    result, error = deepseek_web_tools.search_deepseek("SQLite WAL", 5, 2)
    assert result == []
    assert error == "deepseek_search:disabled"
    assert deepseek_web_tools._used_requests["search"] == 0


def test_enabled_but_no_explicit_cap_still_never_calls_network(monkeypatch):
    monkeypatch.setenv("WEB_DEEPSEEK_SEARCH_ENABLED", "true")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(
        deepseek_web_tools, "urlopen", lambda *a, **kw: pytest.fail("network called")
    )
    _, error = deepseek_web_tools.search_deepseek("SQLite WAL", 5, 2)
    assert error == "deepseek_search:request_cap_disabled"


def test_search_contract_and_cap_use_no_live_api(monkeypatch):
    monkeypatch.setenv("WEB_DEEPSEEK_SEARCH_ENABLED", "true")
    monkeypatch.setenv("WEB_DEEPSEEK_SEARCH_MAX_REQUESTS", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return json.dumps(_search_payload()).encode("utf-8")

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(deepseek_web_tools, "urlopen", fake_urlopen)
    rows, error = deepseek_web_tools.search_deepseek(
        "SQLite WAL",
        5,
        3.0,
        original_question="SQLite WAL 为什么长读会阻止检查点？",
    )
    assert error == ""
    assert len(rows) == 1
    assert rows[0]["url"] == "https://sqlite.org/wal.html"
    assert rows[0]["snippet"] == "Useful longer context on checkpointing"
    assert rows[0]["source"] == "DeepSeek Search"
    request, timeout = requests[0]
    assert request.full_url == "https://api.deepseek.com/v1/tools/search"
    assert timeout == 3.0
    sent = json.loads(request.data)
    assert sent == {
        "query": "SQLite WAL",
        "count": 5,
        "need_content": False,
        "ori_question": "SQLite WAL 为什么长读会阻止检查点？",
    }
    assert request.get_header("Authorization") == "Bearer test-key"
    _, denied = deepseek_web_tools.search_deepseek("second", 5, 3)
    assert denied == "deepseek_search:request_cap_exhausted"
    assert len(requests) == 1


def test_request_cap_is_atomic_across_concurrent_searches(monkeypatch):
    monkeypatch.setenv("WEB_DEEPSEEK_SEARCH_ENABLED", "true")
    monkeypatch.setenv("WEB_DEEPSEEK_SEARCH_MAX_REQUESTS", "3")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return b'{"results":[]}'

    monkeypatch.setattr(deepseek_web_tools, "urlopen", lambda *_a, **_kw: FakeResponse())
    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(
            executor.map(
                lambda _i: deepseek_web_tools.search_deepseek("test", 3, 2),
                range(12),
            )
        )
    assert sum(error == "" for _rows, error in outcomes) == 3
    assert sum(error.endswith("request_cap_exhausted") for _rows, error in outcomes) == 9
    assert deepseek_web_tools._used_requests["search"] == 3


def test_empty_failure_and_status_never_expose_remote_error_content(monkeypatch):
    monkeypatch.setenv("WEB_DEEPSEEK_SEARCH_ENABLED", "true")
    monkeypatch.setenv("WEB_DEEPSEEK_SEARCH_MAX_REQUESTS", "3")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-key")

    def forbidden(_request, timeout):
        raise HTTPError("https://api.deepseek.com", 402, "secret-key", None, None)

    monkeypatch.setattr(deepseek_web_tools, "urlopen", forbidden)
    _, error = deepseek_web_tools.search_deepseek("query", 5, 2)
    assert error == "deepseek_search:http_status:402"
    monkeypatch.setattr(
        deepseek_web_tools, "_request_json", lambda *_: ({"results": []}, "")
    )
    assert deepseek_web_tools.search_deepseek("query", 5, 2) == ([], "")
    monkeypatch.setattr(
        deepseek_web_tools, "_request_json", lambda *_: ({"bad": []}, "")
    )
    assert deepseek_web_tools.search_deepseek("query", 5, 2)[1] == (
        "deepseek_search:invalid_response_shape"
    )


def test_fetch_refuses_private_urls_before_network(monkeypatch):
    monkeypatch.setenv("WEB_DEEPSEEK_FETCH_ENABLED", "true")
    monkeypatch.setenv("WEB_DEEPSEEK_FETCH_MAX_REQUESTS", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(
        deepseek_web_tools, "urlopen", lambda *a, **kw: pytest.fail("network called")
    )
    page, error = deepseek_web_tools.fetch_deepseek(
        "http://localhost/private", max_chars=1000, timeout=2
    )
    assert page is None and error == "deepseek_fetch:unsafe_url"
    assert deepseek_web_tools._used_requests["fetch"] == 0
    _, error = deepseek_web_tools.fetch_deepseek(
        "https://example.org/document?access_token=sensitive",
        max_chars=1000,
        timeout=2,
    )
    assert error == "deepseek_fetch:unsafe_url"
    assert deepseek_web_tools._used_requests["fetch"] == 0
    for secret_url in (
        "https://example.org/document?session_id=sensitive",
        "https://example.org/document?code=oauth-code",
        "https://example.org/document?X-Amz-Credential=sensitive",
        "https://example.org/document#access_token=fragment-secret",
        "https://[invalid/document",
    ):
        _, error = deepseek_web_tools.fetch_deepseek(
            secret_url, max_chars=1000, timeout=2,
        )
        assert error == "deepseek_fetch:unsafe_url"
        assert deepseek_web_tools._used_requests["fetch"] == 0


def test_fetch_return_is_bounded_and_source_url_not_rewritten(monkeypatch):
    monkeypatch.setattr(
        deepseek_web_tools, "_request_json",
        lambda *_args, **_kwargs: ({"title": "Article", "content": "x" * 30_000}, ""),
    )
    page, error = deepseek_web_tools.fetch_deepseek(
        "https://example.org/article", max_chars=750, timeout=2
    )
    assert error == ""
    assert page == {"title": "Article", "content": "x" * 750}


def test_gateway_normal_fallback_never_adds_deepseek(monkeypatch):
    monkeypatch.setattr(tool_gateway, "searxng_enabled", lambda: False)
    monkeypatch.setattr(
        GeneralWebGateway, "_search_bing_rss",
        staticmethod(
            lambda *args: ([{"title": "bing", "url": "https://example.org/a"}], "")
        ),
    )
    monkeypatch.setattr(
        GeneralWebGateway, "_search_deepseek",
        staticmethod(lambda *args: pytest.fail("DeepSeek called while disabled")),
    )
    payload = GeneralWebGateway().search_exact("question")
    assert payload["providers_attempted"] == ["bing_rss"]


def test_gateway_opt_in_deepseek_first_and_failed_provider_fallback(monkeypatch):
    monkeypatch.setenv("WEB_DEEPSEEK_SEARCH_ENABLED", "true")
    monkeypatch.setattr(tool_gateway, "searxng_enabled", lambda: False)
    calls = []

    def search(_query, _limit, _timeout):
        calls.append("deepseek")
        return [], "deepseek_search:http_status:402"

    def bing(_query, _limit, _timeout):
        calls.append("bing")
        return [{"title": "bing", "url": "https://example.org/a"}], ""

    monkeypatch.setattr(GeneralWebGateway, "_search_deepseek", staticmethod(search))
    monkeypatch.setattr(GeneralWebGateway, "_search_bing_rss", staticmethod(bing))
    payload = GeneralWebGateway(search_strategy="deepseek_first").search_exact(
        "question"
    )
    assert calls == ["deepseek", "bing"]
    assert payload["status"] == "ok"
    assert payload["provider_outcomes"][0]["provider"] == "deepseek"
    assert payload["provider_outcomes"][0]["status"] == "failed"
    assert payload["provider_outcomes"][0]["reason"] == "http_status"
    assert payload["results"][0]["url"] == "https://example.org/a"


def test_gateway_read_fetch_uses_last_resort_only_when_opted_in(monkeypatch):
    from src.web.research import official_resolver

    monkeypatch.setattr(
        official_resolver, "read_official_metadata", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(
        tool_gateway, "fetch_article_read_result",
        lambda url, **_kw: SimpleNamespace(
            ok=False, requested_url=url, reason="page_unavailable"
        ),
    )
    called = []

    def fetch(url, *, max_chars, timeout):
        called.append(url)
        return {"title": "Page", "content": "Readable evidence"}, ""

    monkeypatch.setattr(tool_gateway, "fetch_deepseek", fetch)
    gateway = GeneralWebGateway()
    without = gateway.read("https://example.org/article", timeout=4)
    assert without["ok"] is False
    assert called == []
    monkeypatch.setenv("WEB_DEEPSEEK_FETCH_ENABLED", "true")
    with_fetch = gateway.read("https://example.org/article", timeout=4)
    assert called == ["https://example.org/article"]
    assert with_fetch["ok"] is True
    assert with_fetch["method"] == "deepseek_fetch"
    assert with_fetch["content"] == "Readable evidence"


def test_gateway_successful_normal_read_never_pays_for_fetch(monkeypatch):
    from src.web.research import official_resolver

    monkeypatch.setenv("WEB_DEEPSEEK_FETCH_ENABLED", "true")
    monkeypatch.setattr(
        official_resolver, "read_official_metadata", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(
        tool_gateway,
        "fetch_article_read_result",
        lambda url, **_kw: SimpleNamespace(
            ok=True,
            requested_url=url,
            final_url=url,
            method="direct",
            text="Existing reader works",
            author="",
        ),
    )
    monkeypatch.setattr(
        tool_gateway,
        "fetch_deepseek",
        lambda *_a, **_kw: pytest.fail("Fetch must not run after success"),
    )
    result = GeneralWebGateway().read("https://example.org/article", timeout=4)
    assert result["ok"] is True
    assert result["method"] == "direct"
