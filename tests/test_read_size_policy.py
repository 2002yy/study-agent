"""Read-size policy: normal technical documents fit, without unbounded fetches."""

from __future__ import annotations

from src.news import article_fetcher
from src.web import safe_http


def test_document_caps_are_tiered_and_bounded():
    assert safe_http.MAX_BYTES < safe_http.MAX_BYTES_HTML < safe_http.MAX_BYTES_LARGE
    assert safe_http.MAX_BYTES_HTML == 2 * 1024 * 1024
    assert safe_http.MAX_BYTES_LARGE == 4 * 1024 * 1024
    assert safe_http.MAX_DECOMPRESSED >= 4 * 1024 * 1024


def test_article_fetch_uses_the_html_document_cap(monkeypatch):
    seen: dict[str, int] = {}

    def fetch(url, timeout, max_bytes):
        seen["max_bytes"] = max_bytes
        return "", url, "text/html", "fetch_failed"

    monkeypatch.setattr(article_fetcher, "_fetch_html_payload", fetch)
    article_fetcher.fetch_article_read_result("https://example.com/doc", timeout=5)

    assert seen["max_bytes"] >= 2 * 1024 * 1024


def test_a_five_mib_text_payload_is_not_a_decompression_bomb(monkeypatch):
    raw = b"x" * (5 * 1024 * 1024)

    def transport(url, *, timeout, deadline=None, max_bytes=0):
        return {
            "raw": raw,
            "final_url": url,
            "content_type": "text/plain; charset=utf-8",
            "content_encoding": "",
            "truncated": False,
        }

    monkeypatch.setattr(article_fetcher, "safe_fetch_result", transport)
    text, _url, _ct, reason = article_fetcher._fetch_text_payload(
        "https://example.com/big.txt", timeout=5, max_bytes=4 * 1024 * 1024
    )

    assert reason == ""
    assert len(text) == 5 * 1024 * 1024


def test_a_ten_mib_pdf_payload_keeps_the_explicit_binary_cap(monkeypatch):
    raw = b"x" * (10 * 1024 * 1024)

    def transport(url, *, timeout, deadline=None, max_bytes=0):
        return {
            "raw": raw,
            "final_url": url,
            "content_type": "application/pdf",
            "content_encoding": "",
            "truncated": False,
        }

    monkeypatch.setattr(article_fetcher, "safe_fetch_result", transport)
    payload, _url, _ct, reason = article_fetcher._fetch_binary_payload(
        "https://example.com/paper.pdf", timeout=10, max_bytes=12 * 1024 * 1024
    )

    assert reason == ""
    assert len(payload) == 10 * 1024 * 1024
