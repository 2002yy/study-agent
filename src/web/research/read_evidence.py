"""What a revision is allowed to claim as evidence.

A revision could previously present a URL, a quote and a hash of that same quote:
internally consistent, and no proof that the quote came from the page that was
actually read. This module closes that loop by comparing a binding against the
read records the run already holds - the excerpt text that was actually fetched,
addressed by its content hash.

The check is still only about provenance, not about meaning. "This sentence
appears in that page" is what a binding can prove; whether the page supports the
conclusion stays a separate judgement. Collapsing the two is the failure this
module exists to prevent.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

#: The read excerpt is bounded when it is captured; keep the same bound here.
EXCERPT_CHARS = 3000


@dataclass(frozen=True)
class ReadEvidence:
    """One page the run actually read, with the text the model/extractor saw."""

    url: str
    excerpt: str
    content_sha256: str
    round: int = 0

    @classmethod
    def build(cls, *, url: str, excerpt: str, round_index: int = 0) -> "ReadEvidence":
        text = str(excerpt or "")
        return cls(
            url=_normalize_url(url),
            excerpt=text,
            content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            round=round_index,
        )


def _normalize_url(url: object) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    path = parts.path.rstrip("/") or "/"
    query = f"?{parts.query}" if parts.query else ""
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}{query}"


def _read_excerpt(record: Mapping[str, Any]) -> str:
    read = record.get("read")
    if not isinstance(read, Mapping):
        return ""
    if not (read.get("ok") is True or str(read.get("ok")).lower() == "true"):
        return ""
    content = read.get("content") or read.get("readme")
    if isinstance(content, str) and content.strip():
        return content.strip()[:EXCERPT_CHARS]
    entries = read.get("entries")
    if isinstance(entries, list):
        paths = [
            str(entry.get("path") or entry.get("name") or "")
            for entry in entries[:80]
            if isinstance(entry, Mapping)
        ]
        return "\n".join(path for path in paths if path)[:EXCERPT_CHARS]
    return ""


def read_evidence_from_records(
    records: Iterable[Mapping[str, Any]], *, round_index: int = 0
) -> tuple[ReadEvidence, ...]:
    """Turn selected-source records into the evidence a revision may cite."""

    evidence: list[ReadEvidence] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        excerpt = _read_excerpt(record)
        if not excerpt:
            continue
        item = record.get("item") if isinstance(record.get("item"), Mapping) else {}
        assessment = (
            record.get("assessment") if isinstance(record.get("assessment"), Mapping) else {}
        )
        url = str(
            assessment.get("url") or item.get("url") or item.get("link") or item.get("href") or ""
        )
        if not url.strip():
            continue
        evidence.append(
            ReadEvidence.build(url=url, excerpt=excerpt, round_index=round_index)
        )
    return tuple(evidence)


def _quote_matches(quote: str, excerpt: str) -> bool:
    needle = re.sub(r"\s+", " ", str(quote or "")).strip()
    if len(needle) < 8:
        return False
    haystack = re.sub(r"\s+", " ", excerpt)
    return needle in haystack


def verify_binding(
    binding: Mapping[str, Any], evidence: Sequence[ReadEvidence]
) -> str:
    """Return "" when the binding is backed by a real read, else the refusal code."""

    url = _normalize_url(binding.get("url"))
    if not url:
        return "binding_without_url"
    quote = str(binding.get("quote") or "")
    if not quote.strip():
        return "binding_without_quote"
    expected = str(binding.get("content_sha256") or "").strip().lower()
    if expected and expected != hashlib.sha256(quote.encode("utf-8")).hexdigest():
        return "binding_hash_mismatch"
    candidates = [item for item in evidence if _normalize_url(item.url) == url]
    if not candidates:
        return "source_not_read"
    for item in candidates:
        if _quote_matches(quote, item.excerpt):
            return ""
    return "quote_not_in_read"


def verify_bindings(
    bindings: Sequence[Mapping[str, Any]], evidence: Sequence[ReadEvidence]
) -> str:
    """Return "" only when every binding is backed by a real read."""

    if not bindings:
        return "binding_required"
    for binding in bindings:
        refusal = verify_binding(binding, evidence)
        if refusal:
            return refusal
    return ""
