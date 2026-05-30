from __future__ import annotations

from src.news.url_normalizer import (
    build_url_metadata,
    canonicalize_url,
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

    def test_rejects_unsafe_urls(self):
        assert not is_public_http_url("file:///etc/passwd")
        assert not is_public_http_url("ftp://example.com/a")
        assert not is_public_http_url("http://localhost:8000")
        assert not is_public_http_url("http://127.0.0.1:8000")
        assert not is_public_http_url("http://192.168.1.2/a")
        assert not is_public_http_url("https://user:pass@example.com/a")

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
