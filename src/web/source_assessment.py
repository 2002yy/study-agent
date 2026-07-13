"""Deterministic source assessment for bounded web research.

This layer judges source usability and directness, not truth. It intentionally
avoids publisher whitelists: trust and claim verification belong to later
research stages that can read and cross-check source content.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any
from urllib.parse import urlparse


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]", re.IGNORECASE)


@dataclass(frozen=True)
class SourceAssessment:
    source_id: str
    title: str
    url: str
    domain: str
    source_type: str
    relevance: float
    directness: str
    freshness: str
    selected: bool
    rejection_reason: str = ""
    duplicate_of: str = ""
    worth_reading: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _url(item: dict[str, Any]) -> str:
    return _text(item.get("url") or item.get("link") or item.get("href"))


def _domain(url: str, item: dict[str, Any]) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or _text(item.get("source")).lower()


def _source_type(item: dict[str, Any], domain: str) -> str:
    explicit = _text(item.get("source_type") or item.get("type")).lower()
    if explicit:
        return explicit
    if any(item.get(key) for key in ("published_at", "published", "date", "pubDate")):
        return "news"
    return "web" if domain else "unknown"


def _freshness(item: dict[str, Any]) -> str:
    value = _text(
        item.get("published_at")
        or item.get("published")
        or item.get("date")
        or item.get("pubDate")
    )
    return "reported" if value else "unknown"


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_PATTERN.findall(value)}


def _relevance(
    *,
    canonical_query: str,
    title: str,
    snippet: str,
) -> tuple[float, str]:
    query = canonical_query.casefold().strip()
    title_folded = title.casefold()
    snippet_folded = snippet.casefold()
    if query and query in title_folded:
        return 1.0, "direct_title"
    if query and query in snippet_folded:
        return 0.85, "direct_snippet"

    query_tokens = _tokens(canonical_query)
    if not query_tokens:
        return 0.0, "unknown"
    title_tokens = _tokens(title)
    snippet_tokens = _tokens(snippet)
    title_overlap = len(query_tokens & title_tokens) / len(query_tokens)
    snippet_overlap = len(query_tokens & snippet_tokens) / len(query_tokens)
    overlap = max(title_overlap, snippet_overlap)
    if overlap >= 0.75:
        return round(0.7 + overlap * 0.2, 3), "contextual"
    if overlap > 0:
        return round(0.3 + overlap * 0.3, 3), "weak"
    return 0.1, "unmatched"


def _dedupe_key(title: str, url: str) -> str:
    if url:
        parsed = urlparse(url)
        return (
            f"url:{parsed.scheme.lower()}://"
            f"{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
        )
    return f"title:{title.casefold()}"


def assess_sources(
    items: list[dict[str, Any]],
    *,
    canonical_query: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return selected and rejected source records with deterministic metadata."""

    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: dict[str, str] = {}

    for index, item in enumerate(items):
        title = _text(item.get("title"))
        url = _url(item)
        snippet = _text(
            item.get("snippet")
            or item.get("summary")
            or item.get("description")
        )
        domain = _domain(url, item)
        source_id = _text(item.get("id")) or f"web_source_{index + 1}"
        relevance, directness = _relevance(
            canonical_query=canonical_query,
            title=title,
            snippet=snippet,
        )

        reason = ""
        duplicate_of = ""
        if not title and not url:
            reason = "missing_title_and_url"
        elif not url and not domain:
            reason = "missing_source_identifier"
        elif url and urlparse(url).scheme not in {"http", "https"}:
            reason = "invalid_url"
        else:
            key = _dedupe_key(title, url)
            duplicate_of = seen.get(key, "")
            if duplicate_of:
                reason = "duplicate"
            else:
                seen[key] = source_id

        assessment = SourceAssessment(
            source_id=source_id,
            title=title,
            url=url,
            domain=domain,
            source_type=_source_type(item, domain),
            relevance=relevance,
            directness=directness,
            freshness=_freshness(item),
            selected=not reason,
            rejection_reason=reason,
            duplicate_of=duplicate_of,
            worth_reading=not reason and bool(url) and directness != "unmatched",
        )
        record = {"item": dict(item), "assessment": assessment.to_dict()}
        (selected if assessment.selected else rejected).append(record)

    return selected, rejected


def evidence_confidence(selected_sources: list[dict[str, Any]]) -> str:
    """Estimate evidence coverage without claiming that the facts are true."""

    if not selected_sources:
        return "none"
    assessments = [
        record.get("assessment", {})
        for record in selected_sources
        if isinstance(record, dict)
    ]
    direct = sum(
        1
        for assessment in assessments
        if str(assessment.get("directness", "")).startswith("direct_")
    )
    if direct >= 2:
        return "high"
    if direct >= 1 or len(assessments) >= 2:
        return "medium"
    return "low"
