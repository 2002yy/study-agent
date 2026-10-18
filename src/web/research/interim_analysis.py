"""Bound provisional analysis to existing read notes; never grant answer authority."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.web.tool_evidence import _public_url


def _text(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def analysis_sources(notes: list[dict[str, Any]]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
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
                        "title": (_text(note.get("title")) or url)[:160], "excerpt": excerpt})
        if len(sources) == 4:
            break
    return list(reversed(sources))


def validate_interim_analysis(raw: Any, sources: list[dict[str, str]]) -> dict[str, Any] | None:
    """Require real source identities and exact quotes; this is not entailment judging."""
    if not isinstance(raw, dict):
        return None
    raw_text = raw.get("text")
    text = "\n\n".join(_text(line) for line in raw_text.splitlines() if _text(line)) if isinstance(raw_text, str) else ""
    citations = raw.get("citations")
    if not text or len(text) > 400 or not isinstance(citations, list) or not 1 <= len(citations) <= 3:
        return None
    by_id = {source["source_id"]: source for source in sources}
    bound: list[dict[str, str]] = []
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
            bound.append({key: source[key] for key in ("source_id", "url", "title", "question")} | {"quote": quote})
    return {"status": "provisional", "text": text, "citations": bound}


def interim_revision(deep: dict[str, Any]) -> str:
    entries = deep.get("steering")
    receipts = [{"id": entry.get("id"), "content": entry.get("content")}
                for entry in (entries if isinstance(entries, list) else []) if isinstance(entry, dict)]
    payload = {"steering": receipts, "corrections": deep.get("corrections", []),
               "effective_query": deep.get("effective_query", "")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
