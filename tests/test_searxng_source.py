from __future__ import annotations

import json
from types import SimpleNamespace

from src.news.search_sources.searxng_source import build_searxng_search_url


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
        lambda query_text, max_results: [
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
