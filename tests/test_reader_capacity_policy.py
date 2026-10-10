"""Capacity-policy regressions for the shared Reader chain (PR #210 audit fix).

Covers two audit findings:
  P1  the download cap and the post-decompress cap were conflated, so a page the
      transport accepted after its 1 MiB retry could still be rejected by the
      old 350 KB check. Download / decompress limits are now independent.
  P2  a large-page retry that answers with a 3xx must re-enter the redirect
      rules instead of returning the 3xx body as content.
"""
from __future__ import annotations

import pytest

import src.news.article_fetcher as af
import src.web.safe_http as sh


def _pin_public(monkeypatch):
    monkeypatch.setattr(sh, "resolve_public_ips", lambda host, deadline=None: ["93.184.216.34"])


def _body(n_bytes: int) -> bytes:
    return b"<html><body>" + b"A" * n_bytes + b"</body></html>"


def test_download_cap_and_decompress_cap_are_independent(monkeypatch):
    """A ~797 KB uncompressed page: the wire cap truncates, the bounded 1 MiB
    retry succeeds, and the post-decompress guard no longer rejects it."""
    _pin_public(monkeypatch)
    body = _body(797 * 1024)
    calls = {"n": 0}

    def fake_get(url, host, ip, *, timeout, max_bytes=sh.MAX_BYTES):
        calls["n"] += 1
        if len(body) <= max_bytes:
            return 200, {"content-type": "text/html"}, body, False
        return 200, {"content-type": "text/html"}, body[:max_bytes], True

    monkeypatch.setattr(sh, "http_get_raw", fake_get)

    # transport: the retry proves the download cap can reach the large cap
    res = sh.safe_fetch_result("https://example.org/article/big", timeout=8)
    assert res["truncated"] is False
    assert len(res["raw"]) == len(body)
    assert calls["n"] == 2  # first attempt + one bounded retry

    # reader layer: the old 350 KB post-decompress check must not reject it now
    calls["n"] = 0
    html, final_url, _ctype, reason = af._fetch_html_payload(
        "https://example.org/article/big", timeout=8, max_bytes=sh.MAX_BYTES
    )
    assert reason == "", reason
    assert len(html) > 512 * 1024


def test_page_over_one_mib_is_refused(monkeypatch):
    """Above the 1 MiB large cap the read must fail closed, not truncate."""
    _pin_public(monkeypatch)
    body = _body(1_200_000)

    def fake_get(url, host, ip, *, timeout, max_bytes=sh.MAX_BYTES):
        return 200, {"content-type": "text/html"}, body[:max_bytes], True

    monkeypatch.setattr(sh, "http_get_raw", fake_get)
    with pytest.raises(Exception):
        sh.safe_fetch_result("https://example.org/article/huge", timeout=8)


def test_large_page_retry_that_redirects_is_followed_not_returned(monkeypatch):
    """The retry may answer 3xx; it must re-enter the redirect rules so the 3xx
    body is never returned as article content."""
    _pin_public(monkeypatch)
    big = _body(sh.MAX_BYTES + 10)
    calls = {"n": 0}

    def fake_get(url, host, ip, *, timeout, max_bytes=sh.MAX_BYTES):
        calls["n"] += 1
        if calls["n"] == 1:  # first attempt of /start: truncated -> triggers retry
            return 200, {"content-type": "text/html"}, big[:max_bytes], True
        if calls["n"] == 2:  # the retry answers with a redirect
            return 302, {"location": "https://example.org/final"}, b"", False
        return 200, {"content-type": "text/html"}, b"<html><body>final</body></html>", False

    monkeypatch.setattr(sh, "http_get_raw", fake_get)
    res = sh.safe_fetch_result("https://example.org/start", timeout=8)
    assert res["final_url"] == "https://example.org/final"
    assert "final" in res["text"]
    assert res["status"] == 200


@pytest.mark.parametrize("reason", ["site_challenge", "http_403", "decompress_failed"])
def test_reader_preserves_transport_reason(monkeypatch, reason):
    """A SafeFetchError must keep its stable reason instead of degrading to
    'fetch_failed' (diagnostic contract for site challenges / 403s / limits)."""

    def boom(*a, **k):
        raise sh.SafeFetchError(reason)

    monkeypatch.setattr(af, "safe_fetch_result", boom)
    html, _u, _c, why = af._fetch_html_payload("https://example.org/a", timeout=8, max_bytes=sh.MAX_BYTES)
    assert why == reason
    txt, _u2, _c2, why2 = af._fetch_text_payload("https://example.org/a", timeout=8, max_bytes=sh.MAX_BYTES)
    assert why2 == reason


def test_reader_still_fails_closed_on_security_refusal(monkeypatch):
    """A security refusal must propagate, never be routed into a weaker fallback."""

    def boom(*a, **k):
        raise sh.SafeFetchRefusal("unsafe_target")

    monkeypatch.setattr(af, "safe_fetch_result", boom)
    with pytest.raises(sh.SafeFetchRefusal):
        af._fetch_html_payload("https://example.org/a", timeout=8, max_bytes=sh.MAX_BYTES)
