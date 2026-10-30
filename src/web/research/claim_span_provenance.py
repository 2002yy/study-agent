"""A1: does a claim-level passage exist in the body this run actually read?

Analysis-1A separates three responsibilities that used to be collapsed into one
literal-sentence check: locating a passage for a specific claim, proving that the
passage exists in the text this run saved, and judging whether it supports the
claim. This module implements the middle one and nothing else. A successful
result means "these exact characters occupy ``[start, end)`` of the excerpt this
run stored for that read identity" - never "the page supports the sentence".

Two deliberate choices:

* Offsets are verified, not searched. A verifier that re-finds the text anywhere
  in the page would accept a drifted span and hide a locator bug; the caller
  must name the position and a mismatch is a refusal.
* The authoritative body is the saved excerpt, bounded by
  :data:`read_evidence.EXCERPT_CHARS`. An offset computed against a longer body
  is out of bounds here. It must not be compared with the excerpt digest, and it
  must not be quietly re-located - the result reports that the body was
  truncated so the caller can ask for a deeper read instead of guessing.

A1 grants no support eligibility. Rows only become publishable after A2 locates
candidates, A3 turns a verified ``supports`` verdict into a server-side
qualification, and the existing binder and gate accept it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from src.web.research.read_evidence import (
    EXCERPT_CHARS,
    ReadEvidence,
    normalize_read_url,
)

#: Name of the only body a candidate may be located in.
BODY_SCOPE = "read_excerpt"

# Refusal codes. Each names the rule that failed, so an audit can tell a
# fabricated span from a stale offset without reading the record again.
EVIDENCE_ID_REQUIRED = "evidence_id_required"
EVIDENCE_NOT_IN_RUN = "evidence_not_in_run"
READ_IDENTITY_MISMATCH = "read_identity_mismatch"
URL_MISMATCH = "url_mismatch"
HASH_REQUIRED = "hash_required"
HASH_MISMATCH = "hash_mismatch"
EXCERPT_CORRUPT = "excerpt_corrupt"
SPAN_TEXT_REQUIRED = "span_text_required"
SPAN_OUT_OF_BOUNDS = "span_out_of_bounds"
SPAN_NOT_IN_BODY = "span_not_in_body"


@dataclass(frozen=True)
class ClaimSpan:
    """A candidate passage produced by the locating layer (A2), unverified."""

    claim_id: str
    claim_text: str
    evidence_id: str
    url: str
    read_id: str
    span_start: int
    span_end: int
    span_text: str
    excerpt_sha256: str = ""

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ClaimSpan":
        return cls(
            claim_id=_text(raw.get("claim_id")),
            claim_text=_text(raw.get("claim_text")),
            evidence_id=_text(raw.get("evidence_id")),
            url=_text(raw.get("url")),
            read_id=_text(raw.get("read_id")),
            span_start=_index(raw.get("span_start")),
            span_end=_index(raw.get("span_end")),
            span_text=str(raw.get("span_text") or ""),
            excerpt_sha256=_text(
                raw.get("excerpt_sha256") or raw.get("content_sha256")
            ).lower(),
        )


@dataclass(frozen=True)
class ClaimSpanVerification:
    """The deterministic verdict on one candidate: exists, or why not."""

    span: ClaimSpan
    verified: bool
    reason: str
    body_scope: str
    body_chars: int
    #: The saved excerpt reached the capture bound, so text beyond it was never
    #: stored and cannot be located here. At exactly the bound this is a
    #: conservative "may be truncated" rather than a measured fact.
    body_truncated: bool
    excerpt_sha256: str

    @property
    def locator(self) -> str:
        """``span:start-end`` for a verified passage, empty otherwise.

        An unverified candidate must not be able to render a locator: a citation
        that points at a passage the server refused to confirm is the failure
        this slice exists to prevent.
        """

        if not self.verified:
            return ""
        return f"span:{self.span.span_start}-{self.span.span_end}"

    def as_record(self) -> dict[str, Any]:
        return {
            "claim_id": self.span.claim_id,
            "evidence_id": self.span.evidence_id,
            "url": self.span.url,
            "read_id": self.span.read_id,
            "span_start": self.span.span_start,
            "span_end": self.span.span_end,
            "span_text": self.span.span_text,
            "verified": self.verified,
            "reason": self.reason,
            "locator": self.locator,
            "body_scope": self.body_scope,
            "body_chars": self.body_chars,
            "body_truncated": self.body_truncated,
            "excerpt_sha256": self.excerpt_sha256,
        }


def verify_claim_span(
    candidate: Mapping[str, Any] | ClaimSpan,
    *,
    evidence: Sequence[ReadEvidence],
    evidence_ids: Iterable[str],
) -> ClaimSpanVerification:
    """Verify one candidate against the reads this run really stored.

    ``evidence`` is ``read_evidence.read_evidence_from_records(...)`` for the
    current run, and ``evidence_ids`` is the run's ``research_evidence_refs`` id
    set. Both are inputs rather than lookups: this function performs no I/O and
    cannot invent evidence.
    """

    span = candidate if isinstance(candidate, ClaimSpan) else ClaimSpan.from_mapping(
        candidate
    )
    allowed = {str(item).strip() for item in evidence_ids if str(item).strip()}

    records = [item for item in evidence if item.read_id == span.read_id]
    record = records[0] if len(records) == 1 else None
    body_chars = len(record.excerpt) if record is not None else 0
    stored_hash = record.content_sha256 if record is not None else ""

    reason = _refusal(span, records, allowed)
    return ClaimSpanVerification(
        span=span,
        verified=not reason,
        reason=reason,
        body_scope=BODY_SCOPE,
        body_chars=body_chars,
        body_truncated=body_chars >= EXCERPT_CHARS,
        excerpt_sha256=stored_hash,
    )


def _refusal(
    span: ClaimSpan,
    records: Sequence[ReadEvidence],
    allowed: set[str],
) -> str:
    if not span.evidence_id:
        return EVIDENCE_ID_REQUIRED
    if span.evidence_id not in allowed:
        return EVIDENCE_NOT_IN_RUN
    if not span.span_text:
        return SPAN_TEXT_REQUIRED
    if not span.read_id or len(records) != 1:
        return READ_IDENTITY_MISMATCH
    record = records[0]
    if not span.url or normalize_read_url(span.url) != normalize_read_url(record.url):
        return URL_MISMATCH
    if not _record_is_intact(record):
        return EXCERPT_CORRUPT
    if not span.excerpt_sha256:
        return HASH_REQUIRED
    if span.excerpt_sha256 != record.content_sha256.lower():
        return HASH_MISMATCH
    if not _in_bounds(span, record):
        return SPAN_OUT_OF_BOUNDS
    if record.excerpt[span.span_start : span.span_end] != span.span_text:
        return SPAN_NOT_IN_BODY
    return ""


def _record_is_intact(record: ReadEvidence) -> bool:
    """The saved excerpt still hashes to the digest stored beside it."""

    digest = hashlib.sha256(record.excerpt.encode("utf-8")).hexdigest()
    return digest == record.content_sha256.lower()


def _in_bounds(span: ClaimSpan, record: ReadEvidence) -> bool:
    return 0 <= span.span_start < span.span_end <= len(record.excerpt)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _index(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        # A missing or non-numeric offset is not "0": it must fail the bounds
        # check rather than silently address the start of the page.
        return -1
