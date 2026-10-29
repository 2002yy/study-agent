"""Direct regressions for search-reading failures seen in Search-1/2."""

from __future__ import annotations

from src.news import article_fetcher
from src.web.source_assessment import assess_sources


def test_english_answer_page_is_not_discarded_for_a_chinese_query():
    selected, rejected = assess_sources(
        [{
            "title": "List of high-speed railway lines - Wikipedia",
            "url": "https://en.wikipedia.org/wiki/List_of_high-speed_railway_lines",
        }],
        canonical_query="世界 最快 高铁 运营速度 线路",
    )

    assert rejected == []
    assert selected[0]["assessment"]["directness"] == "unmatched"
    assert selected[0]["assessment"]["worth_reading"] is True


def test_transient_http_failure_is_not_cached_as_an_empty_page(monkeypatch):
    url = "https://example.com/story"
    monkeypatch.setattr(article_fetcher, "_ARTICLE_CACHE", {})
    monkeypatch.setattr(article_fetcher, "_is_fetchable_article_url", lambda _url: True)
    responses = iter([
        ("", url, "", "http_503"),
        ("", url, "text/html", ""),
    ])
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_html_payload",
        lambda *_args, **_kwargs: next(responses),
    )
    monkeypatch.setattr(
        article_fetcher,
        "_try_firecrawl",
        lambda *_args, **_kwargs: ("Recovered article facts", "fake_reader"),
    )

    first = article_fetcher.fetch_article_read_result(url)
    assert first.ok is False
    assert first.reason == "http_503"
    assert url not in article_fetcher._ARTICLE_CACHE

    second = article_fetcher.fetch_article_read_result(url)
    assert second.ok is True
    assert second.text == "Recovered article facts"
    assert article_fetcher._ARTICLE_CACHE[url][1] == "Recovered article facts"
