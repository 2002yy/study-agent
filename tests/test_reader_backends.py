from __future__ import annotations

from src.news.readers.jina_reader import build_jina_reader_url
from src.news.readers.local_reader import read_html_locally


def test_local_reader_extracts_html_text():
    html = """
    <html><body><article>
    <h1>Example</h1>
    <p>This is a useful paragraph about Python URL parsing. It has enough words to pass the article cleaner and should be extracted by a local backend.</p>
    <p>Another useful paragraph explains redirects, canonical URLs, and query parameters for a news pipeline implementation.</p>
    <p>The final paragraph adds more context so the text is long enough and not mistaken for navigation or login noise.</p>
    </article></body></html>
    """

    result = read_html_locally(html, url="https://example.com/story", max_chars=5000)

    assert result.ok
    assert result.method.startswith("local_")
    assert "Python URL parsing" in result.text


def test_jina_reader_url_builder_rejects_unsafe_urls():
    assert build_jina_reader_url("file:///etc/passwd") == ""
    assert build_jina_reader_url("http://localhost:8501") == ""
    assert build_jina_reader_url("http://127.0.0.1:8501") == ""


def test_jina_reader_url_builder_accepts_public_urls():
    reader_url = build_jina_reader_url("https://example.com/story?a=1&utm_source=x")

    assert reader_url.startswith("https://r.jina.ai/https://example.com/story")


def test_article_fetcher_does_not_call_jina_by_default(monkeypatch):
    from src.news import article_fetcher
    from src.news.readers.base import ReaderResult

    calls: list[str] = []

    monkeypatch.delenv("NEWS_ENABLE_JINA_READER", raising=False)
    monkeypatch.setattr(article_fetcher, "_ARTICLE_CACHE", {})
    monkeypatch.setattr(article_fetcher, "_is_fetchable_article_url", lambda url: True)
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_html_payload",
        lambda url, timeout, max_bytes: ("<html><body>too short</body></html>", url, "text/html", ""),
    )
    monkeypatch.setattr(
        article_fetcher,
        "read_html_locally",
        lambda html, url, max_chars: ReaderResult(),
    )
    monkeypatch.setattr(
        article_fetcher,
        "read_with_jina_reader",
        lambda url, timeout, max_chars: calls.append(url) or ReaderResult(text="jina text", method="jina_reader"),
    )

    text, method = article_fetcher.fetch_article_text_with_method("https://example.com/story")

    assert text == ""
    assert method == ""
    assert calls == []


def test_article_fetcher_calls_jina_when_enabled(monkeypatch):
    from src.news import article_fetcher
    from src.news.readers.base import ReaderResult

    calls: list[str] = []

    monkeypatch.setenv("NEWS_ENABLE_JINA_READER", "true")
    monkeypatch.setattr(article_fetcher, "_ARTICLE_CACHE", {})
    monkeypatch.setattr(article_fetcher, "_is_fetchable_article_url", lambda url: True)
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_html_payload",
        lambda url, timeout, max_bytes: ("<html><body>too short</body></html>", url, "text/html", ""),
    )
    monkeypatch.setattr(
        article_fetcher,
        "read_html_locally",
        lambda html, url, max_chars: ReaderResult(),
    )
    monkeypatch.setattr(
        article_fetcher,
        "read_with_jina_reader",
        lambda url, timeout, max_chars: calls.append(url) or ReaderResult(text="jina text", method="jina_reader"),
    )

    text, method = article_fetcher.fetch_article_text_with_method("https://example.com/story")

    assert text == "jina text"
    assert method == "jina_reader"
    assert calls == ["https://example.com/story"]
