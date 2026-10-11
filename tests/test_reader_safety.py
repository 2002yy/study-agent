"""Reader-Safety-2: the article reader is fail-closed on security refusals."""

from __future__ import annotations

import pytest

from src.news import article_fetcher as af
from src.web.safe_http import SafeFetchRefusal


@pytest.fixture(autouse=True)
def _clear_cache():
    af._ARTICLE_CACHE.clear()
    yield
    af._ARTICLE_CACHE.clear()


def _allow(monkeypatch):
    monkeypatch.setattr(af, "_is_fetchable_article_url", lambda url: True)


def test_security_refusal_is_fail_closed(monkeypatch):
    _allow(monkeypatch)

    def refuse(*_a, **_k):
        raise SafeFetchRefusal("unsafe_target")

    fired: list[str] = []
    monkeypatch.setattr(af, "safe_fetch_result", refuse)
    monkeypatch.setattr(af, "_try_firecrawl", lambda *a, **k: fired.append("fc") or ("", ""))
    monkeypatch.setattr(af, "_try_jina", lambda *a, **k: fired.append("jina") or ("", ""))
    result = af.fetch_article_read_result("https://example.org/a")
    assert result.ok is False
    assert result.reason == "security_refused:unsafe_target"
    assert fired == []  # a refusal never reaches a weaker fallback


def test_truncation_is_reported_as_failure(monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setattr(
        af, "safe_fetch_result",
        lambda *a, **k: (_ for _ in ()).throw(SafeFetchRefusal("response_too_large")),
    )
    result = af.fetch_article_read_result("https://example.org/b")
    assert result.ok is False and "response_too_large" in result.reason


def test_normal_read_keeps_extraction(monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setattr(
        af, "safe_fetch_result",
        lambda *a, **k: {
            "final_url": "https://example.org/c",
            "content_type": "text/html",
            "content_encoding": "",
            "raw": b"<html><body>hi</body></html>",
            "text": "<html>",
            "truncated": False,
        },
    )

    class Local:
        ok = True
        text = "body text"
        method = "local_trafilatura"
        author = "A"

    monkeypatch.setattr(af, "read_html_locally", lambda *a, **k: Local())
    result = af.fetch_article_read_result("https://example.org/c")
    assert result.ok is True and result.text == "body text"
    assert result.final_url == "https://example.org/c"
