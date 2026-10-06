"""Standard-3: bind a readable source to a fact, mechanically.

Standard-2 only marks a body as acquired and readable; a requested field stays
``NOT_EVALUATED``. This module is the next step: it turns a candidate claim into a
verifiable binding, or refuses to.

The invariant it exists to protect:

    readable source != factual support != publication authority

Two things must be mechanically true before a claim can support a field.

**Identity is bound, not merely non-empty.** A claim names a source; that source must be one
of the trusted Standard-2 records, the body must hash to the recorded digest, and the URL and
digest must match. A fabricated digest or a URL that does not correspond to a trusted record
is rejected - it can never become support.

**The value is derived, not asserted.** The caller proposes a span; the module locates it by
exact offset and derives the normalized value with a deterministic normalizer for that field.
A value the caller asserts is only accepted when it equals the derived one. If no
deterministic normalizer exists for the field, the span is verified but the status is
``SPAN_BOUND`` - never promoted to ``SUPPORT``.

A keyword appearing in the text is not support. Two sources that disagree produce a conflict;
they are never averaged or overwritten. Anything undecidable abstains. Nothing here grants
publication authority.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Iterable, Mapping

SUPPORT = "SUPPORT"
CONFLICT = "CONFLICT"
SPAN_BOUND = "SPAN_BOUND"
INSUFFICIENT = "INSUFFICIENT"
NOT_EVALUATED = "NOT_EVALUATED"

BINDING_STATES = (SUPPORT, CONFLICT, SPAN_BOUND, INSUFFICIENT, NOT_EVALUATED)

_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_SEMVER = re.compile(r"\b(\d+\.\d+(?:\.\d+)?)\b")


@dataclass(frozen=True)
class TrustedSource:
    """A Standard-2 source record. The body is trusted only if it hashes to the digest."""

    url: str
    content_sha256: str
    body: str

    def digest_matches(self) -> bool:
        return hashlib.sha256(str(self.body).encode("utf-8")).hexdigest() == str(
            self.content_sha256
        ).lower()


@dataclass(frozen=True)
class Claim:
    """A proposed fact binding. The span must be verifiable in the body."""

    field: str
    source_url: str
    source_sha256: str
    span_text: str
    normalized_value: str = ""
    source_role: str = ""
    span_start: int = -1
    span_end: int = -1

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "source_url": self.source_url,
            "source_sha256": self.source_sha256,
            "span_text": self.span_text,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "normalized_value": self.normalized_value,
            "source_role": self.source_role,
        }


def _normalize_date(span: str) -> str | None:
    match = _ISO_DATE.search(str(span))
    if not match:
        return None
    try:
        return date(
            int(match.group(1)), int(match.group(2)), int(match.group(3))
        ).isoformat()
    except ValueError:
        return None


def _normalize_version(span: str) -> str | None:
    match = _SEMVER.search(str(span))
    return match.group(1) if match else None


# Deterministic, field-level normalizers. A field with no normalizer yields SPAN_BOUND, not
# SUPPORT - we will not promote "this text exists" to "this text means this value".
_NORMALIZERS: dict[str, Callable[[str], str | None]] = {
    "release_date": _normalize_date,
    "date": _normalize_date,
    "published": _normalize_date,
    "version": _normalize_version,
    "release_version": _normalize_version,
}


def normalizer_for(field: str) -> Callable[[str], str | None] | None:
    name = str(field or "").lower()
    if name in _NORMALIZERS:
        return _NORMALIZERS[name]
    if name.endswith("_date") or name.endswith("_on"):
        return _normalize_date
    if name.endswith("_version"):
        return _normalize_version
    return None


def locate_span(content: str, span_text: str) -> tuple[int, int]:
    """Exact offsets of ``span_text`` in ``content``, or ``(-1, -1)``.

    Mechanical traceability: a binding is only real when its text can be pointed at.
    """

    text = str(span_text or "")
    if not text:
        return (-1, -1)
    start = str(content or "").find(text)
    if start < 0:
        return (-1, -1)
    return (start, start + len(text))


def find_trusted_source(
    trusted: Iterable[TrustedSource], claim: Claim
) -> tuple[TrustedSource | None, str]:
    """Return the trusted record a claim points at, or (None, reason)."""

    if not claim.source_url or not claim.source_sha256:
        return (None, "unbound_source_identity")
    digest = str(claim.source_sha256).lower()
    for source in trusted:
        if str(source.url) != str(claim.source_url):
            continue
        if str(source.content_sha256).lower() != digest:
            continue
        if not source.digest_matches():
            return (None, "body_digest_mismatch")
        return (source, "")
    return (None, "source_not_trusted")


def verify_claim(
    trusted: Iterable[TrustedSource], claim: Claim
) -> tuple[bool, str, int, int]:
    """Return (verified, reason, span_start, span_end). Verified only by an exact span."""

    source, reason = find_trusted_source(trusted, claim)
    if source is None:
        return (False, reason, -1, -1)
    start, end = locate_span(source.body, claim.span_text)
    if start < 0:
        return (False, "span_not_found_in_body", -1, -1)
    if claim.span_start >= 0 and claim.span_start != start:
        return (False, "span_offset_mismatch", -1, -1)
    return (True, "", start, end)


def bind_field(
    field: str,
    claims: Iterable[Claim],
    trusted: Iterable[TrustedSource],
) -> dict[str, Any]:
    """Bind one field from proposed claims. Never raises; undecidable abstains."""

    sources = list(trusted)
    normalizer = normalizer_for(field)

    verified: list[tuple[Claim, int, int, str | None]] = []
    rejected: list[dict[str, str]] = []
    for claim in claims:
        if claim.field != field:
            continue
        if not claim.source_url or not claim.source_sha256:
            rejected.append(
                {"source_url": claim.source_url, "reason": "unbound_source_identity"}
            )
            continue
        source, reason = find_trusted_source(sources, claim)
        if source is None:
            rejected.append({"source_url": claim.source_url, "reason": reason})
            continue
        start, end = locate_span(source.body, claim.span_text)
        if start < 0:
            rejected.append(
                {"source_url": claim.source_url, "reason": "span_not_found_in_body"}
            )
            continue
        if claim.span_start >= 0 and claim.span_start != start:
            rejected.append(
                {"source_url": claim.source_url, "reason": "span_offset_mismatch"}
            )
            continue

        derived = normalizer(claim.span_text) if normalizer else None
        if derived is not None and claim.normalized_value.strip():
            if claim.normalized_value.strip() != derived:
                # The caller asserted a value the span does not yield.
                rejected.append(
                    {
                        "source_url": claim.source_url,
                        "reason": "normalized_value_mismatch",
                    }
                )
                continue
        verified.append((claim, start, end, derived))

    if not verified:
        return {
            "field": field,
            "status": INSUFFICIENT if rejected else NOT_EVALUATED,
            "supports": [],
            "conflicts": [],
            "span_bound": [],
            "rejected": rejected,
        }

    def _record(claim: Claim, start: int, end: int, derived: str | None) -> dict[str, Any]:
        row = claim.to_dict()
        # The recorded span and value are where the text is and what it yields, not what
        # the caller claimed.
        row["span_start"], row["span_end"] = start, end
        row["normalized_value"] = derived if derived is not None else ""
        return row

    if any(derived is None for _, _, _, derived in verified):
        # Span verified, value not derivable - honest about what was proven.
        return {
            "field": field,
            "status": SPAN_BOUND,
            "supports": [],
            "conflicts": [],
            "span_bound": [_record(c, s, e, d) for c, s, e, d in verified],
            "rejected": rejected,
        }

    by_value: dict[str, list[tuple[Claim, int, int, str | None]]] = {}
    for row in verified:
        by_value.setdefault(str(row[3]), []).append(row)

    if len(by_value) > 1:
        # Disagreement is reported, never averaged or overwritten.
        return {
            "field": field,
            "status": CONFLICT,
            "supports": [],
            "conflicts": [
                {
                    "normalized_value": value,
                    "claims": [_record(*row) for row in group],
                }
                for value, group in sorted(by_value.items())
            ],
            "span_bound": [],
            "rejected": rejected,
        }

    value = next(iter(by_value))
    return {
        "field": field,
        "status": SUPPORT,
        "supports": [_record(*row) for row in by_value[value]],
        "conflicts": [],
        "span_bound": [],
        "rejected": rejected,
    }


def bind_fields(
    fields: Iterable[str],
    claims: Iterable[Claim],
    trusted: Iterable[TrustedSource],
) -> dict[str, dict[str, Any]]:
    """Bind every requested field. Fields with no verified claim abstain."""

    materialized_claims = list(claims)
    materialized_sources = list(trusted)
    return {
        field: bind_field(field, materialized_claims, materialized_sources)
        for field in fields
    }


def apply_bindings(
    result: dict[str, Any],
    bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return a copy of the result with bindings recorded. Never grants authority.

    ``publication_authority`` is forced back to ``False``: a verified support is evidence,
    not a publication licence.
    """

    updated = dict(result)
    gap_states = {
        field: dict(state)
        for field, state in (result.get("gap_states") or {}).items()
    }
    conflicts: list[dict[str, Any]] = []
    for field, binding in bindings.items():
        state = gap_states.setdefault(
            field,
            {"research_state": "OPEN", "support_status": NOT_EVALUATED, "source_urls": []},
        )
        status = str(binding.get("status") or NOT_EVALUATED)
        state["support_status"] = status
        if status == SUPPORT:
            state["research_state"] = "SUPPORTED"
        elif status == CONFLICT:
            state["research_state"] = "CONFLICT"
            conflicts.append(
                {"field": field, "conflicts": list(binding.get("conflicts") or [])}
            )
        elif status == SPAN_BOUND:
            state["research_state"] = "SPAN_BOUND"
    updated["gap_states"] = gap_states
    updated["conflicts"] = conflicts
    updated["publication_authority"] = False
    return updated
