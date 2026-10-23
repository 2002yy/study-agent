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
    """One page the run actually read, with the text the model/extractor saw.

    ``read_id`` names *this read attempt*, so two reads of the same URL in
    different rounds stay distinguishable and a binding can point at one of them.
    """

    url: str
    excerpt: str
    content_sha256: str
    round: int = 0
    read_id: str = ""

    @classmethod
    def build(
        cls, *, url: str, excerpt: str, round_index: int = 0, read_id: str = ""
    ) -> "ReadEvidence":
        text = str(excerpt or "")
        return cls(
            url=_normalize_url(url),
            excerpt=text,
            content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            round=round_index,
            read_id=str(read_id or ""),
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
    read = _mapping(record.get("read"))
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


def _mapping(value: Any) -> Mapping[str, Any]:
    """A mapping, or an empty one. Keeps `record.get(...)` chains type-safe."""

    return value if isinstance(value, Mapping) else {}


def read_id_for(*, run_id: str, url: str, round_index: int, attempt: int) -> str:
    """Stable identity of one read attempt.

    Derived from what is persisted (run, page, round, attempt ordinal) and never
    from a timestamp, so a restart that replays the same read produces the same
    identity instead of a second event.
    """

    payload = "|".join(
        [
            str(run_id or ""),
            _normalize_url(url),
            str(int(round_index)),
            str(int(attempt)),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def read_attempts(records: Iterable[Mapping[str, Any]], url: str) -> int:
    """How many records already carry a read of this page (the attempt ordinal)."""

    target = _normalize_url(url)
    count = 0
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if not _mapping(record.get("read")):
            continue
        item = _mapping(record.get("item"))
        assessment = (
            _mapping(record.get("assessment"))
        )
        candidate = str(
            assessment.get("url") or item.get("url") or item.get("link") or item.get("href") or ""
        )
        if _normalize_url(candidate) == target:
            count += 1
    return count


def read_evidence_from_records(
    records: Iterable[Mapping[str, Any]],
    *,
    round_index: int = 0,
    run_id: str = "",
) -> tuple[ReadEvidence, ...]:
    """Turn selected-source records into the evidence a revision may cite."""

    evidence: list[ReadEvidence] = []
    seen: dict[str, int] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        excerpt = _read_excerpt(record)
        if not excerpt:
            continue
        item = _mapping(record.get("item"))
        assessment = (
            _mapping(record.get("assessment"))
        )
        url = str(
            assessment.get("url") or item.get("url") or item.get("link") or item.get("href") or ""
        )
        if not url.strip():
            continue
        key = _normalize_url(url)
        seen[key] = seen.get(key, 0) + 1
        evidence.append(
            ReadEvidence.build(
                url=url,
                excerpt=excerpt,
                round_index=round_index,
                read_id=str(record.get("read_id") or "")
                or read_id_for(
                    run_id=run_id or str(record.get("run_id") or ""),
                    url=url,
                    round_index=round_index,
                    attempt=seen[key],
                ),
            )
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
    # Two different digests: the quote's own hash proves the text was not altered
    # in transit; the read excerpt's hash says *which read* the quote is claimed to
    # come from. Conflating them let a caller invent both and still pass.
    quote_hash = str(binding.get("quote_sha256") or "").strip().lower()
    legacy_hash = str(binding.get("content_sha256") or "").strip().lower()
    expected_quote = quote_hash or legacy_hash
    if expected_quote and expected_quote != hashlib.sha256(quote.encode("utf-8")).hexdigest():
        return "binding_hash_mismatch"
    candidates = [item for item in evidence if _normalize_url(item.url) == url]
    if not candidates:
        return "source_not_read"
    read_id = str(binding.get("read_id") or "").strip()
    if read_id:
        candidates = [item for item in candidates if item.read_id == read_id]
        if not candidates:
            return "read_id_not_found"
    excerpt_hash = str(binding.get("read_excerpt_sha256") or "").strip().lower()
    if excerpt_hash:
        candidates = [
            item for item in candidates if item.content_sha256.lower() == excerpt_hash
        ]
        if not candidates:
            return "read_excerpt_not_found"
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


# -- AR-1C-2-E: one event per read attempt ------------------------------------
def _record_url(record: Mapping[str, Any]) -> str:
    item = _mapping(record.get("item"))
    assessment = (
        _mapping(record.get("assessment"))
    )
    return str(
        assessment.get("url") or item.get("url") or item.get("link") or item.get("href") or ""
    )


def build_read_event(
    *,
    run_id: str,
    records: Sequence[Mapping[str, Any]],
    record: Mapping[str, Any],
    round_index: int,
    notes: int,
    revision: str,
    at: str,
    task_id: str = "",
):
    """The event for one finished read attempt, or None when none was attempted.

    A page that was skipped (not worth reading, budget exhausted) produced no
    material and no attempt: emitting an event for it would inflate the record of
    what the run actually learned.
    """

    from src.web.research.motion_events import (
        EVIDENCE_READ,
        READ_FAILED,
        MotionEvent,
    )

    read = _mapping(record.get("read"))
    if not isinstance(read, Mapping):
        return None
    status = str(read.get("status") or "")
    if status not in {"read", "failed"}:
        return None
    url = _record_url(record)
    if not url.strip():
        return None
    attempt = max(1, read_attempts(records, url))
    read_id = read_id_for(
        run_id=run_id, url=url, round_index=round_index, attempt=attempt
    )
    detail = {
        "read_id": read_id,
        "url": _normalize_url(url),
        "task_id": str(task_id or ""),
    }
    if status == "read":
        excerpt = _read_excerpt(record)
        if not excerpt:
            # "Read" without usable text is not material; record it as the failure
            # it is rather than as evidence.
            detail["reason"] = "no_usable_content"
            return MotionEvent(
                kind=READ_FAILED,
                at=at,
                event_id=read_id,
                round=int(round_index),
                notes=int(notes),
                revision=str(revision),
                cause="读取成功但没有可用正文",
                detail=detail,
            )
        detail["excerpt_sha256"] = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        return MotionEvent(
            kind=EVIDENCE_READ,
            at=at,
            event_id=read_id,
            round=int(round_index),
            notes=int(notes),
            revision=str(revision),
            cause="读取到一个可用来源",
            detail=detail,
        )
    detail["reason"] = str(read.get("error") or read.get("reason") or "read_failed")[:200]
    return MotionEvent(
        kind=READ_FAILED,
        at=at,
        event_id=read_id,
        round=int(round_index),
        notes=int(notes),
        revision=str(revision),
        cause="读取失败",
        detail=detail,
    )


def round_read_summary(
    records: Iterable[Mapping[str, Any]],
    events: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, int]]:
    """Per-round activity, derived from the authoritative read records.

    ``recheck`` counts conflicts that an actual evaluation raised; it is never
    inferred from how many pages were read.
    """

    rounds: dict[int, dict[str, int]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        read = _mapping(record.get("read"))
        if not isinstance(read, Mapping):
            continue
        status = str(read.get("status") or "")
        if status not in {"read", "failed"}:
            continue
        round_index = int(read.get("round") or 0)
        bucket = rounds.setdefault(round_index, {"round": round_index, "read": 0, "failed": 0, "recheck": 0})
        bucket["read" if status == "read" else "failed"] += 1
    for event in events:
        if not isinstance(event, Mapping):
            continue
        if str(event.get("kind") or "") != "evidence_conflict":
            continue
        round_index = int(event.get("round") or 0)
        bucket = rounds.setdefault(round_index, {"round": round_index, "read": 0, "failed": 0, "recheck": 0})
        bucket["recheck"] += 1
    return [rounds[key] for key in sorted(rounds)]
