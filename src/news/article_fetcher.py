"""Article fetching with DNS/IP security validation."""

from __future__ import annotations

import ipaddress
import os
import re
import time
from collections.abc import MutableMapping
from socket import getaddrinfo
from typing import Any
from urllib.parse import urlparse
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)

from src.news.article_extractor import (
    article_method_label as _article_method_label,
    decode_html_payload as _decode_html_payload,
)
from src.news.domain_policy import article_priority_adjustment, should_fetch_article
from src.news.readers.firecrawl_reader import firecrawl_enabled, read_with_firecrawl
from src.news.readers.jina_reader import read_with_jina_reader
from src.news.readers.local_reader import read_html_locally


# ── Cache ─────────────────────────────────────────────────────────────

_ARTICLE_CACHE: dict[str, tuple[float, str, str]] = {}
_ARTICLE_CACHE_TTL = 1800
_ARTICLE_CACHE_MAX_SIZE = 32


def _prune_cache(
    cache: MutableMapping[str, Any],
    ttl: float,
    max_size: int,
    now: float,
) -> None:
    expired = [
        key for key, (created_at, *_) in cache.items() if now - created_at >= ttl
    ]
    for key in expired:
        cache.pop(key, None)

    while len(cache) >= max_size:
        oldest_key = min(cache, key=lambda k: cache[k][0])
        cache.pop(oldest_key, None)


def _prune_article_cache(now: float) -> None:
    _prune_cache(_ARTICLE_CACHE, _ARTICLE_CACHE_TTL, _ARTICLE_CACHE_MAX_SIZE, now)


# ── Reader backend settings ────────────────────────────────────────────


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def jina_fallback_enabled() -> bool:
    """Return whether hosted Jina Reader fallback is explicitly enabled."""
    return _env_flag("NEWS_ENABLE_JINA_READER", default=False)


# ── DNS / IP security helpers ─────────────────────────────────────────


def _check_dns_target_safe(hostname: str) -> bool:
    """Resolve hostname and reject if it points to a private/internal address.

    Note: there is a TOCTOU window between this DNS check and the real
    urlopen() connection.  For a personal tool the risk is acceptable;
    a production-grade fix would pin resolved IPs or use a single
    connection path that integrates resolution with fetch.
    """
    try:
        addrs = getaddrinfo(hostname, None)
    except Exception:
        return False
    for _family, _type, _proto, _canon, sockaddr in addrs:
        raw_ip = sockaddr[0]
        try:
            ip = ipaddress.ip_address(raw_ip)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                return False
        except ValueError:
            continue
    return True


def _is_fetchable_article_url(url: str) -> bool:
    try:
        parsed = urlparse((url or "").strip())
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    host = parsed.hostname or ""
    if not host:
        return False

    lowered = host.lower()
    if lowered in {"localhost"}:
        return False

    try:
        ip = ipaddress.ip_address(lowered)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    except ValueError:
        # Hostname is not an IP literal — resolve via DNS
        if not _check_dns_target_safe(host):
            return False

    return True


# ── Safe HTTP redirect handler (SSRF defense in depth) ─────────────────

_MAX_REDIRECT_DEPTH = 3


class _SafeHTTPRedirectHandler(HTTPRedirectHandler):
    """Custom redirect handler that validates each hop for SSRF safety.

    - Checks _is_fetchable_article_url() before following each redirect
    - Limits redirect chain depth to _MAX_REDIRECT_DEPTH
    - Works alongside the response.geturl() final-URL check below
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_fetchable_article_url(newurl):
            return None  # refuse unsafe redirect target
        newreq = super().redirect_request(req, fp, code, msg, headers, newurl)
        if newreq is None:
            return None
        depth = getattr(req, "_redirect_depth", 0) + 1
        if depth > _MAX_REDIRECT_DEPTH:
            return None
        newreq._redirect_depth = depth
        return newreq


# Shared opener with safe redirect handler (replaces default HTTPRedirectHandler)
_SAFE_OPENER = build_opener(_SafeHTTPRedirectHandler())


# ── Article fetching ──────────────────────────────────────────────────


def _fetch_html_payload(
    url: str,
    timeout: int,
    max_bytes: int,
) -> tuple[str, str]:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )

    with _SAFE_OPENER.open(req, timeout=timeout) as response:
        final_url = response.geturl()
        if final_url and not _is_fetchable_article_url(final_url):
            return "", ""

        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower() and "text" not in content_type.lower():
            return "", ""

        payload = response.read(max_bytes + 1)
        if len(payload) > max_bytes:
            payload = payload[:max_bytes]

    return _decode_html_payload(payload, content_type), final_url or url


def _try_firecrawl(url: str, timeout: int, max_chars: int) -> tuple[str, str]:
    if not firecrawl_enabled():
        return "", ""
    result = read_with_firecrawl(url, timeout=timeout, max_chars=max_chars)
    if result.ok:
        return result.text, result.method
    return "", ""


def _try_jina(url: str, timeout: int, max_chars: int) -> tuple[str, str]:
    if not jina_fallback_enabled():
        return "", ""
    result = read_with_jina_reader(url, timeout=timeout, max_chars=max_chars)
    if result.ok:
        return result.text, result.method
    return "", ""


def fetch_article_text_with_method(
    url: str,
    timeout: int = 8,
    max_bytes: int = 350_000,
    max_chars: int = 5000,
) -> tuple[str, str]:
    url = (url or "").strip()
    if not url or not _is_fetchable_article_url(url):
        return "", ""

    now = time.time()
    _prune_article_cache(now)

    cached = _ARTICLE_CACHE.get(url)
    if cached and now - cached[0] < _ARTICLE_CACHE_TTL:
        return cached[1], cached[2]

    try:
        final_url = url
        html, final_url = _fetch_html_payload(url, timeout=timeout, max_bytes=max_bytes)
        if html:
            local_result = read_html_locally(
                html,
                url=final_url or url,
                max_chars=max_chars,
            )
            if local_result.ok:
                _ARTICLE_CACHE[url] = (now, local_result.text, local_result.method)
                return local_result.text, local_result.method

        fallback_url = final_url or url
        text, method = _try_firecrawl(fallback_url, timeout=timeout, max_chars=max_chars)
        if text:
            _ARTICLE_CACHE[url] = (now, text, method)
            return text, method

        text, method = _try_jina(fallback_url, timeout=timeout, max_chars=max_chars)
        if text:
            _ARTICLE_CACHE[url] = (now, text, method)
            return text, method

        _ARTICLE_CACHE[url] = (now, "", "")
        return "", ""
    except Exception:
        text, method = _try_firecrawl(url, timeout=timeout, max_chars=max_chars)
        if text:
            _ARTICLE_CACHE[url] = (now, text, method)
            return text, method

        text, method = _try_jina(url, timeout=timeout, max_chars=max_chars)
        if text:
            _ARTICLE_CACHE[url] = (now, text, method)
            return text, method
        return "", ""


def fetch_article_text(
    url: str,
    timeout: int = 8,
    max_bytes: int = 350_000,
    max_chars: int = 5000,
) -> str:
    text, _ = fetch_article_text_with_method(
        url,
        timeout=timeout,
        max_bytes=max_bytes,
        max_chars=max_chars,
    )
    return text


# ── Article priority & enrichment ─────────────────────────────────────


def _article_fetch_priority(item: dict, query_text: str = "") -> int:
    source = (item.get("source") or "").lower()
    title = (item.get("title") or "").lower()
    link = (item.get("resolved_link") or item.get("link") or "").lower()
    published_at = (item.get("published_at") or "").lower()

    score = 100 + article_priority_adjustment(item, query_text)

    transit_domains = ["news.google.com", "bing.com/news"]
    if any(d in link for d in transit_domains):
        score += 60

    trusted_sources = [
        "infoq",
        "51cto",
        "36kr",
        "cnbeta",
        "sina",
        "新浪",
        "中国科技网",
        "huggingface",
        "medium.com",
        "dev.to",
    ]
    if any(src.lower() in source or src.lower() in link for src in trusted_sources):
        score -= 10

    if query_text:
        query_lower = query_text.lower()
        query_words = [w for w in query_lower.split() if len(w) >= 2]
        match_count = sum(1 for w in query_words if w in title)
        score -= min(match_count * 8, 24)

    if published_at:
        if re.search(r"202[4-6]", published_at):
            score -= 5

    return score


def enrich_news_items_with_article_text(
    news_items: list[dict],
    max_articles: int = 5,
    max_chars_per_article: int = 5000,
    query_text: str = "",
) -> list[dict]:
    enriched = [dict(item) for item in news_items]

    ranked_indices = sorted(
        range(len(enriched)),
        key=lambda idx: (_article_fetch_priority(enriched[idx], query_text), idx),
    )
    selected_indices = set(ranked_indices[:max_articles])

    for idx, item in enumerate(enriched):
        if idx not in selected_indices:
            item["article_excerpt"] = ""
            item["article_status"] = "未进入正文读取候选，仅使用标题与来源"
            continue

        if not should_fetch_article(item, query_text):
            item["article_excerpt"] = ""
            item["article_status"] = "域名策略过滤，未读取正文"
            continue

        article_url = item.get("resolved_link") or item.get("link", "")
        if "news.google.com" in article_url:
            item["article_excerpt"] = ""
            item["article_status"] = "未解析到原文链接，使用标题与来源"
            continue

        article_text, method = fetch_article_text_with_method(
            article_url,
            max_chars=max_chars_per_article,
        )
        if article_text:
            item["article_excerpt"] = article_text
            method_label = _article_method_label(method)
            item["article_status"] = f"正文已读｜{method_label}"
        else:
            item["article_excerpt"] = ""
            item["article_status"] = "正文不可用，使用标题与来源"

    return enriched
