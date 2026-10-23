"""Bound provisional analysis to existing read notes; never grant answer authority."""

from __future__ import annotations

import hashlib
import json
from typing import Any, TypedDict

from src.web.tool_evidence import _public_url


class AnalysisSource(TypedDict):
    """One read note as an interim-analysis source.

    ``round`` is kept explicit (rather than widening every value to ``Any``) so
    the reader round stays type-checked wherever attribution is decided.
    """

    source_id: str
    url: str
    question: str
    title: str
    excerpt: str
    round: int | None


class BoundCitation(TypedDict):
    """One validated citation of a provisional judgment.

    ``round`` is the reader round the quoted material came from; a citation
    without one can never satisfy the supplement attribution condition.
    """

    source_id: str
    url: str
    title: str
    question: str
    round: int | None
    quote: str


def _text(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def analysis_sources(notes: list[dict[str, Any]]) -> list[AnalysisSource]:
    sources: list[AnalysisSource] = []
    seen: set[tuple[str, str]] = set()
    for note in reversed(notes[-80:]):
        if not isinstance(note, dict) or note.get("superseded"):
            continue
        try:
            url = _public_url(note.get("url"))
        except ValueError:
            continue
        excerpt = _text(note.get("facts"))[:280]
        question = _text(note.get("sub_question"))[:160]
        if not url or not excerpt:
            continue
        source_id = "s_" + hashlib.sha256(f"{url}:{question}:{excerpt}".encode()).hexdigest()[:20]
        identity = (url, question)
        if identity in seen:
            continue
        seen.add(identity)
        sources.append({"source_id": source_id, "url": url, "question": question,
                        "title": (_text(note.get("title")) or url)[:160], "excerpt": excerpt,
                        "round": note.get("round") if isinstance(note.get("round"), int) else None})
        if len(sources) == 4:
            break
    return list(reversed(sources))


def validate_interim_analysis(
    raw: Any, sources: list[AnalysisSource]
) -> dict[str, Any] | None:
    """Require real source identities and exact quotes; this is not entailment judging."""
    if not isinstance(raw, dict):
        return None
    raw_text = raw.get("text")
    text = "\n\n".join(_text(line) for line in raw_text.splitlines() if _text(line)) if isinstance(raw_text, str) else ""
    citations = raw.get("citations")
    if not text or len(text) > 400 or not isinstance(citations, list) or not 1 <= len(citations) <= 3:
        return None
    by_id = {source["source_id"]: source for source in sources}
    bound: list[BoundCitation] = []
    seen: set[tuple[str, str]] = set()
    for citation in citations:
        if not isinstance(citation, dict) or not isinstance(citation.get("source_id"), str):
            return None
        source = by_id.get(citation["source_id"])
        quote = _text(citation.get("quote"))
        if source is None or not 12 <= len(quote) <= 240 or quote not in source["excerpt"]:
            return None
        identity = (source["source_id"], quote)
        if identity not in seen:
            seen.add(identity)
            bound.append(
                {
                    "source_id": source["source_id"],
                    "url": source["url"],
                    "title": source["title"],
                    "question": source["question"],
                    "round": source["round"],
                    "quote": quote,
                }
            )
    return {"status": "provisional", "text": text, "citations": bound}


def interim_revision(deep: dict[str, Any]) -> str:
    entries = deep.get("steering")
    receipts = [{"id": entry.get("id"), "content": entry.get("content")}
                for entry in (entries if isinstance(entries, list) else []) if isinstance(entry, dict)]
    payload = {"steering": receipts, "corrections": deep.get("corrections", []),
               "effective_query": deep.get("effective_query", "")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
