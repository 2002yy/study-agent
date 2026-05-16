"""RSS multi-source fetching with deduplication and news item pipeline."""

from __future__ import annotations

import re
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from src.news.link_resolver import (
    _has_direct_article_link,
    _news_item_url,
    resolve_news_link,
)


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
) -> tuple[int, int, int, int, float]:
    preferred_domains = _preferred_source_domains(query_text)
    item_url = _news_item_url(item)
    source_priority = int(any(domain in item_url for domain in preferred_domains))
    direct_link_priority = int(_has_direct_article_link(item))
    recent_priority = int(_is_recent_news_item(item, now_ts))
    query_match_count = _count_query_term_matches(item.get("title", ""), query_text)
    return (
        source_priority,
        direct_link_priority,
        recent_priority,
        query_match_count,
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


# ── RSS fetching (no link resolution) ─────────────────────────────────


def _fetch_rss_items_from_url(
    feed_url: str,
    max_items: int = 10,
    source_fallback: str = "News Source",
    query_text: str = "",
) -> list[dict]:
    req = Request(
        feed_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        },
    )

    with urlopen(req, timeout=15) as response:
        payload = response.read()

    root = ET.fromstring(payload)
    items: list[dict] = []

    for node in root.findall("./channel/item"):
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
                "_sort_ts": published_ts,
            }
        )

        if len(items) >= max_items:
            break

    return items


# ── News item fetching pipeline ───────────────────────────────────────


def _fetch_query_news_items(query_text: str, max_items: int = 10) -> list[dict]:
    query = quote_plus(query_text)
    feed_urls = [
        ("Google News", NEWS_FEED_URL.format(query=query), False),
        ("Bing News", BING_NEWS_FEED_URL.format(query=query), False),
    ]
    feed_urls.extend((feed["name"], feed["url"], True) for feed in DOMESTIC_NEWS_FEEDS)

    items: list[dict] = []
    errors: list[Exception] = []
    per_feed_limit = max(max_items, 8)

    for source_name, feed_url, filter_by_query in feed_urls:
        try:
            items.extend(
                _fetch_rss_items_from_url(
                    feed_url,
                    max_items=per_feed_limit,
                    source_fallback=source_name,
                    query_text=query_text if filter_by_query else "",
                )
            )
        except Exception as exc:
            errors.append(exc)

    if not items and errors:
        raise errors[0]

    return _dedupe_and_trim_news_items(items, max_items, query_text=query_text)


def fetch_news_items(
    query_text: str = DEFAULT_NEWS_QUERY,
    max_items: int = 10,
    resolve_top_n: int = 5,
) -> list[dict]:
    query_text = normalize_news_query(query_text)
    cache_key = f"{query_text}|{max_items}|resolve:{resolve_top_n}"

    now = time.time()
    _prune_news_cache(now)

    cached = _NEWS_CACHE.get(cache_key)
    if cached and now - cached[0] < _NEWS_CACHE_TTL:
        return cached[1][:max_items]

    items = _fetch_query_news_items(query_text, max_items=max_items)

    # Resolve links only for items that survive dedupe/trim
    resolve_count = min(resolve_top_n, len(items))
    for item in items[:resolve_count]:
        link = item.get("link", "")
        item["resolved_link"] = resolve_news_link(link)

    _NEWS_CACHE[cache_key] = (now, items)
    return items


def fetch_latest_news_items(max_items: int = 10) -> list[dict]:
    return fetch_news_items(DEFAULT_NEWS_QUERY, max_items=max_items)
