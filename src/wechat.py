from __future__ import annotations

import re
import time
import ipaddress
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, unquote, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4
import xml.etree.ElementTree as ET

from src.llm_client import ModelProfile, chat, stream_chat
from src.mode_manager import load_runtime_modes, update_wechat_join_state
from src.news.article_extractor import (
    article_method_label as _article_method_label,
    clean_article_text as _clean_article_text,  # noqa: F401
    decode_html_payload as _decode_html_payload,
    extract_article_text as _extract_article_text,
    extract_article_text_with_fallback_parser as _extract_article_text_with_fallback_parser,  # noqa: F401
    extract_article_text_with_readability as _extract_article_text_with_readability,  # noqa: F401
    extract_article_text_with_trafilatura as _extract_article_text_with_trafilatura,  # noqa: F401
)
from src.role_manager import load_role
from src.safe_writer import append_text_safely, safe_write_text

ROOT = Path(__file__).resolve().parent.parent
GROUP_FILE = ROOT / "chat" / "wechat_group.md"
UNREAD_FILE = ROOT / "chat" / "wechat_unread.md"
STATE_FILE = ROOT / "chat" / "wechat_state.md"
ARCHIVE_DIR = ROOT / "chat" / "archive"
TEMPLATE_FILE = ROOT / "templates" / "wechat_update.md"
INTERACTIVE_TEMPLATE = ROOT / "templates" / "wechat_interactive_reply.md"
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

STYLE_PROMPTS = {
    "简短": "\n【风格要求】每条消息 1-2 句，每位不超过 60 字，总长度不超过 400 字。",
    "标准": "\n【风格要求】每条消息 2-3 句，每位不超过 100 字，总长度不超过 600 字。",
    "稍微有温度": "\n【风格要求】每条消息 2-4 句，每位不超过 120 字，总长度不超过 800 字。",
}

WECHAT_ROLE_ORDER = ["三月七", "刻晴", "纳西妲", "流萤"]
WECHAT_BLOCK_PATTERN = re.compile(r"【(.+?)】\s*(.+?)(?=\n【|\Z)", re.DOTALL)
WECHAT_MISSING_ROLE_FALLBACKS = {
    "三月七": "我这边也接住啦，这句我听到了。那我先把气氛接上，我们继续往下聊。",
    "刻晴": "我补一句重点：先把你刚刚提到的核心问题记住，接下来按最关键的一步继续推进就好。",
    "纳西妲": "从这个角度看，你刚刚那句话其实已经给了线索。顺着它往下想，通常就能把眼前这一步理清一些。",
    "流萤": "我也在。别急，我们就顺着你刚刚这句话慢慢接下去，一点点把现在的感觉和事情放稳。",
}
ROLE_ID_TO_NAME = {
    "auto": "自动",
    "march7": "三月七",
    "keqing": "刻晴",
    "nahida": "纳西妲",
    "firefly": "流萤",
}
PERFORMANCE_STYLE_HINTS = {
    "fast": "整体更轻、更快、更短，每位角色 1 到 2 句即可。",
    "standard": "整体自然平衡，每位角色 1 到 3 句。",
    "deep": "可以稍微多一点层次，但仍然保持轻盈，不要写成长文。",
}
LEGACY_OPENING_MARKERS = (
    "要是你正好看到",
    "就把这里当成轻松一点的学习搭子小群也行",
)


def _file_signature(path: Path) -> str:
    if not path.is_file():
        return "missing"
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


@lru_cache(maxsize=32)
def _load_wechat_text_cached(path_str: str, signature: str) -> str:
    path = Path(path_str)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _load_text(path: Path, default: str = "") -> str:
    if not path.is_file():
        return default
    return _load_wechat_text_cached(str(path), _file_signature(path))


def _message_blocks(content: str) -> list[tuple[str, str]]:
    return [
        (speaker.strip(), text.strip())
        for speaker, text in WECHAT_BLOCK_PATTERN.findall(content)
    ]


def _format_role_blocks(blocks: list[tuple[str, str]]) -> str:
    return "\n\n".join(
        f"【{speaker}】\n{text.strip()}" for speaker, text in blocks if text.strip()
    ).strip()


def _ensure_all_roles_reply(content: str) -> str:
    blocks = _message_blocks(content)
    if not blocks:
        return _format_role_blocks(
            [
                (speaker, WECHAT_MISSING_ROLE_FALLBACKS[speaker])
                for speaker in WECHAT_ROLE_ORDER
            ]
        )

    by_speaker: dict[str, list[str]] = {}
    for speaker, text in blocks:
        if speaker not in WECHAT_ROLE_ORDER:
            continue
        by_speaker.setdefault(speaker, []).append(text.strip())

    normalized_blocks: list[tuple[str, str]] = []
    for speaker in WECHAT_ROLE_ORDER:
        parts = [part for part in by_speaker.get(speaker, []) if part]
        if parts:
            normalized_blocks.append((speaker, "\n".join(parts)))
        else:
            normalized_blocks.append((speaker, WECHAT_MISSING_ROLE_FALLBACKS[speaker]))
    return _format_role_blocks(normalized_blocks)


def _resolve_model_profile(
    selected_model: str = "auto",
    performance_mode: str = "standard",
) -> ModelProfile:
    if performance_mode == "deep":
        return "pro"
    if performance_mode == "fast":
        return "flash"
    if selected_model == "pro":
        return "pro"
    return "flash"


def _clean_news_title(title: str) -> str:
    return re.sub(r"\s*-\s*[^-]+$", "", title).strip()


_NEWS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_NEWS_CACHE_TTL = 600
_NEWS_CACHE_MAX_SIZE = 32

_ARTICLE_CACHE: dict[str, tuple[float, str, str]] = {}
_ARTICLE_CACHE_TTL = 1800
_ARTICLE_CACHE_MAX_SIZE = 32
_RECENT_NEWS_WINDOW_DAYS = 90


def normalize_news_query(query_text: str, max_chars: int = 120) -> str:
    query_text = re.sub(r"\s+", " ", (query_text or "").strip())
    if not query_text:
        return DEFAULT_NEWS_QUERY
    return query_text[:max_chars]


def _prune_news_cache(now: float) -> None:
    expired = [
        key
        for key, (created_at, _) in _NEWS_CACHE.items()
        if now - created_at >= _NEWS_CACHE_TTL
    ]
    for key in expired:
        _NEWS_CACHE.pop(key, None)

    while len(_NEWS_CACHE) >= _NEWS_CACHE_MAX_SIZE:
        oldest_key = min(_NEWS_CACHE, key=lambda key: _NEWS_CACHE[key][0])
        _NEWS_CACHE.pop(oldest_key, None)


def _prune_article_cache(now: float) -> None:
    expired = [
        key
        for key, (created_at, _, _) in _ARTICLE_CACHE.items()
        if now - created_at >= _ARTICLE_CACHE_TTL
    ]
    for key in expired:
        _ARTICLE_CACHE.pop(key, None)

    while len(_ARTICLE_CACHE) >= _ARTICLE_CACHE_MAX_SIZE:
        oldest_key = min(_ARTICLE_CACHE, key=lambda key: _ARTICLE_CACHE[key][0])
        _ARTICLE_CACHE.pop(oldest_key, None)


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

    terms = []
    for part in re.split(r"\s+", normalized):
        cleaned = part.strip().lower()
        if not cleaned or cleaned == "when:1d":
            continue

        sub_terms = re.findall(r"[a-z0-9._-]+|[\u4e00-\u9fff]{2,}", cleaned)
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


def _news_item_url(item: dict) -> str:
    return (item.get("resolved_link") or item.get("link") or "").strip().lower()


def _is_google_news_url(url: str) -> bool:
    try:
        host = (urlparse((url or "").strip()).netloc or "").lower()
    except Exception:
        return False
    return "news.google.com" in host


def _has_direct_article_link(item: dict) -> bool:
    item_url = _news_item_url(item)
    return bool(item_url) and not _is_google_news_url(item_url)


def _display_news_title(title: str, max_chars: int = 28) -> str:
    title = re.sub(r"\s+", " ", (title or "").strip())
    if not title:
        return "未命名条目"
    if len(title) <= max_chars:
        return title
    return title[: max_chars - 3].rstrip() + "..."


def _display_link_host(url: str) -> str:
    try:
        parsed = urlparse((url or "").strip())
    except Exception:
        return ""

    host = (parsed.netloc or "").strip().lower()
    if not host:
        return ""
    return host


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
        resolved_link = resolve_news_link(link)
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
                "resolved_link": resolved_link,
                "_sort_ts": published_ts,
            }
        )

        if len(items) >= max_items:
            break

    return items

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
        pass

    return True


def _extract_resolved_url_from_google_news_html(html: str) -> str:
    patterns = [
        r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+url=(https?://[^"\'>\s]+)',
        r'"(?:url|targetUrl|articleUrl|canonicalUrl)"\s*:\s*"(https?:[^"\\]+)"',
        r'href=["\'](https?://[^"\']+)["\']',
        r'(https?%3A%2F%2F[^"\'>\s]+)',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, html, flags=re.I)
        for match in matches:
            candidate = unquote(match) if "%2F" in match or "%3A" in match else match
            candidate = candidate.replace("\\u0026", "&").replace("\\/", "/")
            if candidate and not _is_google_news_url(candidate):
                return candidate
    return ""


def resolve_news_link(url: str, timeout: int = 6) -> str:
    """
    Try to resolve Google News RSS redirect links to a final article URL.
    If resolution fails, return the original URL.
    """
    url = (url or "").strip()
    if not url:
        return ""

    try:
        parsed = urlparse(url)
        if "news.google.com" not in (parsed.netloc or ""):
            return url

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
                return final_url

            content_type = response.headers.get("Content-Type", "")
            if "html" in content_type.lower():
                payload = response.read(250_000)
                html = _decode_html_payload(payload, content_type)
                extracted_url = _extract_resolved_url_from_google_news_html(html)
                if extracted_url:
                    return extracted_url

        return final_url or url
    except Exception:
        return url


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
        import re

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


def _format_news_items_for_digest(news_items: list[dict]) -> str:
    lines: list[str] = []

    for idx, item in enumerate(news_items, start=1):
        title = item.get("title", "")
        source = item.get("source", "新闻源")
        published_at = item.get("published_at", "今天")
        link = item.get("resolved_link") or item.get("link", "")
        link_host = _display_link_host(link) or "未知来源"
        article_status = item.get("article_status", "仅标题")
        article_excerpt = item.get("article_excerpt", "")

        lines.append(f"{idx}. {title}")
        lines.append(f"来源：{source}")
        lines.append(f"时间：{published_at}")
        lines.append(f"链接域名：{link_host}")
        lines.append(f"正文状态：{article_status}")

        if article_excerpt:
            lines.append("页面文本摘录：")
            lines.append(article_excerpt)

        lines.append("")

    return "\n".join(lines).strip()


def _news_article_coverage_summary(news_items: list[dict]) -> str:
    total = len(news_items)
    with_article_text = sum(
        1
        for item in news_items
        if item.get("article_excerpt")
        or str(item.get("article_status", "")).startswith("正文已读")
    )
    without_article_text = total - with_article_text

    if total <= 0:
        return "本轮没有可用搜索结果。"

    if with_article_text == 0:
        return (
            f"本轮共 {total} 条结果，0 条读到页面文本，{without_article_text} 条仅能依据标题、来源和时间概括。"
            "如果要总结，只能给出保守判断，不要把标题线索写成确定事实。"
        )

    if with_article_text == total:
        return f"本轮共 {total} 条结果，{with_article_text} 条都读到了页面文本，可优先依据页面文本摘录总结。"

    return (
        f"本轮共 {total} 条结果，其中 {with_article_text} 条读到了页面文本，"
        f"{without_article_text} 条只能依据标题、来源和时间概括。"
        "对没有页面文本的条目，必须明确边界，避免写成确定事实。"
    )


def format_news_source_block(query_text: str, news_items: list[dict]) -> str:
    query_text = normalize_news_query(query_text)
    lines = [f"【联网检索】\n查询：{query_text}"]

    for idx, item in enumerate(news_items[:10], start=1):
        title = _display_news_title(item.get("title", ""))
        source = item.get("source", "新闻源")
        published_at = item.get("published_at", "今天")
        link = item.get("resolved_link") or item.get("link", "")
        article_status = item.get("article_status", "仅标题")
        lines.append(f"{idx}. {title}")
        lines.append(f"   来源：{source}｜{published_at}｜{article_status}")
        if link:
            host = _display_link_host(link) or "打开来源"
            lines.append(f"   链接：{host}")

    return "\n".join(lines).strip()


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
    query_text: str = "最新新闻 when:1d", max_items: int = 10
) -> list[dict]:
    query_text = normalize_news_query(query_text)
    cache_key = f"{query_text}|{max_items}"

    now = time.time()
    _prune_news_cache(now)

    cached = _NEWS_CACHE.get(cache_key)
    if cached and now - cached[0] < _NEWS_CACHE_TTL:
        return cached[1][:max_items]

    items = _fetch_query_news_items(query_text, max_items=max_items)

    _NEWS_CACHE[cache_key] = (now, items)
    return items


def fetch_latest_news_items(max_items: int = 10) -> list[dict]:
    return fetch_news_items(DEFAULT_NEWS_QUERY, max_items=max_items)


def generate_news_digest(
    news_items: list[dict],
    performance_mode: str = "standard",
    selected_model: str = "auto",
) -> str:
    if not news_items:
        return ""

    model_profile = _resolve_model_profile(selected_model, performance_mode)
    coverage_summary = _news_article_coverage_summary(news_items)
    items_text = _format_news_items_for_digest(news_items)
    messages = [
        {
            "role": "system",
            "content": (
                "\u4f60\u8981\u57fa\u4e8e\u8054\u7f51\u641c\u7d22\u7ed3\u679c\u6574\u7406\u4e00\u4efd\u7b80\u6d01\u3001\u7ed3\u6784\u5316\u7684\u4e2d\u6587\u6458\u8981\u3002"
                "\u90e8\u5206\u6761\u76ee\u53ef\u80fd\u5305\u542b\u9875\u9762\u6587\u672c\u6458\u5f55\uff0c\u90e8\u5206\u6761\u76ee\u53ef\u80fd\u53ea\u6709\u6807\u9898\u3001\u6765\u6e90\u548c\u65f6\u95f4\u3002\n\n"
                "\u8981\u6c42\uff1a\n"
                "1. \u4f18\u5148\u4f9d\u636e\u201c\u9875\u9762\u6587\u672c\u6458\u5f55\u201d\u603b\u7ed3\uff1b\n"
                "2. \u6ca1\u6709\u9875\u9762\u6587\u672c\u6458\u5f55\u7684\u6761\u76ee\uff0c\u53ea\u80fd\u57fa\u4e8e\u6807\u9898\u3001\u6765\u6e90\u548c\u65f6\u95f4\u8c28\u614e\u6982\u62ec\uff1b\n"
                "3. \u4e0d\u8981\u5047\u88c5\u8bfb\u53d6\u4e86\u6ca1\u6709\u63d0\u4f9b\u7684\u6b63\u6587\uff1b\n"
                "4. \u4e0d\u8981\u8865\u5145\u641c\u7d22\u7ed3\u679c\u4e2d\u6ca1\u6709\u7684\u4fe1\u606f\uff1b\n"
                "5. \u5982\u679c\u6240\u6709\u6761\u76ee\u90fd\u6ca1\u6709\u6b63\u6587\uff0c\u53ea\u80fd\u7ed9\u51fa\u4fdd\u5b88\u5224\u65ad\uff1b\n"
                "6. \u660e\u786e\u6307\u51fa\u54ea\u4e9b\u7ed3\u8bba\u6765\u81ea\u9875\u9762\u6587\u672c\uff0c\u54ea\u4e9b\u53ea\u662f\u6807\u9898\u5c42\u9762\u7684\u7ebf\u7d22\u3002\n\n"
                "\u8f93\u51fa\u683c\u5f0f\uff1a\n"
                "\u3010\u641c\u7d22\u7ed3\u679c\u6458\u8981\u3011\n"
                "1. \u4e3b\u9898\u4e00\n"
                "- \u4e3b\u8981\u4fe1\u606f\n"
                "- \u4f9d\u636e\u6765\u6e90\uff1a\u9875\u9762\u6587\u672c / \u6807\u9898\u6765\u6e90\n"
                "- \u4fe1\u606f\u8fb9\u754c\n"
                "2. \u4e3b\u9898\u4e8c\n"
                "- \u4e3b\u8981\u4fe1\u606f\n"
                "- \u4f9d\u636e\u6765\u6e90\uff1a\u9875\u9762\u6587\u672c / \u6807\u9898\u6765\u6e90\n"
                "- \u4fe1\u606f\u8fb9\u754c\n"
            ),
        },
        {
            "role": "user",
            "content": (
                "\u4e0b\u9762\u662f 5 \u5230 10 \u6761\u641c\u7d22\u7ed3\u679c\u3002\n"
                f"\u6b63\u6587\u8986\u76d6\u60c5\u51b5\uff1a{coverage_summary}\n\n"
                f"{items_text}"
            ),
        },
    ]
    return chat(messages, temperature=0.3, model_profile=model_profile).strip()


def generate_wechat_news_discussion(
    news_digest: str,
    relationship_mode: str = "standard",
    performance_mode: str = "standard",
    selected_model: str = "auto",
) -> str:
    if not news_digest.strip():
        return ""

    model_profile = _resolve_model_profile(selected_model, performance_mode)
    messages = [
        {
            "role": "system",
            "content": (
                "你要根据一段当天新闻摘要，生成四位学习搭子的微信群讨论。"
                "必须由三月七、刻晴、纳西妲、流萤四位角色全部发言。"
                "每位角色都要引用或回应摘要里的具体新闻点，不能空泛安慰，不能只说套话。"
                "输出格式固定为【角色名】\\n内容。"
                "三月七偏轻松和反应，刻晴偏判断和重点，纳西妲偏分析和连接，流萤偏感受和收束。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"当前互动氛围：{relationship_mode}\n"
                f"当前性能模式：{performance_mode}\n\n"
                "请围绕下面这份新闻摘要展开群聊，不要假装用户刚刚发言。\n\n"
                f"{news_digest}"
            ),
        },
    ]
    raw = chat(messages, temperature=0.7, model_profile=model_profile).strip()
    return _ensure_all_roles_reply(raw)


def _load_system_prompt() -> str:
    return _load_text(
        TEMPLATE_FILE,
        "你是微信群聊生成器。根据本轮课后更新摘要，生成四位伙伴的群聊消息。输出格式：【角色名】\\n内容",
    )


def _load_interactive_prompt() -> str:
    return _load_text(
        INTERACTIVE_TEMPLATE,
        "你是微信群聊互动生成器。根据用户消息和群聊历史生成回复。输出格式：【角色名】\\n内容",
    )


def _build_interactive_messages(
    user_text: str,
    relationship_mode: str | None = None,
) -> tuple[list[dict], bool]:
    modes = load_runtime_modes()
    if relationship_mode is None:
        relationship_mode = modes.relationship_mode

    is_first = not modes.first_reaction_done
    prompt = _load_interactive_prompt()
    history = read_wechat_group()
    history_lines = history.splitlines()[-40:] if history else []

    if is_first:
        prompt += (
            "\n\n当前状态：这是这个群聊线程里用户第一次发言。"
            "请体现轻微惊讶和欢迎，但不要过度夸张。"
        )
    else:
        prompt += "\n\n当前状态：这不是第一次发言，请正常继续群聊互动。"

    if relationship_mode == "warm":
        prompt += "\n[互动氛围: warm] 更温和、更鼓励，但不进入恋爱感扮演。"
    elif relationship_mode == "close":
        prompt += (
            "\n[互动氛围: close] 可以更贴近更柔和，但不能生成成人内容，"
            "不能模拟现实恋人，不能削弱学习目标。"
        )

    messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": "【最近群聊】\n"
            + "\n".join(history_lines)
            + f"\n\n【用户刚才说】\n{user_text}\n\n请生成群聊回复。",
        },
    ]
    return messages, is_first


def generate_wechat_messages(
    session_messages: list[dict],
    after_session_updates: dict[str, str],
    memory_bundle: dict[str, str],
    model_profile: ModelProfile = "flash",
    style: str = "标准",
    relationship_mode: str = "standard",
) -> str:
    if not after_session_updates:
        return ""

    context: list[str] = [
        _load_system_prompt() + STYLE_PROMPTS.get(style, STYLE_PROMPTS["标准"])
    ]
    state = read_wechat_state()

    if relationship_mode == "warm":
        context.append(
            "\n[互动氛围: warm] 语气更温和、更鼓励，但仍然保持学习复盘导向。"
        )
    elif relationship_mode == "close":
        context.append(
            "\n[互动氛围: close] 可以更贴近、更温柔，但不能生成成人内容，不能模拟现实恋人，"
            "不能削弱学习目标。"
        )

    if state["user_has_joined"]:
        context.insert(0, "\n[系统说明] 用户已经在群聊里，可以直接对用户说话。")
    else:
        context.insert(0, "\n[系统说明] 当前更像课后反馈场景，不需要假定用户正在看。")

    update_keys = [
        ("session_archive_update", "本轮归档"),
        ("progress_update", "进度更新"),
        ("current_focus_update", "当前重点"),
    ]
    for key, label in update_keys:
        content = after_session_updates.get(key, "")
        if content and all(
            flag not in content for flag in ["失败", "无对话", "无需更新"]
        ):
            context.append(f"\n【{label}】\n{content[:400]}")

    if memory_bundle.get("summary.md"):
        context.append(f"\n【现有摘要参考】\n{memory_bundle['summary.md'][:300]}")

    context.append("\n【最近对话背景】")
    for msg in session_messages[-2:]:
        speaker = "用户" if msg["role"] == "user" else "Agent"
        context.append(f"{speaker}: {msg['content'][:100]}")

    messages = [
        {"role": "system", "content": "\n".join(context)},
        {
            "role": "user",
            "content": f"请生成一版 {style} 风格的微信群消息，每位角色用【角色名】开头。",
        },
    ]
    raw = chat(messages, temperature=0.6, model_profile=model_profile).strip()
    return _ensure_all_roles_reply(raw)


def read_wechat_unread() -> str:
    return _load_text(UNREAD_FILE)


def read_wechat_group() -> str:
    return _load_text(GROUP_FILE)


def has_wechat_unread() -> bool:
    unread = read_wechat_unread()
    return bool(unread and "暂无未读消息" not in unread and "暂无未读" not in unread)


def has_wechat_group_started() -> bool:
    content = read_wechat_group()
    if not _message_blocks(content):
        return False
    if _is_legacy_opening(content):
        return False
    return True


def _is_legacy_opening(content: str) -> bool:
    if "【用户】" in content:
        return False
    return all(marker in content for marker in LEGACY_OPENING_MARKERS)


def generate_wechat_opening(
    role_hint: str = "auto",
    relationship_mode: str = "standard",
    performance_mode: str = "standard",
    selected_model: str = "auto",
) -> str:
    model_profile = _resolve_model_profile(selected_model, performance_mode)
    role_name = ROLE_ID_TO_NAME.get(role_hint, role_hint)
    role_prompt = ""
    if role_hint != "auto":
        role_prompt = load_role(role_hint)[:400]

    atmosphere_prompt = {
        "standard": "气氛自然、轻松、像学习搭子之间的日常接话。",
        "warm": "气氛更温和、更鼓励一点，但不要太煽情。",
        "close": "气氛更贴近、更有陪伴感，但依然清爽克制。",
    }.get(relationship_mode, "气氛自然、轻松。")

    system_prompt = (
        "你要生成一个微信群聊的开场片段。"
        "这是用户进入群聊前，四位角色彼此之间已经聊起来的一小段内容。"
        "必须四位角色全部发言，格式固定为【角色名】\\n内容。"
        "不要提到系统、模型、性能模式，不要出现说明文字。"
        "整体要像已经在聊，而不是正式欢迎词。"
        "四位角色不能提前知道用户会来、正在看、可能看到，不能对用户隔空说话。"
    )
    user_prompt = (
        f"当前角色偏好：{role_name}。\n"
        f"当前互动氛围：{relationship_mode}。{atmosphere_prompt}\n"
        f"当前性能模式：{performance_mode}。{PERFORMANCE_STYLE_HINTS.get(performance_mode, PERFORMANCE_STYLE_HINTS['standard'])}\n"
        "请生成一轮四人开场群聊，让她们像刚刚已经在讨论学习、进度、状态或轻松复盘。\n"
        "如果当前角色不是自动，就让这位角色在气质上稍微更带头一点，但不要压过其他三位。\n"
        "不要出现用户，不要出现旁白，不要出现版本号，不要展开长剧情。\n"
        "禁止出现类似“如果你看到”“你要是来了”“你应该能看到”“把这里当成给你准备的地方”这类句子。"
    )
    if role_prompt:
        user_prompt += f"\n\n当前角色参考设定：\n{role_prompt}"

    opening = chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
        model_profile=model_profile,
    ).strip()
    return _ensure_all_roles_reply(opening)


def start_wechat_group_with_opening(content: str) -> str:
    normalized = _ensure_all_roles_reply(content)
    safe_write_text(GROUP_FILE, normalized + "\n")
    safe_write_text(UNREAD_FILE, "# 未读消息\n\n> 暂无未读消息。\n")
    update_wechat_join_state(
        user_has_joined=False,
        first_reaction_done=False,
        mode="interactive_group",
    )
    return normalized


def append_new_wechat_feedback(content: str) -> None:
    if not content.strip():
        return
    normalized = _ensure_all_roles_reply(content)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    version = load_runtime_modes().current_version
    thread_id = uuid4().hex[:8]
    header = (
        "# 微信群未读消息\n\n"
        f"- 生成时间: {now}\n"
        "- 状态: unread\n"
        f"- 阶段: {version}\n"
        f"- thread_id: {thread_id}\n\n---\n\n"
    )
    safe_write_text(UNREAD_FILE, header + normalized + "\n")
    append_text_safely(GROUP_FILE, normalized + "\n")
    update_wechat_join_state(
        user_has_joined=False,
        first_reaction_done=False,
        mode="unread_feedback",
    )


def append_system_group_note(content: str) -> None:
    if not content.strip():
        return
    current = read_wechat_group()
    prefix = "" if not current.strip() else "\n\n"
    append_text_safely(GROUP_FILE, prefix + content.strip() + "\n")


def append_interactive_group_reply(content: str) -> None:
    if not content.strip():
        return
    normalized = _ensure_all_roles_reply(content)
    append_text_safely(GROUP_FILE, normalized + "\n")
    unread = read_wechat_unread()
    if has_wechat_unread():
        safe_write_text(UNREAD_FILE, unread + "\n\n" + normalized + "\n")
    else:
        safe_write_text(UNREAD_FILE, normalized + "\n")


def append_wechat_messages(content: str) -> None:
    append_new_wechat_feedback(content)


def clear_wechat_unread() -> None:
    safe_write_text(UNREAD_FILE, "# 未读消息\n\n> 暂无未读消息。\n")


def reset_wechat_group() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if GROUP_FILE.is_file():
        old_content = GROUP_FILE.read_text(encoding="utf-8")
        archive_path = ARCHIVE_DIR / f"wechat_group_{ts}.md"
        safe_write_text(archive_path, old_content)
        safe_write_text(GROUP_FILE, "")

    if UNREAD_FILE.is_file():
        safe_write_text(UNREAD_FILE, "# 未读消息\n\n> 暂无未读消息。\n")

    update_wechat_join_state(False, False, "interactive_group")


def mark_wechat_read() -> None:
    clear_wechat_unread()


def read_wechat_state() -> dict:
    modes = load_runtime_modes()
    return {
        "user_has_joined": modes.user_has_joined,
        "first_join_done": modes.first_reaction_done,
        "mode": modes.wechat_mode,
    }


def write_wechat_state(user_has_joined: bool, first_join_done: bool, mode: str):
    update_wechat_join_state(user_has_joined, first_join_done, mode)


def append_user_group_message(user_text: str):
    ts = datetime.now().strftime("%m-%d %H:%M")
    message = f"\n\n【用户】 {ts}\n{user_text}"
    if GROUP_FILE.is_file():
        current = GROUP_FILE.read_text(encoding="utf-8")
        safe_write_text(GROUP_FILE, current + message)
    else:
        safe_write_text(GROUP_FILE, f"# 学习伙伴群\n{message}")


def generate_interactive_wechat_reply(
    user_text: str,
    model_profile: ModelProfile = "flash",
    relationship_mode: str | None = None,
) -> str:
    messages, _is_first = _build_interactive_messages(user_text, relationship_mode)
    raw = chat(messages, temperature=0.7, model_profile=model_profile)
    return _ensure_all_roles_reply(raw.strip())


def generate_interactive_wechat_reply_stream(
    user_text: str,
    model_profile: ModelProfile = "flash",
    relationship_mode: str | None = None,
):
    messages, is_first = _build_interactive_messages(user_text, relationship_mode)
    return stream_chat(messages, temperature=0.7, model_profile=model_profile), is_first


def normalize_interactive_wechat_reply(content: str) -> str:
    return _ensure_all_roles_reply(content)


def search_wechat(keyword: str, max_results: int = 10) -> list[dict]:
    content = read_wechat_group()
    if not content:
        return []
    results = []
    for speaker, text in _message_blocks(content):
        if keyword.lower() in text.lower():
            results.append({"speaker": speaker, "text": text.strip()[:150]})
            if len(results) >= max_results:
                break
    return results


def summarize_wechat(max_chars: int = 500) -> str:
    content = read_wechat_group()
    if not content:
        return "暂无群聊记录"
    lines = content.splitlines()
    dividers = [
        i for i, line in enumerate(lines) if "---" in line or "课后反馈" in line
    ]
    start = dividers[-1] if dividers else max(0, len(lines) - 60)
    recent = "\n".join(lines[start:])
    return recent[:max_chars] + ("..." if len(recent) > max_chars else "")


def count_wechat_messages(content: str) -> int:
    if not content.strip():
        return 0
    return len(_message_blocks(content))
