"""Regression tests for the bounded reader-quality fixes:

1. transport gzip/deflate bodies are decompressed before HTML/text decoding;
2. tables are kept by the article extractor (release pages carry versions in tables).
"""

from __future__ import annotations

import gzip
import zlib

from src.news.article_extractor import decompress_transport_payload


# --- bounded transport decompression -------------------------------------------


def test_gzip_is_undone():
    body = b"<html><table><tr><td>3.14.0</td></tr></table></html>"
    assert decompress_transport_payload(gzip.compress(body), "gzip") == body


def test_x_gzip_and_case_are_accepted():
    body = b"<html>ok</html>"
    assert decompress_transport_payload(gzip.compress(body), "X-GZIP") == body


def test_deflate_is_undone_raw_and_zlib():
    body = b"<html>deflate</html>"
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    raw = compressor.compress(body) + compressor.flush()
    assert decompress_transport_payload(raw, "deflate") == body
    assert decompress_transport_payload(zlib.compress(body), "deflate") == body


def test_identity_and_unknown_encodings_are_untouched():
    body = b"<html>plain</html>"
    assert decompress_transport_payload(body, "") == body
    assert decompress_transport_payload(body, "identity") == body
    assert decompress_transport_payload(body, "br") == body


def test_corrupt_gzip_is_not_a_crash():
    assert decompress_transport_payload(b"1f8b0800-not-really", "gzip") == b"1f8b0800-not-really"


def test_decompressed_output_is_bounded():
    body = b"x" * 100_000
    out = decompress_transport_payload(gzip.compress(body), "gzip", max_bytes=1_000)
    assert len(out) == 1_000


# --- tables are kept ------------------------------------------------------------


def test_trafilatura_is_asked_to_keep_tables(monkeypatch):
    import sys
    import types

    captured: dict[str, object] = {}

    def _extract(html, **kwargs):
        captured.update(kwargs)
        return "Download the release table. " + "| version | 3.14.0 | " * 12

    fake = types.ModuleType("trafilatura")
    fake.extract = _extract
    monkeypatch.setitem(sys.modules, "trafilatura", fake)

    from src.news.article_extractor import extract_article_text_with_trafilatura

    text = extract_article_text_with_trafilatura(
        "<html><table><tr><td>3.14.0</td></tr></table></html>",
        url="https://www.python.org/downloads/release/python-3140/",
    )
    assert captured.get("include_tables") is True
    assert "3.14.0" in text


# --- author / byline metadata ---------------------------------------------------


def test_author_is_read_from_meta_tags():
    from src.news.article_extractor import extract_article_author

    html = '<html><head><meta name="author" content="Jane Doe"></head><body>x</body></html>'
    assert extract_article_author(html) == "Jane Doe"


def test_author_reads_og_article_author():
    from src.news.article_extractor import extract_article_author

    html = '<meta property="article:author" content="Ada Lovelace">'
    assert extract_article_author(html) == "Ada Lovelace"


def test_missing_author_is_empty_not_guessed():
    from src.news.article_extractor import extract_article_author

    assert extract_article_author("<html><body>no byline</body></html>") == ""


def test_author_field_survives_the_reader_result(monkeypatch):
    from src.news import readers
    from src.news.readers.local_reader import read_html_locally

    monkeypatch.setattr(
        readers.local_reader,
        "extract_article_text",
        lambda html, url="", max_chars=5000: ("a" * 200, "trafilatura"),
    )
    html = '<meta name="author" content="Grace Hopper">'
    result = read_html_locally(html, url="https://example.com/post")
    assert result.ok is True
    assert result.author == "Grace Hopper"


def test_author_propagates_through_fetch_cache_and_gateway(monkeypatch):
    from src.news import article_fetcher
    from src.news.readers.base import ReaderResult
    from src.web.tool_gateway import GeneralWebGateway

    article_fetcher._ARTICLE_CACHE.clear()
    monkeypatch.setattr(
        article_fetcher,
        "_is_fetchable_article_url",
        lambda _url: True,
    )
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_html_payload",
        lambda _url, timeout, max_bytes: (
            '<meta name="author" content="Grace Hopper">',
            "https://example.com/post",
            "text/html",
            "",
        ),
    )
    monkeypatch.setattr(
        article_fetcher,
        "read_html_locally",
        lambda html, url="", max_chars=5000: ReaderResult(
            text="article body " * 20,
            method="trafilatura",
            author="Grace Hopper",
        ),
    )

    first = article_fetcher.fetch_article_read_result("https://example.com/post")
    second = article_fetcher.fetch_article_read_result("https://example.com/post")
    gateway = GeneralWebGateway().read("https://example.com/post")

    assert first.author == "Grace Hopper"
    assert second.author == "Grace Hopper"
    assert gateway["author"] == "Grace Hopper"
