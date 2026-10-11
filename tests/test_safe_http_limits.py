"""B-Search-2B9-N: the size limit and its error attribution are correct.

The reader reported `response_too_large` for the Minecraft wiki page. Evidence
from the SAME production request (UA `StudyAgent/feed`) shows that page answers
**200 with 797,493 chunked bytes**, so a 300 KB cap truncates it legitimately:
the earlier `403 + Please wait` came from a different request with a browser UA.

These tests lock that behaviour in, including the cases the review asked for, so
a future change cannot silently turn a truncated body into a reported success.
"""

from __future__ import annotations

import pytest

import src.web.safe_http as sh


class _FakeResponse:
    def __init__(self, status: int, headers: dict[str, str], body: bytes):
        self.status = status
        self._headers = headers
        self._body = body

    def read(self, amt: int | None = None) -> bytes:
        return self._body if amt is None else self._body[:amt]

    def getheaders(self) -> list[tuple[str, str]]:
        return list(self._headers.items())


def _install(monkeypatch, response: _FakeResponse) -> None:
    class _FakeConn:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            return None

        def getresponse(self):
            return response

        def close(self):
            return None

    monkeypatch.setattr(sh.http.client, "HTTPConnection", _FakeConn)


def _get(monkeypatch, status, body, headers, cap):
    _install(monkeypatch, _FakeResponse(status, headers, body))
    return sh.http_get_raw("http://example.org/a", "example.org", "1.2.3.4",
                           timeout=5, max_bytes=cap)


def test_chunked_403_small_body_is_not_truncated(monkeypatch):
    """42 KB chunked 403 (the review's fixture): small body, status reported as-is."""
    status, headers, raw, truncated = _get(
        monkeypatch, 403, b"x" * 42_084, {"transfer-encoding": "chunked"}, sh.MAX_BYTES)
    assert status == 403
    assert len(raw) == 42_084
    assert truncated is False
    assert headers["transfer-encoding"] == "chunked"


def test_small_200_is_not_truncated(monkeypatch):
    status, _headers, raw, truncated = _get(
        monkeypatch, 200, b"y" * 1024, {"content-length": "1024"}, sh.MAX_BYTES)
    assert (status, len(raw), truncated) == (200, 1024, False)


def test_over_limit_200_is_truncated_and_not_a_success(monkeypatch):
    status, _headers, raw, truncated = _get(
        monkeypatch, 200, b"z" * 400_000, {}, 300_000)
    assert status == 200
    assert len(raw) == 300_000
    assert truncated is True


def test_size_limit_and_http_error_together_stay_distinguishable(monkeypatch):
    """A huge 403 keeps both facts: the status and the truncation flag."""
    status, _headers, raw, truncated = _get(monkeypatch, 403, b"q" * 500_000, {}, 300_000)
    assert status == 403
    assert len(raw) == 300_000 and truncated is True


def test_gzip_uses_the_wire_size_not_a_decompressed_one(monkeypatch):
    """The transport reads raw bytes, so a small gzip body is not truncated."""
    status, headers, raw, truncated = _get(
        monkeypatch, 200, b"g" * 12_000, {"content-encoding": "gzip"}, sh.MAX_BYTES)
    assert headers["content-encoding"] == "gzip"
    assert len(raw) == 12_000 and truncated is False


def test_mapping_truncated_body_raises_size_error_not_success(monkeypatch):
    monkeypatch.setattr(sh, "resolve_public_ips", lambda host, **kw: ["1.2.3.4"])
    monkeypatch.setattr(sh, "http_get_raw",
                        lambda url, host, ip, *, timeout, max_bytes=sh.MAX_BYTES:
                        (200, {}, b"a" * max_bytes, True))
    with pytest.raises(sh.SafeFetchRefusal, match="response_too_large"):
        sh.safe_fetch_result("https://ex.org/a", timeout=5)


def test_mapping_http_error_wins_over_success(monkeypatch):
    monkeypatch.setattr(sh, "resolve_public_ips", lambda host, **kw: ["1.2.3.4"])
    monkeypatch.setattr(sh, "http_get_raw",
                        lambda url, host, ip, *, timeout, max_bytes=sh.MAX_BYTES:
                        (403, {}, b"tiny", False))
    # An HTTP status error is an ordinary failure, not a security refusal.
    with pytest.raises(sh.SafeFetchError, match="http_403"):
        sh.safe_fetch_result("https://ex.org/a", timeout=5)


def test_mapping_small_200_returns_payload(monkeypatch):
    monkeypatch.setattr(sh, "resolve_public_ips", lambda host, **kw: ["1.2.3.4"])
    monkeypatch.setattr(sh, "http_get_raw",
                        lambda url, host, ip, *, timeout, max_bytes=sh.MAX_BYTES:
                        (200, {"content-type": "text/html"}, b"<html>ok</html>", False))
    result = sh.safe_fetch_result("https://ex.org/a", timeout=5)
    assert result["status"] == 200 and result["truncated"] is False


def test_capacity_policy_constants():
    assert sh.MAX_BYTES == 512 * 1024
    assert sh.MAX_BYTES_LARGE == 1024 * 1024
    assert sh.MAX_DECOMPRESSED == 4 * 1024 * 1024


def test_ordinary_cap_retries_once_up_to_the_large_cap(monkeypatch):
    """A ~600 KiB page is refused at 512 KiB, then read by the one bounded retry."""
    monkeypatch.setattr(sh, "resolve_public_ips", lambda host, **kw: ["1.2.3.4"])
    calls: list[int] = []

    def fake_get(url, host, ip, *, timeout, max_bytes=sh.MAX_BYTES):
        calls.append(max_bytes)
        if max_bytes < sh.MAX_BYTES_LARGE:
            return 200, {}, b"a" * max_bytes, True          # truncated at the first cap
        return 200, {}, b"a" * 600_000, False               # full body on the retry

    monkeypatch.setattr(sh, "http_get_raw", fake_get)
    result = sh.safe_fetch_result("https://ex.org/big", timeout=5)
    assert calls == [sh.MAX_BYTES, sh.MAX_BYTES_LARGE]
    assert result["status"] == 200 and result["truncated"] is False


def test_page_beyond_the_large_cap_is_still_refused(monkeypatch):
    monkeypatch.setattr(sh, "resolve_public_ips", lambda host, **kw: ["1.2.3.4"])
    monkeypatch.setattr(sh, "http_get_raw",
                        lambda url, host, ip, *, timeout, max_bytes=sh.MAX_BYTES:
                        (200, {}, b"a" * max_bytes, True))
    with pytest.raises(sh.SafeFetchRefusal, match="response_too_large"):
        sh.safe_fetch_result("https://ex.org/huge", timeout=5)


def test_cloudflare_challenge_is_named_not_silently_parsed(monkeypatch):
    monkeypatch.setattr(sh, "resolve_public_ips", lambda host, **kw: ["1.2.3.4"])
    monkeypatch.setattr(sh, "http_get_raw",
                        lambda url, host, ip, *, timeout, max_bytes=sh.MAX_BYTES:
                        (403, {"cf-mitigated": "challenge"}, b"<html>Please wait</html>", False))
    with pytest.raises(sh.SafeFetchError, match="site_challenge"):
        sh.safe_fetch_result("https://ex.org/challenged", timeout=5)


def test_decompressed_size_is_capped_separately_from_the_wire_size():
    import gzip

    payload = b"x" * 50_000
    packed = gzip.compress(payload)
    assert len(packed) < len(payload)
    assert sh.decompress_bounded(packed, "gzip") == payload
    with pytest.raises(sh.SafeFetchError, match="decompressed_too_large"):
        sh.decompress_bounded(packed, "gzip", limit=1000)
    with pytest.raises(sh.SafeFetchError, match="decompress_failed"):
        sh.decompress_bounded(b"not gzip at all", "gzip")

