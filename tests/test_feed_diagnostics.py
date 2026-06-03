from __future__ import annotations


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
