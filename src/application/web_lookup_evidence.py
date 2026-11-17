"""Pure source-evidence projections and bounded read policy for web research.

Separated from the durable service to keep URL normalization, inherited notes,
read limits, and synthesis formatting testable without runtime orchestration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.domain.runtime_entities import WebLookupRun
from src.news.digest import format_news_source_block


_INHERITED_ITEM_FIELDS = (
    "title",
    "url",
    "link",
    "href",
    "published_at",
    "published",
    "date",
    "pubDate",
)
_INHERITED_ASSESSMENT_FIELDS = (
    "source_id",
    "title",
    "url",
    "domain",
    "source_type",
    "relevance",
    "directness",
    "freshness",
    "selected",
    "worth_reading",
)
_FOLLOW_UP_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "what",
        "how",
        "请问",
        "继续",
        "一下",
        "关于",
        "这个",
        "那个",
        "什么",
        "如何",
    }
)


def _canonical_source_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw.rstrip("/").lower()
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and key.lower() not in {"fbclid", "gclid"}
        ]
    )
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/") or "/",
            query,
            "",
        )
    )


def _follow_up_tokens(value: str) -> set[str]:
    normalized = str(value or "").lower()
    latin = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9._+-]{1,}", normalized)
        if token not in _FOLLOW_UP_STOPWORDS
    }
    cjk_runs = re.findall(r"[\u3400-\u9fff]+", normalized)
    cjk = {
        run[index : index + 2]
        for run in cjk_runs
        for index in range(max(0, len(run) - 1))
        if run[index : index + 2] not in _FOLLOW_UP_STOPWORDS
    }
    return latin | cjk


def _safe_inherited_source(record: Any) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    raw_item = record.get("item")
    item: dict[str, Any] = raw_item if isinstance(raw_item, dict) else {}
    raw_assessment = record.get("assessment")
    assessment: dict[str, Any] = (
        raw_assessment if isinstance(raw_assessment, dict) else {}
    )
    safe_item = {
        key: item[key]
        for key in _INHERITED_ITEM_FIELDS
        if key in item and isinstance(item[key], (str, int, float, bool, type(None)))
    }
    safe_assessment = {
        key: assessment[key]
        for key in _INHERITED_ASSESSMENT_FIELDS
        if key in assessment
        and isinstance(assessment[key], (str, int, float, bool, type(None)))
    }
    if not safe_item and not safe_assessment:
        return None
    return {
        "item": safe_item,
        "assessment": safe_assessment,
        "evidence_state": "inherited_candidate",
    }


def _bounded_inherited_notes(parent: WebLookupRun) -> list[dict[str, str]]:
    deep = parent.research_context.get("deep")
    raw_notes = deep.get("notes") if isinstance(deep, dict) else []
    successful_urls = {
        _canonical_source_url(_source_url(record))
        for record in parent.selected_sources
        if isinstance(record.get("read"), dict)
        and record["read"].get("status") == "read"
    }
    notes: list[dict[str, str]] = []
    used_chars = 0
    for raw in raw_notes if isinstance(raw_notes, list) else []:
        if not isinstance(raw, dict) or len(notes) >= 8:
            continue
        url = str(raw.get("url") or "").strip()
        facts = str(raw.get("facts") or "").strip()[:1000]
        if not facts or _canonical_source_url(url) not in successful_urls:
            continue
        remaining = 8000 - used_chars
        if remaining <= 0:
            break
        facts = facts[:remaining]
        notes.append(
            {
                "url": url,
                "title": str(raw.get("title") or url)[:300],
                "facts": facts,
            }
        )
        used_chars += len(facts)
    return notes


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


@dataclass(frozen=True)
class ResearchReadBudget:
    max_reads: int = 3
    max_chars_per_source: int = 6000
    max_total_chars: int = 16000

    @classmethod
    def from_env(cls) -> "ResearchReadBudget":
        return cls(
            max_reads=_env_int(
                "WEB_RESEARCH_MAX_READS",
                3,
                minimum=0,
                maximum=8,
            ),
            max_chars_per_source=_env_int(
                "WEB_RESEARCH_MAX_CHARS_PER_SOURCE",
                6000,
                minimum=500,
                maximum=30000,
            ),
            max_total_chars=_env_int(
                "WEB_RESEARCH_MAX_TOTAL_CHARS",
                16000,
                minimum=1000,
                maximum=100000,
            ),
        )

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _source_url(record: dict[str, Any]) -> str:
    assessment = record.get("assessment")
    item = record.get("item")
    if isinstance(assessment, dict) and assessment.get("url"):
        return str(assessment["url"])
    if isinstance(item, dict):
        return str(item.get("url") or item.get("link") or item.get("href") or "")
    return ""


def _is_read_ok(result: dict[str, Any]) -> bool:
    value = result.get("ok")
    return value is True or str(value).strip().lower() == "true"


def _bounded_read_result(
    result: dict[str, Any],
    *,
    max_chars: int,
) -> tuple[dict[str, Any], int]:
    bounded = dict(result)
    used = 0
    for key in ("content", "readme"):
        value = bounded.get(key)
        if not isinstance(value, str):
            continue
        bounded[key] = value[:max_chars]
        used += len(bounded[key])
        if len(value) > max_chars:
            bounded[f"{key}_truncated"] = True
    entries = bounded.get("entries")
    if isinstance(entries, list) and len(entries) > 200:
        bounded["entries"] = entries[:200]
        bounded["entries_truncated"] = True
    return bounded, used


def _read_excerpt(record: dict[str, Any], *, max_chars: int = 3000) -> str:
    read = record.get("read")
    if not isinstance(read, dict) or not _is_read_ok(read):
        return ""
    content = read.get("content") or read.get("readme")
    if isinstance(content, str) and content.strip():
        return content.strip()[:max_chars]
    entries = read.get("entries")
    if isinstance(entries, list):
        paths = [
            str(entry.get("path") or entry.get("name") or "")
            for entry in entries[:80]
            if isinstance(entry, dict)
        ]
        return "\n".join(path for path in paths if path)[:max_chars]
    return ""


def _format_research_source_block(
    query: str,
    items: list[dict[str, Any]],
    selected_sources: list[dict[str, Any]],
) -> str:
    del items  # Candidate metadata alone must never enter synthesis context.
    read_items: list[dict[str, Any]] = []
    read_blocks: list[str] = []
    for index, record in enumerate(selected_sources, start=1):
        excerpt = _read_excerpt(record)
        if not excerpt:
            continue
        raw_item = record.get("item")
        item = raw_item if isinstance(raw_item, dict) else {}
        read_items.append(item)
        raw_assessment = record.get("assessment")
        assessment = raw_assessment if isinstance(raw_assessment, dict) else {}
        title = str(item.get("title") or assessment.get("title") or f"来源 {index}")
        url = str(assessment.get("url") or item.get("url") or item.get("link") or "")
        inherited_note = ""
        if record.get("evidence_state") == "revalidated":
            raw_note = record.get("inherited_note")
            if isinstance(raw_note, dict):
                facts = str(raw_note.get("facts") or "").strip()[:1000]
                if facts:
                    inherited_note = f"\n经重新验证的既有笔记：{facts}"
        read_blocks.append(
            f"【已读取 {index}】{title}\n{url}\n{excerpt}{inherited_note}"
        )
    if not read_blocks:
        return ""
    base = format_news_source_block(query, read_items)
    combined = "\n\n".join(part for part in (base, *read_blocks) if part.strip())
    return combined[:24000]


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value.strip()))
