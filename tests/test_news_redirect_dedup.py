from __future__ import annotations


def test_fetch_news_items_dedupes_by_canonical_url_after_resolution(monkeypatch):
    from src.news import rss_fetcher

    now_ts = 1_800_000_000.0
    raw_items = [
        {
            "title": "Same article A",
            "source": "Google News",
            "published_at": "2026-05-30 10:00",
            "published_timestamp": now_ts,
            "link": "https://news.example/redirect?url=https%3A%2F%2Fexample.com%2Fstory%3Futm_source%3Dg",
            "resolved_link": "",
            "canonical_url": "",
            "domain": "",
            "resolution_status": "pending",
            "_sort_ts": now_ts,
        },
        {
            "title": "Same article B",
            "source": "Bing News",
            "published_at": "2026-05-30 10:01",
            "published_timestamp": now_ts + 1,
            "link": "https://bing.example/redirect?u=https%3A%2F%2Fexample.com%2Fstory%3Futm_campaign%3Db",
            "resolved_link": "",
            "canonical_url": "",
            "domain": "",
            "resolution_status": "pending",
            "_sort_ts": now_ts + 1,
        },
        {
            "title": "Different article",
            "source": "Docs",
            "published_at": "2026-05-30 10:02",
            "published_timestamp": now_ts + 2,
            "link": "https://docs.python.org/3/library/urllib.parse.html?utm_source=x",
            "resolved_link": "",
            "canonical_url": "",
            "domain": "",
            "resolution_status": "pending",
            "_sort_ts": now_ts + 2,
        },
    ]

    monkeypatch.setattr(rss_fetcher, "_NEWS_CACHE", {})
    monkeypatch.setattr(
        rss_fetcher,
        "_fetch_query_news_items",
        lambda query_text, max_items=10: [dict(item) for item in raw_items],
    )

    items = rss_fetcher.fetch_news_items(
        query_text="python url parsing",
        max_items=3,
        resolve_top_n=3,
    )

    canonical_urls = [item["canonical_url"] for item in items]
    assert canonical_urls.count("https://example.com/story") == 1
    assert "https://docs.python.org/3/library/urllib.parse.html" in canonical_urls
    assert all("domain" in item for item in items)
    assert all("resolution_status" in item for item in items)
    assert all("domain_policy" in item for item in items)


def test_fetch_news_items_filters_hard_blocked_login_pages(monkeypatch):
    from src.news import rss_fetcher

    now_ts = 1_800_000_000.0
    raw_items = [
        {
            "title": "Login page",
            "source": "Bad Source",
            "published_at": "2026-05-30 10:00",
            "published_timestamp": now_ts,
            "link": "https://accounts.example.com/login?next=/story",
            "resolved_link": "",
            "canonical_url": "",
            "domain": "",
            "resolution_status": "pending",
            "_sort_ts": now_ts,
        },
        {
            "title": "Python docs",
            "source": "Docs",
            "published_at": "2026-05-30 10:02",
            "published_timestamp": now_ts + 2,
            "link": "https://docs.python.org/3/library/urllib.parse.html",
            "resolved_link": "",
            "canonical_url": "",
            "domain": "",
            "resolution_status": "pending",
            "_sort_ts": now_ts + 2,
        },
    ]

    monkeypatch.setattr(rss_fetcher, "_NEWS_CACHE", {})
    monkeypatch.setattr(
        rss_fetcher,
        "_fetch_query_news_items",
        lambda query_text, max_items=10: [dict(item) for item in raw_items],
    )

    items = rss_fetcher.fetch_news_items(
        query_text="python url parsing",
        max_items=5,
        resolve_top_n=5,
    )

    assert len(items) == 1
    assert items[0]["domain"] == "docs.python.org"


def test_source_block_includes_url_metadata():
    from src.news.digest import format_news_source_block

    source_block = format_news_source_block(
        "python url parsing",
        [
            {
                "title": "urllib parse docs",
                "source": "Docs",
                "published_at": "2026-05-30 10:00",
                "article_status": "正文已读｜Trafilatura",
                "link": "https://news.example/redirect?url=https%3A%2F%2Fdocs.python.org%2F3%2Flibrary%2Furllib.parse.html",
                "resolved_link": "https://docs.python.org/3/library/urllib.parse.html",
                "canonical_url": "https://docs.python.org/3/library/urllib.parse.html",
                "domain": "docs.python.org",
                "resolution_status": "resolved",
                "redirect_hops": [
                    {"source": "input", "status": "received", "is_safe": True},
                    {"source": "query_parameter", "status": "extracted", "is_safe": True},
                ],
                "domain_policy": {
                    "blocked": False,
                    "reasons": ["prefer-tech-domain"],
                },
            }
        ],
    )

    assert "域名：docs.python.org｜解析：resolved" in source_block
    assert "证据：article_text" in source_block
    assert "跳转链：2 hops" in source_block
    assert "域名策略：prefer-tech-domain" in source_block
    assert "原始链接：news.example" in source_block
    assert "真实链接：docs.python.org" in source_block
