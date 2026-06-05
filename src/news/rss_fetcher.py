"""RSS multi-source fetching with deduplication and news item pipeline."""

from __future__ import annotations

import re
import time
from collections.abc import MutableMapping
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from src.news.domain_policy import annotate_domain_policy, news_sort_score
from src.news.feed_registry import (
    mark_seen_entries,
    record_feed_result,
    registered_feed_urls,
)
from src.news.link_resolver import (
    _has_direct_article_link,
    _news_item_url,
    resolve_news_link_metadata,
)
from src.news.search_sources.searxng_source import search_searxng
from src.news.url_normalizer import build_url_metadata


# ── Constants ──────────────────────────────────────────────────────────

DEFAULT_NEWS_QUERY = "最新新闻 when:1d"

NEWS_FEED_URL = (
    "https://news.google.com/rss/search?q={query}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
)
BING_NEWS_FEED_URL = (
    "https://www.bing.com/news/search?q={query}&format=rss&setlang=zh-hans"
)
DOMESTIC_NEWS_FEEDS = (
    {
        "name": "Yicai Headline",
        "url": "https://rsshub.app/yicai/headline",
    },
    {
        "name": "Sina Finance China",
        "url": "https://rsshub.app/sina/finance/china",
    },
    {
        "name": "Caijing Roll",
        "url": "https://rsshub.app/caijing/roll",
    },
)


# ── Cache ─────────────────────────────────────────────────────────────

_NEWS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_NEWS_CACHE_TTL = 600
_NEWS_CACHE_MAX_SIZE = 32
_RECENT_NEWS_WINDOW_DAYS = 90
_LAST_FEED_WARNINGS: list[dict] = []
_LAST_FEED_METADATA: dict[str, dict[str, str]] = {}


def get_last_feed_warnings() -> list[dict]:
    """Return diagnostics for feeds that failed during the latest fetch."""
    return [dict(item) for item in _LAST_FEED_WARNINGS]


def _set_last_feed_warnings(warnings: list[dict]) -> None:
    global _LAST_FEED_WARNINGS
    _LAST_FEED_WARNINGS = [dict(item) for item in warnings]


def _record_feed_result_safely(
    source: str,
    url: str,
    *,
    ok: bool,
    item_count: int = 0,
    error: Exception | None = None,
    etag: str = "",
    modified: str = "",
) -> None:
    try:
        record_feed_result(
            source,
            url,
            ok=ok,
            item_count=item_count,
            error=error,
            etag=etag,
            modified=modified,
        )
    except Exception:
        pass


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
        oldest_key = min(cache, key=lambda key: cache[key][0])
        cache.pop(oldest_key, None)


def _prune_news_cache(now: float) -> None:
    _prune_cache(_NEWS_CACHE, _NEWS_CACHE_TTL, _NEWS_CACHE_MAX_SIZE, now)


# ── News query / title helpers ────────────────────────────────────────


def _clean_news_title(title: str) -> str:
    return re.sub(r"\s*-\s*[^-]+$", "", title).strip()


def normalize_news_query(query_text: str, max_chars: int = 120) -> str:
    query_text = re.sub(r"\s+", " ", (query_text or "").strip())
    if not query_text:
        return DEFAULT_NEWS_QUERY
    return query_text[:max_chars]


def _is_default_news_query(query_text: str) -> bool:
    return normalize_news_query(query_text) == DEFAULT_NEWS_QUERY


def _parse_news_pub_date(pub_date: str) -> tuple[str, float]:
    if not pub_date:
        return "", 0.0

    try:
        dt = parsedate_to_datetime(pub_date).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M"), dt.timestamp()
    except Exception:
        return pub_date, 0.0


def _query_terms(query_text: str) -> list[str]:
    normalized = normalize_news_query(query_text)
    if normalized == DEFAULT_NEWS_QUERY:
        return []

    terms: list[str] = []
    for part in re.split(r"\s+", normalized):
        cleaned = part.strip().lower()
        if not cleaned or cleaned == "when:1d":
            continue

        sub_terms = re.findall(r"[a-z0-9._-]+|[一-鿿]{2,}", cleaned)
        if sub_terms:
            terms.extend(sub_terms)
        else:
            terms.append(cleaned)
    return terms


def _title_matches_query(title: str, query_text: str) -> bool:
    terms = _query_terms(query_text)
    if not terms:
        return True

    lowered_title = (title or "").lower()
    return any(term in lowered_title for term in terms)


def _count_query_term_matches(title: str, query_text: str) -> int:
    terms = _query_terms(query_text)
    if not terms:
        return 0

    lowered_title = (title or "").lower()
    return sum(1 for term in terms if term in lowered_title)


def _preferred_source_domains(query_text: str) -> tuple[str, ...]:
    terms = set(_query_terms(query_text))
    if "openai" in terms:
        return ("openai.com",)
    return ()


# ── News sorting / deduplication ──────────────────────────────────────


def _is_recent_news_item(
    item: dict, now_ts: float, window_days: int = _RECENT_NEWS_WINDOW_DAYS
) -> bool:
    sort_ts = item.get("_sort_ts", 0.0)
    if not sort_ts:
        return False
    return now_ts - sort_ts <= window_days * 86400


def _news_item_sort_key(
    item: dict,
    query_text: str,
    now_ts: float,
) -> tuple[int, int, int, int, int, float]:
    preferred_domains = _preferred_source_domains(query_text)
    item_url = _news_item_url(item)
    source_priority = int(any(domain in item_url for domain in preferred_domains))
    direct_link_priority = int(_has_direct_article_link(item))
    recent_priority = int(_is_recent_news_item(item, now_ts))
    query_match_count = _count_query_term_matches(item.get("title", ""), query_text)
    domain_policy_score = news_sort_score(item, query_text)
    return (
        source_priority,
        direct_link_priority,
        recent_priority,
        query_match_count,
        domain_policy_score,
        item.get("_sort_ts", 0.0),
    )


def _dedupe_and_trim_news_items(
    news_items: list[dict],
    max_items: int,
    query_text: str = "",
) -> list[dict]:
    now_ts = time.time()
    sorted_items = sorted(
        news_items,
        key=lambda item: _news_item_sort_key(item, query_text, now_ts),
        reverse=True,
    )

    seen: set[tuple[str, str]] = set()
    recent_items: list[dict] = []
    older_items: list[dict] = []
    for item in sorted_items:
        title = item.get("title", "").strip().lower()
        link = item.get("link", "").strip()
        dedupe_key = (link, title)
        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        cleaned = dict(item)
        cleaned.pop("_sort_ts", None)
        if _is_recent_news_item(item, now_ts):
            recent_items.append(cleaned)
            if len(recent_items) >= max_items:
                break
        else:
            older_items.append(cleaned)

    if len(recent_items) >= max_items:
        return recent_items[:max_items]

    return (recent_items + older_items)[:max_items]


def _attach_url_metadata(item: dict, resolve: bool, query_text: str) -> dict:
    cleaned = dict(item)
    link = cleaned.get("link", "")
    metadata = resolve_news_link_metadata(link) if resolve else build_url_metadata(link)
    cleaned["resolved_link"] = metadata.resolved_url
    cleaned["canonical_url"] = metadata.canonical_url
    cleaned["domain"] = metadata.domain
    cleaned["resolution_status"] = metadata.resolution_status
    cleaned["redirect_hops"] = [
        {
            "url": hop.url,
            "source": hop.source,
            "status": hop.status,
            "is_safe": hop.is_safe,
            "status_code": hop.status_code,
            "location": hop.location,
            "reason": hop.reason,
            "error": hop.error,
        }
        for hop in metadata.redirect_hops
    ]
    if metadata.error:
        cleaned["resolution_error"] = metadata.error
    return annotate_domain_policy(cleaned, query_text)


def _dedupe_by_canonical_url(news_items: list[dict], max_items: int) -> list[dict]:
    seen_canonical: set[str] = set()
    seen_titles: set[str] = set()
    deduped: list[dict] = []

    for item in news_items:
        policy = item.get("domain_policy") or {}
        if policy.get("blocked"):
            continue

        canonical_url = (item.get("canonical_url") or "").strip().lower()
        title = item.get("title", "").strip().lower()

        if canonical_url:
            if canonical_url in seen_canonical:
                continue
            seen_canonical.add(canonical_url)
        elif title:
            if title in seen_titles:
                continue
            seen_titles.add(title)

        cleaned = dict(item)
        cleaned.pop("_sort_ts", None)
        deduped.append(cleaned)
        if len(deduped) >= max_items:
            break

    return deduped


def _resolve_and_dedupe_news_items(
    news_items: list[dict],
    max_items: int,
    resolve_top_n: int,
    query_text: str,
) -> list[dict]:
    # Resolve a small over-fetch window so canonical dedup can remove duplicate
    # redirect URLs without leaving too few usable items.
    resolve_count = min(max(resolve_top_n, max_items), len(news_items))
    resolved_items: list[dict] = []

    for idx, item in enumerate(news_items):
        resolved_items.append(
            _attach_url_metadata(item, resolve=idx < resolve_count, query_text=query_text)
        )

    now_ts = time.time()
    sorted_items = sorted(
        resolved_items,
        key=lambda item: _news_item_sort_key(item, query_text, now_ts),
        reverse=True,
    )
    return _dedupe_by_canonical_url(sorted_items, max_items)


# ── RSS fetching (no link resolution) ─────────────────────────────────


def _fetch_rss_items_from_url(
    feed_url: str,
    max_items: int = 10,
    source_fallback: str = "News Source",
    query_text: str = "",
) -> list[dict]:
    items, _metadata = _fetch_rss_items_with_metadata(
        feed_url,
        max_items=max_items,
        source_fallback=source_fallback,
        query_text=query_text,
    )
    return items


def _fetch_rss_items_with_metadata(
    feed_url: str,
    max_items: int = 10,
    source_fallback: str = "News Source",
    query_text: str = "",
) -> tuple[list[dict], dict]:
    global _LAST_FEED_METADATA
    req = Request(
        feed_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        },
    )

    with urlopen(req, timeout=15) as response:
        metadata = {
            "etag": response.headers.get("ETag", ""),
            "modified": response.headers.get("Last-Modified", ""),
        }
        payload = response.read()
    _LAST_FEED_METADATA[feed_url] = metadata

    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError(f"Malformed RSS feed: {source_fallback}: {exc}") from exc

    channel = root.find("./channel")
    if channel is None:
        raise ValueError(f"Malformed RSS feed: {source_fallback}: missing channel")

    items: list[dict] = []

    for node in channel.findall("./item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        pub_date = (node.findtext("pubDate") or "").strip()
        source = ""
        source_node = node.find("source")
        if source_node is not None and source_node.text:
            source = source_node.text.strip()

        clean_title = _clean_news_title(title)
        if not clean_title:
            continue
        if query_text and not _title_matches_query(clean_title, query_text):
            continue

        published_local, published_ts = _parse_news_pub_date(pub_date)
        items.append(
            {
                "title": clean_title,
                "source": source or source_fallback,
                "published_at": published_local or "Today",
                "published_timestamp": published_ts,
                "link": link,
                "resolved_link": "",  # No resolution during RSS phase
                "canonical_url": "",
                "domain": "",
                "resolution_status": "pending",
                "_sort_ts": published_ts,
            }
        )

        if len(items) >= max_items:
            break

    return items, metadata


# ── News item fetching pipeline ───────────────────────────────────────


def _fetch_query_news_items(query_text: str, max_items: int = 10) -> list[dict]:
    feed_urls = registered_feed_urls(query_text)

    items: list[dict] = []
    errors: list[Exception] = []
    feed_warnings: list[dict] = []
    per_feed_limit = max(max_items * 2, 8)

    try:
        items.extend(search_searxng(query_text, max_results=per_feed_limit))
    except Exception as exc:
        errors.append(exc)
        feed_warnings.append(
            {
                "source": "SearXNG",
                "url": "",
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
        )

    for source_name, feed_url, filter_by_query in feed_urls:
        try:
            feed_items = _fetch_rss_items_from_url(
                feed_url,
                max_items=per_feed_limit,
                source_fallback=source_name,
                query_text=query_text if filter_by_query else "",
            )
            feed_metadata = _LAST_FEED_METADATA.get(feed_url, {})
            items.extend(feed_items)
            _record_feed_result_safely(
                source_name,
                feed_url,
                ok=True,
                item_count=len(feed_items),
                etag=feed_metadata.get("etag", ""),
                modified=feed_metadata.get("modified", ""),
            )
        except Exception as exc:
            errors.append(exc)
            _record_feed_result_safely(
                source_name,
                feed_url,
                ok=False,
                error=exc,
            )
            feed_warnings.append(
                {
                    "source": source_name,
                    "url": feed_url,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )

    if not items and errors:
        _set_last_feed_warnings(feed_warnings)
        raise errors[0]

    _set_last_feed_warnings(feed_warnings)

    # Keep a modest candidate pool before redirect resolution; final trimming
    # happens after canonical URL deduplication.
    return _dedupe_and_trim_news_items(items, max_items * 2, query_text=query_text)


def fetch_news_items(
    query_text: str = DEFAULT_NEWS_QUERY,
    max_items: int = 10,
    resolve_top_n: int = 5,
) -> list[dict]:
    query_text = normalize_news_query(query_text)
    cache_key = f"{query_text}|{max_items}|resolve:{resolve_top_n}|canonical:v3"

    now = time.time()
    _prune_news_cache(now)

    cached = _NEWS_CACHE.get(cache_key)
    if cached and now - cached[0] < _NEWS_CACHE_TTL:
        return cached[1][:max_items]

    items = _fetch_query_news_items(query_text, max_items=max_items)
    items = _resolve_and_dedupe_news_items(
        items,
        max_items=max_items,
        resolve_top_n=resolve_top_n,
        query_text=query_text,
    )

    _NEWS_CACHE[cache_key] = (now, items)
    try:
        mark_seen_entries(items, now=now)
    except Exception:
        pass
    return items


def fetch_latest_news_items(max_items: int = 10) -> list[dict]:
    return fetch_news_items(DEFAULT_NEWS_QUERY, max_items=max_items)
