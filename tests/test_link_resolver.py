from __future__ import annotations

from src.news.link_resolver import (
    _extract_resolved_url_from_google_news_html,
    _is_google_news_url,
    resolve_news_link,
    resolve_news_link_result,
)


def test_google_news_html_extracts_data_url_with_entities():
    html = """
    <html>
      <body>
        <a data-n-au="https://example.com/story?a=1&amp;b=2">read</a>
      </body>
    </html>
    """

    assert (
        _extract_resolved_url_from_google_news_html(html)
        == "https://example.com/story?a=1&b=2"
    )


def test_google_news_html_extracts_percent_encoded_url():
    html = """
    <script>
      window.raw = "https%3A%2F%2Fpublisher.example%2Farticle%3Fid%3D42";
    </script>
    """

    assert (
        _extract_resolved_url_from_google_news_html(html)
        == "https://publisher.example/article?id=42"
    )


def test_google_news_html_rejects_unsafe_extracted_target():
    html = """
    <script>
      {"targetUrl":"http://127.0.0.1/admin"}
    </script>
    """

    assert _extract_resolved_url_from_google_news_html(html) == ""


def test_google_news_html_skips_favicon_before_article_link():
    html = """
    <html>
      <head><link rel="icon" href="https://publisher.example/favicon.ico"></head>
      <body><a href="https://publisher.example/news/real-story">read</a></body>
    </html>
    """

    assert (
        _extract_resolved_url_from_google_news_html(html)
        == "https://publisher.example/news/real-story"
    )


def test_google_news_host_detection_is_exact_enough():
    assert _is_google_news_url("https://news.google.com/rss/articles/abc")
    assert not _is_google_news_url("https://evilnews.google.com/rss/articles/abc")


def test_resolve_news_link_does_not_return_unsafe_target():
    wrapped = "https://news.example/redirect?url=http%3A%2F%2F127.0.0.1%2Fadmin"

    assert resolve_news_link(wrapped) == wrapped


def test_resolve_news_link_result_records_query_parameter_hops():
    wrapped = "https://news.example/redirect?url=https%3A%2F%2Fexample.com%2Fstory"

    result = resolve_news_link_result(wrapped)

    assert result.resolution_status == "resolved"
    assert result.resolved_url == "https://example.com/story"
    assert [hop.source for hop in result.hops] == ["input", "query_parameter"]
    assert result.hops[-1].location == "https://example.com/story"
    assert result.hops[-1].reason == "redirect_query_parameter"
    assert result.metadata.redirect_hops == result.hops


def test_resolve_news_link_result_records_blocked_unsafe_hop():
    wrapped = "https://news.example/redirect?url=http%3A%2F%2F127.0.0.1%2Fadmin"

    result = resolve_news_link_result(wrapped)

    assert result.resolution_status == "unsafe"
    assert result.resolved_url == "http://127.0.0.1/admin"
    assert result.hops[-1].source == "query_parameter"
    assert result.hops[-1].status == "blocked"
    assert result.hops[-1].is_safe is False
    assert result.hops[-1].reason == "unsafe_redirect_target"
