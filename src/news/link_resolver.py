"""URL resolution for news links, especially Google News redirect links."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from src.news.article_extractor import decode_html_payload as _decode_html_payload
from src.news.url_normalizer import (
    UrlMetadata,
    build_url_metadata,
    extract_redirect_target,
)


def _is_google_news_url(url: str) -> bool:
    try:
        host = (urlparse((url or "").strip()).netloc or "").lower()
    except Exception:
        return False
    return "news.google.com" in host


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


def _extract_resolved_url_from_google_news_html(html: str) -> str:
    patterns = [
        r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+url=(https?://[^"\'>\s]+)',
        r'"(?:url|targetUrl|articleUrl|canonicalUrl)"\s*:\s*"(https?:[^"\\]+)"',
        r'href=["\'](https?://[^"\']+)["\']',
        r"(https?%3A%2F%2F[^\"'>\s]+)",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, html, flags=re.I)
        for match in matches:
            candidate = unquote(match) if "%2F" in match or "%3A" in match else match
            candidate = candidate.replace("\\u0026", "&").replace("\\/", "/")
            if candidate and not _is_google_news_url(candidate):
                return candidate
    return ""


def resolve_news_link_metadata(url: str, timeout: int = 6) -> UrlMetadata:
    """Resolve a news/search redirect link and return normalized metadata.

    The function is fail-soft: errors return metadata for the original URL
    rather than breaking the whole news pipeline.
    """
    url = (url or "").strip()
    if not url:
        return build_url_metadata("", "", resolution_status="empty")

    generic_target = extract_redirect_target(url)
    if generic_target:
        return build_url_metadata(url, generic_target, resolution_status="resolved")

    try:
        parsed = urlparse(url)
        if "news.google.com" not in (parsed.netloc or ""):
            return build_url_metadata(url, url, resolution_status="original")

        req = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )

        with urlopen(req, timeout=timeout) as response:
            final_url = response.geturl()
            if final_url and not _is_google_news_url(final_url):
                return build_url_metadata(url, final_url, resolution_status="resolved")

            content_type = response.headers.get("Content-Type", "")
            if "html" in content_type.lower():
                payload = response.read(250_000)
                html = _decode_html_payload(payload, content_type)
                extracted_url = _extract_resolved_url_from_google_news_html(html)
                if extracted_url:
                    return build_url_metadata(
                        url,
                        extracted_url,
                        resolution_status="resolved",
                    )

        return build_url_metadata(url, final_url or url, resolution_status="original")
    except Exception as exc:
        return build_url_metadata(url, url, resolution_status="error", error=str(exc))


def resolve_news_link(url: str, timeout: int = 6) -> str:
    """
    Try to resolve Google News RSS redirect links to a final article URL.
    If resolution fails, return the original URL.
    """
    metadata = resolve_news_link_metadata(url, timeout=timeout)
    return metadata.resolved_url or url


def _display_link_host(url: str) -> str:
    try:
        parsed = urlparse((url or "").strip())
    except Exception:
        return ""
    host = (parsed.netloc or "").strip().lower()
    if not host:
        return ""
    return host
