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


_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")
_LATIN_TOKEN = re.compile(r"[a-z0-9]+")
# "千冶·刃", "千冶・刃" and "千冶刃" are the same entity; punctuation between two
# CJK characters must not split it into a stray one-character unit.
_CJK_JOINER = re.compile(r"(?<=[\u3400-\u9fff])[·・\-—–/／|,，、]+(?=[\u3400-\u9fff])")
# English function words carry no topical signal and made a page that happened to
# contain "the ... of" look relevant. They are dropped symmetrically from the
# query and the document, so nothing is biased by one side only.
_LATIN_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can",
        "do", "does", "for", "from", "had", "has", "have", "how", "if", "in",
        "into", "is", "it", "its", "may", "not", "of", "on", "or", "should",
        "than", "that", "the", "their", "then", "there", "these", "this",
        "those", "to", "was", "were", "what", "when", "where", "which", "who",
        "why", "will", "with", "would", "you", "your",
    }
)


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
    """Topical units: latin words plus CJK bigrams, never single CJK characters.

    Single-character CJK overlap is what made a Baidu dictionary page for 星 look
    relevant to "星铁 遗器": one shared character out of twelve was enough. A CJK
    bigram only matches when two consecutive characters agree, so a dictionary
    entry no longer competes with a page about the asked entity. A one-character
    run (a query that really is one character) still yields that character.
    """

    folded = _CJK_JOINER.sub("", value.casefold())
    tokens = {
        token
        for token in _LATIN_TOKEN.findall(folded)
        if len(token) > 1 and token not in _LATIN_STOPWORDS
    }
    for run in _CJK_RUN.findall(folded):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


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
    # 0.6 rather than 0.75: with CJK bigrams a page that covers five of seven
    # topical units is clearly about the query, and the old threshold called it
    # "weak" only because the unit count is now honest.
    if overlap >= 0.6:
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
            # Lexical relevance is a hint, not a veto on reading a valid URL.
            # A Chinese query can retrieve an English answer page.
            worth_reading=not reason and bool(url),
        )
        record = {"item": dict(item), "assessment": assessment.to_dict()}
        (selected if assessment.selected else rejected).append(record)

    return selected, rejected


def evidence_confidence(selected_sources: list[dict[str, Any]]) -> str:
    """Diagnose coverage from actual reads; never infer factual support."""
    assessments = [
        record.get("assessment") or {}
        for record in selected_sources
        if isinstance(record, dict)
        and isinstance(record.get("read"), dict)
        and record["read"].get("status") == "read"
        and isinstance(record.get("assessment"), dict)
    ]
    if not assessments:
        return "none"
    direct = sum(
        str(assessment.get("directness", "")).startswith("direct_")
        for assessment in assessments
    )
    if direct >= 2:
        return "high"
    # Two unrelated pages are not medium evidence merely by their count.
    related = sum(
        bool(assessment.get("directness"))
        and assessment["directness"] != "unmatched"
        for assessment in assessments
    )
    if direct >= 1 or related >= 2:
        return "medium"
    return "low"
