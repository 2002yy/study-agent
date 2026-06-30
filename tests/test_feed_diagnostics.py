from __future__ import annotations

import threading


class _FakeResponse:
    def __init__(self, payload: bytes):
        self.headers = {
            "ETag": '"abc"',
            "Last-Modified": "Wed, 03 Jun 2026 10:00:00 GMT",
        }
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._payload


def test_fetch_query_news_items_keeps_feed_warnings_for_partial_success(monkeypatch):
    from src.news import rss_fetcher

    def fake_searxng(*args, **kwargs):
        raise RuntimeError("searx down")

    def fake_fetch(feed_url, max_items=10, source_fallback="", query_text=""):
        if source_fallback == "Google News":
            raise ValueError("Malformed RSS feed: Google News: bad xml")
        return [
            {
                "title": "Good item",
                "source": source_fallback,
                "published_at": "2026-06-03 10:00",
                "published_timestamp": 1_800_000_000.0,
                "link": "https://example.com/good",
                "resolved_link": "",
                "canonical_url": "",
                "domain": "",
                "resolution_status": "pending",
                "_sort_ts": 1_800_000_000.0,
            }
        ]

    monkeypatch.setattr(rss_fetcher, "_NEWS_CACHE", {})
    monkeypatch.setattr(rss_fetcher, "search_searxng", fake_searxng)
    monkeypatch.setattr(rss_fetcher, "_fetch_rss_items_from_url", fake_fetch)

    items = rss_fetcher._fetch_query_news_items("python url", max_items=3)
    warnings = rss_fetcher.get_last_feed_warnings()

    assert items
    assert any(item["source"] == "SearXNG" for item in warnings)
    assert any(item["source"] == "Google News" for item in warnings)
    assert all("error_type" in item and "message" in item for item in warnings)


def test_fetch_query_news_items_records_feed_health(monkeypatch):
    from src.news import rss_fetcher

    recorded = []

    def fake_record(
        source,
        url,
        *,
        ok,
        item_count=0,
        error=None,
        etag="",
        modified="",
    ):
        recorded.append(
            {
                "source": source,
                "ok": ok,
                "item_count": item_count,
                "error_type": type(error).__name__ if error else "",
                "etag": etag,
                "modified": modified,
            }
        )

    def fake_fetch(feed_url, max_items=10, source_fallback="", query_text=""):
        if source_fallback == "Google News":
            raise ValueError("bad xml")
        return [
            {
                "title": "Good item",
                "source": source_fallback,
                "published_at": "2026-06-03 10:00",
                "published_timestamp": 1_800_000_000.0,
                "link": "https://example.com/good",
                "resolved_link": "",
                "canonical_url": "",
                "domain": "",
                "resolution_status": "pending",
                "_sort_ts": 1_800_000_000.0,
            }
        ]

    monkeypatch.setattr(rss_fetcher, "_NEWS_CACHE", {})
    monkeypatch.setattr(rss_fetcher, "search_searxng", lambda *a, **k: [])
    monkeypatch.setattr(rss_fetcher, "_fetch_rss_items_from_url", fake_fetch)
    monkeypatch.setattr(rss_fetcher, "record_feed_result", fake_record)

    rss_fetcher._fetch_query_news_items("python url", max_items=3)

    assert any(
        item["source"] == "Google News"
        and item["ok"] is False
        and item["error_type"] == "ValueError"
        for item in recorded
    )
    assert any(
        item["source"] == "Bing News" and item["ok"] is True and item["item_count"] == 1
        for item in recorded
    )


def test_fetch_rss_items_records_response_cache_headers(monkeypatch):
    from src.news import rss_fetcher

    payload = b"""
    <rss><channel>
      <item>
        <title>Python URL parsing</title>
        <link>https://docs.python.org/3/library/urllib.parse.html</link>
        <pubDate>Wed, 03 Jun 2026 10:00:00 GMT</pubDate>
      </item>
    </channel></rss>
    """

    monkeypatch.setattr(rss_fetcher, "_LAST_FEED_METADATA", {})
    monkeypatch.setattr(rss_fetcher, "urlopen", lambda req, timeout=15: _FakeResponse(payload))

    items = rss_fetcher._fetch_rss_items_from_url(
        "https://example.com/rss",
        source_fallback="Example Feed",
    )

    assert items[0]["title"] == "Python URL parsing"
    assert rss_fetcher._LAST_FEED_METADATA["https://example.com/rss"] == {
        "etag": '"abc"',
        "modified": "Wed, 03 Jun 2026 10:00:00 GMT",
    }


def test_search_sources_start_concurrently(monkeypatch):
    from src.news import rss_fetcher

    barrier = threading.Barrier(3)

    def item(source: str, url: str) -> dict:
        return {
            "title": f"{source} result",
            "source": source,
            "published_at": "2026-06-30 10:00",
            "link": url,
            "_sort_ts": 1_800_000_000.0,
        }

    def fake_searxng(*args, **kwargs):
        barrier.wait(timeout=2)
        return [item("SearXNG", "https://search.example/story")]

    def fake_fetch(feed_url, max_items=10, source_fallback="", query_text=""):
        barrier.wait(timeout=2)
        return [item(source_fallback, feed_url)]

    monkeypatch.setattr(rss_fetcher, "search_searxng", fake_searxng)
    monkeypatch.setattr(
        rss_fetcher,
        "registered_feed_urls",
        lambda query: [
            ("Feed A", "https://a.example/rss", False),
            ("Feed B", "https://b.example/rss", False),
        ],
    )
    monkeypatch.setattr(rss_fetcher, "_fetch_rss_items_from_url", fake_fetch)

    results = rss_fetcher._fetch_query_news_items("result", max_items=5)

    assert {result["source"] for result in results} == {
        "SearXNG",
        "Feed A",
        "Feed B",
    }
