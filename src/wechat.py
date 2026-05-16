"""Compatibility facade for legacy imports.

New code should import from:
- src.wechat_state
- src.wechat_generator
- src.wechat_prompt
- src.wechat_format
- src.news.rss_fetcher
- src.news.article_fetcher
- src.news.link_resolver
- src.news.digest
"""

from __future__ import annotations

from src.wechat_format import (  # noqa: F401
    LEGACY_OPENING_MARKERS,
    PERFORMANCE_STYLE_HINTS,
    ROLE_ID_TO_NAME,
    STYLE_PROMPTS,
    WECHAT_BLOCK_PATTERN,
    WECHAT_MISSING_ROLE_FALLBACKS,
    WECHAT_ROLE_ORDER,
    _ensure_all_roles_reply,
    _format_role_blocks,
    _is_legacy_opening,
    _message_blocks,
)
from src.wechat_state import (  # noqa: F401
    append_interactive_group_reply,
    append_new_wechat_feedback,
    append_system_group_note,
    append_user_group_message,
    append_wechat_messages,
    clear_wechat_unread,
    count_wechat_messages,
    has_wechat_group_started,
    has_wechat_unread,
    mark_wechat_read,
    read_wechat_group,
    read_wechat_state,
    read_wechat_unread,
    reset_wechat_group,
    search_wechat,
    start_wechat_group_with_opening,
    summarize_wechat,
    write_wechat_state,
)
from src.wechat_generator import (  # noqa: F401
    generate_interactive_wechat_reply,
    generate_interactive_wechat_reply_stream,
    generate_wechat_messages,
    generate_wechat_news_discussion,
    generate_wechat_opening,
    normalize_interactive_wechat_reply,
)
from src.news.rss_fetcher import (  # noqa: F401
    DEFAULT_NEWS_QUERY,
    NEWS_FEED_URL,
    BING_NEWS_FEED_URL,
    DOMESTIC_NEWS_FEEDS,
    _NEWS_CACHE,
    _NEWS_CACHE_TTL,
    _NEWS_CACHE_MAX_SIZE,
    _RECENT_NEWS_WINDOW_DAYS,
    _clean_news_title,
    _count_query_term_matches,
    _dedupe_and_trim_news_items,
    _fetch_query_news_items,
    _fetch_rss_items_from_url,
    _is_default_news_query,
    _is_recent_news_item,
    _news_item_sort_key,
    _parse_news_pub_date,
    _preferred_source_domains,
    _prune_cache,
    _prune_news_cache,
    _query_terms,
    _title_matches_query,
    fetch_latest_news_items,
    fetch_news_items,
    normalize_news_query,
)
from src.news.article_fetcher import (  # noqa: F401
    _ARTICLE_CACHE,
    _article_fetch_priority,
    _check_dns_target_safe,
    _is_fetchable_article_url,
    enrich_news_items_with_article_text,
    fetch_article_text,
    fetch_article_text_with_method,
)
from src.news.link_resolver import (  # noqa: F401
    _display_link_host,
    _extract_resolved_url_from_google_news_html,
    _has_direct_article_link,
    _is_google_news_url,
    _news_item_url,
    resolve_news_link,
)
from src.news.digest import (  # noqa: F401
    _display_news_title,
    _format_news_items_for_digest,
    _news_article_coverage_summary,
    format_news_source_block,
    generate_news_digest,
)
from src.news.article_extractor import (  # noqa: F401
    clean_article_text as _clean_article_text,
    decode_html_payload as _decode_html_payload,
    extract_article_text as _extract_article_text,
    extract_article_text_with_fallback_parser as _extract_article_text_with_fallback_parser,
)
