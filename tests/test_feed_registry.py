from __future__ import annotations

import json

from src.news.feed_registry import (
    load_feed_registry,
    load_feed_state,
    record_feed_result,
    registered_feed_urls,
)


def test_load_feed_registry_falls_back_to_defaults(tmp_path):
    feeds = load_feed_registry(tmp_path / "missing.json")

    assert any(feed.name == "Google News" for feed in feeds)
    assert any(feed.requires_query for feed in feeds)


def test_load_feed_registry_reads_custom_file(tmp_path):
    path = tmp_path / "feeds.json"
    path.write_text(
        json.dumps(
            {
                "feeds": [
                    {
                        "name": "Example Feed",
                        "url": "https://example.com/rss?q={query}",
                        "requires_query": True,
                        "filter_by_query": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    feeds = load_feed_registry(path)

    assert len(feeds) == 1
    assert feeds[0].resolved_url("python url") == "https://example.com/rss?q=python+url"


def test_registered_feed_urls_resolves_default_query_sources():
    urls = registered_feed_urls("python url")

    assert any(source == "Google News" and "python+url" in url for source, url, _ in urls)
    assert any(source == "Bing News" and "python+url" in url for source, url, _ in urls)
    assert any(
        source == "Bing News" and "/search?" in url and "format=rss" in url
        for source, url, _ in urls
    )


def test_record_feed_result_persists_health(tmp_path):
    path = tmp_path / "state.json"
    record_feed_result(
        "Example Feed",
        "https://example.com/rss",
        ok=False,
        error=ValueError("bad xml"),
        etag='"abc"',
        modified="Wed, 03 Jun 2026 10:00:00 GMT",
        path=path,
    )

    state = load_feed_state(path)
    rows = list(state.health.values())

    assert rows[0].source == "Example Feed"
    assert rows[0].status == "error"
    assert rows[0].error_type == "ValueError"
    assert rows[0].message == "bad xml"
    assert rows[0].etag == '"abc"'
    assert rows[0].modified == "Wed, 03 Jun 2026 10:00:00 GMT"
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {"health"}
