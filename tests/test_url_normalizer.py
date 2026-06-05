from __future__ import annotations

import pytest

from src.news.url_normalizer import (
    build_url_metadata,
    canonicalize_url,
    display_domain,
    extract_domain,
    extract_redirect_target,
    is_public_http_url,
)


class TestUrlNormalizer:
    def test_extract_redirect_target_from_url_param(self):
        wrapped = "https://example.com/redirect?url=https%3A%2F%2Fgithub.com%2F2002yy%2Fstudy-agent%3Futm_source%3Drss"

        assert extract_redirect_target(wrapped) == (
            "https://github.com/2002yy/study-agent?utm_source=rss"
        )

    def test_extract_redirect_target_from_q_param(self):
        wrapped = "https://search.example.com/?q=https%3A%2F%2Fdocs.python.org%2F3%2F"

        assert extract_redirect_target(wrapped) == "https://docs.python.org/3/"

    def test_canonicalize_strips_tracking_params_and_fragment(self):
        url = (
            "HTTPS://GitHub.com/2002yy/study-agent?"
            "utm_source=rss&b=2&a=1&fbclid=abc#section"
        )

        assert canonicalize_url(url) == "https://github.com/2002yy/study-agent?a=1&b=2"

    def test_canonicalize_preserves_meaningful_query_params(self):
        url = "https://example.com/article?id=42&utm_medium=social"

        assert canonicalize_url(url) == "https://example.com/article?id=42"

    def test_canonicalize_drops_default_ports_and_duplicate_pairs(self):
        url = "https://Example.com:443/story?b=2&a=1&a=1&utm_source=x"

        assert canonicalize_url(url) == "https://example.com/story?a=1&b=2"

    def test_canonicalize_applies_domain_specific_query_allowlist(self):
        url = "https://openai.com/news/product?utm_source=x&ref=feed&id=keep"

        assert canonicalize_url(url) == "https://openai.com/news/product"

    def test_canonicalize_keeps_unknown_domain_query_params(self):
        url = "https://publisher.example/story?article=42&utm_campaign=x"

        assert canonicalize_url(url) == "https://publisher.example/story?article=42"

    def test_display_domain_decodes_punycode_for_ui(self):
        assert display_domain("https://xn--fsqu00a.xn--0zwm56d/story") == "例子.测试"
        assert display_domain("www.xn--fsqu00a.xn--0zwm56d") == "例子.测试"

    def test_rejects_unsafe_urls(self):
        assert not is_public_http_url("file:///etc/passwd")
        assert not is_public_http_url("ftp://example.com/a")
        assert not is_public_http_url("http://localhost:8000")
        assert not is_public_http_url("http://127.0.0.1:8000")
        assert not is_public_http_url("http://192.168.1.2/a")
        assert not is_public_http_url("https://user:pass@example.com/a")  # pragma: allowlist secret
        assert not is_public_http_url("https://example.com\\@evil.test/a")
        assert not is_public_http_url("https://example.com/a b")
        assert not is_public_http_url("https://example.com:99999/a")

    @pytest.mark.parametrize(
        "url",
        [
            "http://2130706433/admin",
            "http://0177.0.0.1/admin",
            "http://0x7f.0.0.1/admin",
            "http://127.1/admin",
            "http://[::1]/admin",
            "http://[::ffff:127.0.0.1]/admin",
            "http://%31%32%37.0.0.1/admin",
            "http://example.com%2f.evil.test/admin",
        ],
    )
    def test_rejects_parser_ambiguous_or_encoded_hosts(self, url):
        assert not is_public_http_url(url)

    def test_repeated_encoded_redirect_to_private_host_is_blocked(self):
        wrapped = (
            "https://news.example/redirect?"
            "url=http%253A%252F%252F127.0.0.1%252Fadmin"
        )

        assert extract_redirect_target(wrapped) == ""
        metadata = build_url_metadata(wrapped)
        assert metadata.resolution_status == "unsafe"
        assert metadata.resolved_url == "http://127.0.0.1/admin"

    def test_normal_public_urls_still_pass_safety_matrix(self):
        assert is_public_http_url("https://docs.python.org/3/library/urllib.parse.html")
        assert is_public_http_url("https://xn--fsqu00a.xn--0zwm56d/story")

    def test_build_url_metadata_marks_resolved_and_domain(self):
        metadata = build_url_metadata(
            "https://news.example.com/redirect?url=https%3A%2F%2Fgithub.com%2F2002yy%2Fstudy-agent%3Futm_campaign%3Dx",
        )

        assert metadata.resolution_status == "resolved"
        assert metadata.domain == "github.com"
        assert metadata.canonical_url == "https://github.com/2002yy/study-agent"

    def test_build_url_metadata_marks_unsafe(self):
        metadata = build_url_metadata("http://localhost:8501")

        assert metadata.resolution_status == "unsafe"
        assert metadata.canonical_url == ""
        assert extract_domain(metadata.resolved_url) == "localhost"
