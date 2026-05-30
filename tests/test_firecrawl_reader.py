from __future__ import annotations

import json

from src.news.readers.firecrawl_reader import build_firecrawl_scrape_url


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


def test_build_firecrawl_scrape_url():
    assert build_firecrawl_scrape_url("http://127.0.0.1:3002") == "http://127.0.0.1:3002/v1/scrape"
    assert build_firecrawl_scrape_url("https://firecrawl.example.com/") == "https://firecrawl.example.com/v1/scrape"


def test_firecrawl_reader_rejects_unsafe_target_url():
    from src.news.readers.firecrawl_reader import read_with_firecrawl

    result = read_with_firecrawl(
        "http://127.0.0.1:8501/private",
        base_url="https://firecrawl.example.com",
    )

    assert not result.ok
    assert result.error == "unsafe-or-empty-url"


def test_firecrawl_reader_parses_nested_markdown(monkeypatch):
    from src.news.readers import firecrawl_reader

    markdown = (
        "Firecrawl extracted article text about Python URL parsing. "
        "It explains redirects, canonical URLs, query parameters, and practical extraction behavior. "
        "This sentence extends the content enough to pass the cleaner. "
        "The final sentence confirms that markdown output can be normalized into a ReaderResult."
    )
    payload = json.dumps({"data": {"markdown": markdown}}).encode("utf-8")
    requests: list[object] = []

    def fake_urlopen(req, timeout):
        requests.append(req)
        return _FakeResponse(payload)

    monkeypatch.setattr(firecrawl_reader, "urlopen", fake_urlopen)

    result = firecrawl_reader.read_with_firecrawl(
        "https://example.com/story",
        base_url="https://firecrawl.example.com",
        api_key="test-key",
    )

    assert result.ok
    assert result.method == "firecrawl"
    assert "Python URL parsing" in result.text
    assert requests[0].full_url == "https://firecrawl.example.com/v1/scrape"
    assert requests[0].headers["Authorization"] == "Bearer test-key"


def test_firecrawl_reader_non_json_fails_soft(monkeypatch):
    from src.news.readers import firecrawl_reader

    monkeypatch.setattr(
        firecrawl_reader,
        "urlopen",
        lambda req, timeout: _FakeResponse(b"<html>nope</html>", "text/html"),
    )

    result = firecrawl_reader.read_with_firecrawl(
        "https://example.com/story",
        base_url="https://firecrawl.example.com",
    )

    assert not result.ok
    assert result.error == "non-json-firecrawl-response"


def test_article_fetcher_does_not_call_firecrawl_by_default(monkeypatch):
    from src.news import article_fetcher
    from src.news.readers.base import ReaderResult

    calls: list[str] = []

    monkeypatch.delenv("NEWS_ENABLE_FIRECRAWL_READER", raising=False)
    monkeypatch.delenv("NEWS_ENABLE_JINA_READER", raising=False)
    monkeypatch.setattr(article_fetcher, "_ARTICLE_CACHE", {})
    monkeypatch.setattr(article_fetcher, "_is_fetchable_article_url", lambda url: True)
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_html_payload",
        lambda url, timeout, max_bytes: ("<html><body>too short</body></html>", url),
    )
    monkeypatch.setattr(
        article_fetcher,
        "read_html_locally",
        lambda html, url, max_chars: ReaderResult(),
    )
    monkeypatch.setattr(
        article_fetcher,
        "read_with_firecrawl",
        lambda url, timeout, max_chars: calls.append(url) or ReaderResult(text="firecrawl text", method="firecrawl"),
    )

    text, method = article_fetcher.fetch_article_text_with_method("https://example.com/story")

    assert text == ""
    assert method == ""
    assert calls == []


def test_article_fetcher_uses_firecrawl_before_jina_when_enabled(monkeypatch):
    from src.news import article_fetcher
    from src.news.readers.base import ReaderResult

    calls: list[str] = []

    monkeypatch.setenv("NEWS_ENABLE_FIRECRAWL_READER", "true")
    monkeypatch.setenv("NEWS_ENABLE_JINA_READER", "true")
    monkeypatch.setattr(article_fetcher, "_ARTICLE_CACHE", {})
    monkeypatch.setattr(article_fetcher, "_is_fetchable_article_url", lambda url: True)
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_html_payload",
        lambda url, timeout, max_bytes: ("<html><body>too short</body></html>", url),
    )
    monkeypatch.setattr(
        article_fetcher,
        "read_html_locally",
        lambda html, url, max_chars: ReaderResult(),
    )
    monkeypatch.setattr(
        article_fetcher,
        "read_with_firecrawl",
        lambda url, timeout, max_chars: calls.append("firecrawl") or ReaderResult(text="firecrawl text", method="firecrawl"),
    )
    monkeypatch.setattr(
        article_fetcher,
        "read_with_jina_reader",
        lambda url, timeout, max_chars: calls.append("jina") or ReaderResult(text="jina text", method="jina_reader"),
    )

    text, method = article_fetcher.fetch_article_text_with_method("https://example.com/story")

    assert text == "firecrawl text"
    assert method == "firecrawl"
    assert calls == ["firecrawl"]
