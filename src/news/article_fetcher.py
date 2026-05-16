"""Article fetching with DNS/IP security validation."""

from __future__ import annotations

import ipaddress
import re
import time
from socket import getaddrinfo
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from src.news.article_extractor import (
    decode_html_payload as _decode_html_payload,
    extract_article_text as _extract_article_text,
    article_method_label as _article_method_label,
)
from src.news.link_resolver import _is_google_news_url


# ── Cache ─────────────────────────────────────────────────────────────

_ARTICLE_CACHE: dict[str, tuple[float, str, str]] = {}
_ARTICLE_CACHE_TTL = 1800
_ARTICLE_CACHE_MAX_SIZE = 32


def _prune_cache(
    cache: dict[str, tuple[float, ...]],
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


# ── DNS / IP security helpers ─────────────────────────────────────────


def _check_dns_target_safe(hostname: str) -> bool:
    """Resolve hostname and reject if it points to a private/internal address."""
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


# ── Article fetching ──────────────────────────────────────────────────


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

    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )

    try:
        with urlopen(req, timeout=timeout) as response:
            final_url = response.geturl()
            if final_url and not _is_fetchable_article_url(final_url):
                _ARTICLE_CACHE[url] = (now, "", "")
                return "", ""

            content_type = response.headers.get("Content-Type", "")
            if (
                "html" not in content_type.lower()
                and "text" not in content_type.lower()
            ):
                _ARTICLE_CACHE[url] = (now, "", "")
                return "", ""

            payload = response.read(max_bytes + 1)
            if len(payload) > max_bytes:
                payload = payload[:max_bytes]

        html = _decode_html_payload(payload, content_type)
        text, method = _extract_article_text(
            html,
            url=url,
            max_chars=max_chars,
        )
        _ARTICLE_CACHE[url] = (now, text, method)
        return text, method
    except Exception:
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

    score = 100

    transit_domains = ["news.google.com", "bing.com/news"]
    if any(d in link for d in transit_domains):
        score += 60

    official_domains = [
        "openai.com",
        "github.com",
        "python.org",
        "rust-lang.org",
        "apple.com",
        "microsoft.com",
        "go.dev",
        "react.dev",
        "nextjs.org",
        "arxiv.org",
    ]
    if any(d in link for d in official_domains):
        score -= 15

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
