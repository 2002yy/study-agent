"""Date-aware query normalization for public web research.

The normalizer is intentionally deterministic. It does not claim that a model or
product exists; it only produces stable search variants and records the date
context used by the research run.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
from typing import Any

_GPT_MODEL_PATTERN = re.compile(
    r"(?i)\bgpt[\s_-]*(\d+)(?:[.\s_-]+(\d+))?[\s._-]*(sol)?\b"
)
_EXPLICIT_YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
_SEARCH_DIRECTIVE_PATTERNS = (
    re.compile(
        r"^(?:请|帮我|麻烦)?\s*(?:联网|上网)?\s*"
        r"(?:看看|查查|查一下|查询一下|查询|查|搜搜|搜一下|搜索一下|搜索|"
        r"检索一下|检索|了解一下|了解)\s*[:：]?\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:please\s+)?(?:search(?:\s+the\s+web)?(?:\s+for)?|look\s+up|find\s+out)\s*[:：]?\s*",
        re.IGNORECASE,
    ),
)
_TODAY_MARKERS = ("today", "今天", "今日", "当天")
_LATEST_MARKERS = (
    "latest",
    "current",
    "newest",
    "最新",
    "当前版本",
    "刚发布",
)
_RECENT_MARKERS = ("recent", "recently", "近期", "最近", "近况", "新进展")


@dataclass(frozen=True)
class QueryNormalization:
    raw_query: str
    canonical_query: str
    query_variants: tuple[str, ...]
    as_of_date: str
    freshness_days: int | None
    freshness_requested: bool
    entity_aliases: tuple[str, ...] = ()
    search_directive_removed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _compact_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _strip_search_directive(value: str) -> tuple[str, bool]:
    focused = value
    for pattern in _SEARCH_DIRECTIVE_PATTERNS:
        stripped = pattern.sub("", focused, count=1).strip()
        if stripped != focused and stripped:
            return stripped, True
    return focused, False


def _canonical_gpt_name(match: re.Match[str]) -> str:
    major = match.group(1)
    minor = match.group(2)
    suffix = match.group(3)
    version = major if not minor else f"{major}.{minor}"
    return f"GPT-{version}{' Sol' if suffix else ''}"


def canonicalize_entity_names(query: str) -> tuple[str, tuple[str, ...]]:
    """Return a canonical query and the aliases that were normalized."""

    aliases: list[str] = []

    def replace_gpt(match: re.Match[str]) -> str:
        original = match.group(0)
        canonical = _canonical_gpt_name(match)
        if original.casefold() != canonical.casefold():
            aliases.append(original)
        return canonical

    canonical = _GPT_MODEL_PATTERN.sub(replace_gpt, _compact_spaces(query or ""))
    return canonical, tuple(dict.fromkeys(aliases))


def freshness_window_days(query: str) -> int | None:
    lowered = query.casefold()
    if any(marker in lowered for marker in _TODAY_MARKERS):
        return 1
    if any(marker in lowered for marker in _LATEST_MARKERS):
        return 30
    if any(marker in lowered for marker in _RECENT_MARKERS):
        return 60
    return None


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = _compact_spaces(value)
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return tuple(result)


def normalize_web_query(query: str, *, now: datetime | None = None) -> QueryNormalization:
    current = _utc_now(now)
    raw = _compact_spaces(query or "")
    focused, directive_removed = _strip_search_directive(raw)
    canonical, aliases = canonicalize_entity_names(focused)
    freshness_days = freshness_window_days(raw)

    variants: list[str] = []
    # Search the focused canonical entity first. The focused raw spelling and
    # complete user request remain fallbacks for uncommon provider tokenization.
    variants.append(canonical or focused or raw)
    variants.append(focused)
    variants.append(raw)
    if canonical.startswith("GPT-"):
        variants.append(f"{canonical} OpenAI")
    if freshness_days is not None and not _EXPLICIT_YEAR_PATTERN.search(raw):
        variants.append(f"{canonical or focused or raw} {current.strftime('%B %Y')}")

    return QueryNormalization(
        raw_query=raw,
        canonical_query=canonical or focused or raw,
        query_variants=_dedupe(variants),
        as_of_date=current.date().isoformat(),
        freshness_days=freshness_days,
        freshness_requested=freshness_days is not None,
        entity_aliases=aliases,
        search_directive_removed=directive_removed,
    )
