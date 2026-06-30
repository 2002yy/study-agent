from __future__ import annotations

import json

from src.news.search_sources.searxng_source import (
    build_searxng_search_url,
    get_last_searxng_error,
)


class _FakeResponse:
    def __init__(self, payload: bytes, content_type: str = "application/json"):
        self._payload = payload
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _limit: int = -1) -> bytes:
        return self._payload


def test_build_searxng_search_url_rejects_missing_or_unsafe_base_url():
    assert build_searxng_search_url("python", "") == ""
    assert build_searxng_search_url("python", "file:///tmp") == ""
    assert build_searxng_search_url("python", "http://localhost:8080") == ""


def test_build_searxng_search_url_uses_json_format():
    url = build_searxng_search_url("python urllib.parse", "https://search.example.com")

    assert url.startswith("https://search.example.com/search?")
    assert "format=json" in url
    assert "q=python+urllib.parse" in url
    assert "categories=news" in url


def test_search_searxng_disabled_by_default(monkeypatch):
    from src.news.search_sources import searxng_source

    calls: list[str] = []
    monkeypatch.delenv("NEWS_ENABLE_SEARXNG", raising=False)
    monkeypatch.setenv("SEARXNG_BASE_URL", "https://search.example.com")
    monkeypatch.setattr(
        searxng_source,
        "urlopen",
        lambda req, timeout: calls.append(req.full_url) or _FakeResponse(b"{}"),
    )

    assert searxng_source.search_searxng("python") == []
    assert calls == []


def test_search_searxng_parses_json_results(monkeypatch):
    from src.news.search_sources import searxng_source

    payload = json.dumps(
        {
            "results": [
                {
                    "title": "Python docs",
                    "url": "https://docs.python.org/3/library/urllib.parse.html",
                    "content": "urllib.parse documentation",
                    "engine": "duckduckgo",
                    "score": 2.5,
                },
                {
                    "title": "Unsafe local",
                    "url": "http://127.0.0.1:8501",
                    "content": "should be ignored",
                },
            ]
        }
    ).encode("utf-8")

    monkeypatch.setenv("NEWS_ENABLE_SEARXNG", "true")
    monkeypatch.setenv("SEARXNG_BASE_URL", "https://search.example.com")
    monkeypatch.setattr(
        searxng_source,
        "urlopen",
        lambda req, timeout: _FakeResponse(payload),
    )

    items = searxng_source.search_searxng("python", max_results=5)

    assert len(items) == 1
    assert items[0]["title"] == "Python docs"
    assert items[0]["source"] == "SearXNG/duckduckgo"
    assert items[0]["link"] == "https://docs.python.org/3/library/urllib.parse.html"
    assert items[0]["search_excerpt"] == "urllib.parse documentation"
    assert items[0]["_search_score"] == 2.5


def test_search_searxng_sorts_results_by_provider_score(monkeypatch):
    from src.news.search_sources import searxng_source

    payload = json.dumps(
        {
            "results": [
                {"title": "Low", "url": "https://example.com/low", "score": 0.1},
                {"title": "High", "url": "https://example.com/high", "score": 3.0},
            ]
        }
    ).encode("utf-8")
    monkeypatch.setenv("NEWS_ENABLE_SEARXNG", "true")
    monkeypatch.setenv("SEARXNG_BASE_URL", "https://search.example.com")
    monkeypatch.setattr(
        searxng_source,
        "urlopen",
        lambda req, timeout: _FakeResponse(payload),
    )

    items = searxng_source.search_searxng("python", max_results=5)

    assert [item["title"] for item in items] == ["High", "Low"]


def test_search_searxng_preserves_nonzero_published_timestamp(monkeypatch):
    from src.news.search_sources import searxng_source

    payload = json.dumps(
        {
            "results": [
                {
                    "title": "Dated",
                    "url": "https://example.com/dated",
                    "publishedDate": "2026-06-30T12:34:56+08:00",
                }
            ]
        }
    ).encode("utf-8")
    monkeypatch.setenv("NEWS_ENABLE_SEARXNG", "true")
    monkeypatch.setenv("SEARXNG_BASE_URL", "https://search.example.com")
    monkeypatch.setattr(
        searxng_source,
        "urlopen",
        lambda req, timeout: _FakeResponse(payload),
    )

    item = searxng_source.search_searxng("dated")[0]

    assert item["published_timestamp"] > 0
    assert item["_sort_ts"] == item["published_timestamp"]


def test_search_searxng_non_json_fails_soft(monkeypatch):
    from src.news.search_sources import searxng_source

    monkeypatch.setenv("NEWS_ENABLE_SEARXNG", "true")
    monkeypatch.setenv("SEARXNG_BASE_URL", "https://search.example.com")
    monkeypatch.setattr(
        searxng_source,
        "urlopen",
        lambda req, timeout: _FakeResponse(b"<html>forbidden</html>", "text/html"),
    )

    assert searxng_source.search_searxng("python") == []


def test_rss_fetcher_includes_searxng_items_when_enabled(monkeypatch):
    from src.news import rss_fetcher

    monkeypatch.setattr(
        rss_fetcher,
        "search_searxng",
        lambda query_text, max_results, **kwargs: [
            {
                "title": "Python docs",
                "source": "SearXNG/test",
                "published_at": "Today",
                "published_timestamp": 0.0,
                "link": "https://docs.python.org/3/library/urllib.parse.html",
                "resolved_link": "",
                "canonical_url": "",
                "domain": "",
                "resolution_status": "pending",
                "_sort_ts": 0.0,
            }
        ],
    )
    monkeypatch.setattr(rss_fetcher, "DOMESTIC_NEWS_FEEDS", ())
    monkeypatch.setattr(
        rss_fetcher,
        "_fetch_rss_items_from_url",
        lambda *args, **kwargs: [],
    )

    items = rss_fetcher._fetch_query_news_items("python", max_items=5)

    assert len(items) == 1
    assert items[0]["source"] == "SearXNG/test"


def test_get_last_searxng_error_records_content_type_mismatch(monkeypatch):
    from src.news.search_sources import searxng_source

    monkeypatch.setenv("NEWS_ENABLE_SEARXNG", "true")
    monkeypatch.setenv("SEARXNG_BASE_URL", "https://search.example.com")
    monkeypatch.setattr(
        searxng_source,
        "urlopen",
        lambda req, timeout: _FakeResponse(b"not json", "text/html"),
    )

    result = searxng_source.search_searxng("python")
    assert result == []
    error = get_last_searxng_error()
    assert "text/html" in error
    assert "Unexpected Content-Type" in error


def test_get_last_searxng_error_records_exception(monkeypatch):
    from src.news.search_sources import searxng_source

    monkeypatch.setenv("NEWS_ENABLE_SEARXNG", "true")
    monkeypatch.setenv("SEARXNG_BASE_URL", "https://search.example.com")

    monkeypatch.setattr(
        searxng_source,
        "urlopen",
        lambda req, timeout: (_ for _ in ()).throw(TimeoutError("connect timeout")),
    )

    result = searxng_source.search_searxng("python")
    assert result == []
    error = get_last_searxng_error()
    assert "TimeoutError" in error
    assert "connect timeout" in error


def test_get_last_searxng_error_cleared_on_success(monkeypatch):
    from src.news.search_sources import searxng_source

    payload = json.dumps(
        {
            "results": [
                {
                    "title": "Test",
                    "url": "https://example.com",
                    "content": "",
                    "engine": "test",
                }
            ]
        }
    ).encode("utf-8")

    monkeypatch.setenv("NEWS_ENABLE_SEARXNG", "true")
    monkeypatch.setenv("SEARXNG_BASE_URL", "https://search.example.com")
    monkeypatch.setattr(
        searxng_source,
        "urlopen",
        lambda req, timeout: _FakeResponse(payload),
    )

    # First trip fails
    monkeypatch.setattr(
        searxng_source,
        "urlopen",
        lambda req, timeout: _FakeResponse(b"<html>", "text/html"),
    )
    searxng_source.search_searxng("python")
    assert get_last_searxng_error() != ""

    # Second trip succeeds — error must be cleared
    monkeypatch.setattr(
        searxng_source,
        "urlopen",
        lambda req, timeout: _FakeResponse(payload),
    )
    searxng_source.search_searxng("python")
    assert get_last_searxng_error() == ""
