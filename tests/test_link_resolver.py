from __future__ import annotations

from src.news.link_resolver import (
    _extract_resolved_url_from_google_news_html,
    _is_google_news_url,
    resolve_news_link,
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


def test_google_news_host_detection_is_exact_enough():
    assert _is_google_news_url("https://news.google.com/rss/articles/abc")
    assert not _is_google_news_url("https://evilnews.google.com/rss/articles/abc")


def test_resolve_news_link_does_not_return_unsafe_target():
    wrapped = "https://news.example/redirect?url=http%3A%2F%2F127.0.0.1%2Fadmin"

    assert resolve_news_link(wrapped) == wrapped
