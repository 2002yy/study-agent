"""URL resolution for news links, especially Google News redirect links."""

from __future__ import annotations

import re
from html import unescape as html_unescape
from urllib.parse import unquote, urlparse
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
    urlopen as _stdlib_urlopen,
)

from src.news.article_extractor import decode_html_payload as _decode_html_payload
from src.news.url_normalizer import (
    RedirectHop,
    RedirectResolutionResult,
    UrlMetadata,
    build_url_metadata,
    extract_redirect_target,
    extract_redirect_target_candidate,
    is_public_http_url,
)

urlopen = _stdlib_urlopen


def _is_google_news_url(url: str) -> bool:
    try:
        host = (urlparse((url or "").strip()).netloc or "").lower()
    except Exception:
        return False
    return host == "news.google.com" or host.endswith(".news.google.com")


def _news_item_url(item: dict) -> str:
    return (
        item.get("canonical_url")
        or item.get("resolved_link")
        or item.get("link")
        or ""
    ).strip().lower()


def _has_direct_article_link(item: dict) -> bool:
    item_url = _news_item_url(item)
    return bool(item_url) and not _is_google_news_url(item_url)


def _normalize_extracted_url(candidate: str) -> str:
    candidate = html_unescape((candidate or "").strip())
    candidate = (
        candidate.replace("\\u0026", "&")
        .replace("\\u003d", "=")
        .replace("\\u003D", "=")
        .replace("\\u003f", "?")
        .replace("\\u003F", "?")
        .replace("\\/", "/")
    )
    for _ in range(3):
        decoded = unquote(candidate)
        if decoded == candidate:
            break
        candidate = decoded
    return candidate.strip()


def _extract_resolved_url_from_google_news_html(html: str) -> str:
    patterns = [
        r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+url=(https?://[^"\'>\s]+)',
        r'<meta[^>]+content=["\'][^"\']*url=(https?://[^"\']+)["\']',
        r'"(?:url|targetUrl|articleUrl|canonicalUrl)"\s*:\s*"(https?:[^"\\]+)"',
        r'data-n-au=["\'](https?://[^"\']+)["\']',
        r'(?:data-[\w-]*(?:url|href|target|article)[\w-]*|href)=["\'](https?://[^"\']+)["\']',
        r'href=["\'](https?://[^"\']+)["\']',
        r"(https?%3A%2F%2F[^\"'>\s]+)",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, html, flags=re.I)
        for match in matches:
            candidate = _normalize_extracted_url(match)
            if (
                candidate
                and is_public_http_url(candidate)
                and not _is_google_news_url(candidate)
            ):
                return candidate
    return ""


def _make_hop(
    url: str,
    source: str,
    status: str,
    *,
    status_code: int | None = None,
    error: str = "",
) -> RedirectHop:
    return RedirectHop(
        url=(url or "").strip(),
        source=source,
        status=status,
        is_safe=is_public_http_url(url),
        status_code=status_code,
        error=error,
    )


def _metadata_result(
    original_url: str,
    resolved_url: str,
    status: str,
    hops: list[RedirectHop],
    error: str = "",
) -> RedirectResolutionResult:
    hop_tuple = tuple(hops)
    metadata = build_url_metadata(
        original_url,
        resolved_url,
        resolution_status=status,
        error=error,
        redirect_hops=hop_tuple,
    )
    return RedirectResolutionResult(metadata=metadata, hops=hop_tuple)


class _RecordingRedirectHandler(HTTPRedirectHandler):
    def __init__(self, hops: list[RedirectHop]) -> None:
        self._hops = hops
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        hop = _make_hop(
            newurl,
            "http_redirect",
            "followed" if is_public_http_url(newurl) else "blocked",
            status_code=code,
        )
        self._hops.append(hop)
        if not hop.is_safe:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_news_url(req: Request, timeout: int, hops: list[RedirectHop]):
    """Open URL with hop recording, preserving the old urlopen monkeypatch seam."""
    if urlopen is not _stdlib_urlopen:
        return urlopen(req, timeout=timeout)
    opener = build_opener(_RecordingRedirectHandler(hops))
    return opener.open(req, timeout=timeout)


def resolve_news_link_result(url: str, timeout: int = 6) -> RedirectResolutionResult:
    """Resolve a news/search redirect link with debug-friendly hop history."""
    url = (url or "").strip()
    hops: list[RedirectHop] = []
    if not url:
        return _metadata_result("", "", "empty", hops)

    hops.append(_make_hop(url, "input", "received"))
    if not hops[-1].is_safe:
        return _metadata_result(url, url, "unsafe", hops)

    generic_target = extract_redirect_target(url)
    if generic_target:
        hops.append(_make_hop(generic_target, "query_parameter", "extracted"))
        return _metadata_result(url, generic_target, "resolved", hops)
    generic_candidate = extract_redirect_target_candidate(url)
    if generic_candidate:
        hops.append(_make_hop(generic_candidate, "query_parameter", "blocked"))
        return _metadata_result(url, generic_candidate, "unsafe", hops)

    try:
        if not _is_google_news_url(url):
            return _metadata_result(url, url, "original", hops)

        req = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )

        with _open_news_url(req, timeout, hops) as response:
            final_url = response.geturl()
            if final_url and not _is_google_news_url(final_url):
                if not hops or hops[-1].url != final_url:
                    hops.append(_make_hop(final_url, "http_final", "resolved"))
                if is_public_http_url(final_url):
                    return _metadata_result(url, final_url, "resolved", hops)
                return _metadata_result(url, final_url, "unsafe", hops)

            content_type = response.headers.get("Content-Type", "")
            if "html" in content_type.lower():
                payload = response.read(250_000)
                html = _decode_html_payload(payload, content_type)
                extracted_url = _extract_resolved_url_from_google_news_html(html)
                if extracted_url:
                    hops.append(_make_hop(extracted_url, "html_extract", "extracted"))
                    return _metadata_result(url, extracted_url, "resolved", hops)

        return _metadata_result(url, final_url or url, "original", hops)
    except Exception as exc:
        hops.append(_make_hop(url, "resolver", "error", error=str(exc)))
        return _metadata_result(url, url, "error", hops, error=str(exc))


def resolve_news_link_metadata(url: str, timeout: int = 6) -> UrlMetadata:
    """Resolve a news/search redirect link and return normalized metadata.

    The function is fail-soft: errors return metadata for the original URL
    rather than breaking the whole news pipeline.
    """
    return resolve_news_link_result(url, timeout=timeout).metadata


def resolve_news_link(url: str, timeout: int = 6) -> str:
    """
    Try to resolve Google News RSS redirect links to a final article URL.
    If resolution fails, return the original URL.
    """
    metadata = resolve_news_link_metadata(url, timeout=timeout)
    if metadata.resolution_status in {"resolved", "original"} and is_public_http_url(
        metadata.resolved_url
    ):
        return metadata.resolved_url
    return url


def _display_link_host(url: str) -> str:
    try:
        parsed = urlparse((url or "").strip())
    except Exception:
        return ""
    host = (parsed.netloc or "").strip().lower()
    if not host:
        return ""
    return host
