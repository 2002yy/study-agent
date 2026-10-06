"""Standard-3: bind a readable source to a fact, mechanically.

Standard-2 only marks a body as acquired and readable; a requested field stays
``NOT_EVALUATED``. This module is the next step: it turns a candidate claim into a
verifiable binding, or refuses to.

The invariant it exists to protect:

    readable source != factual support != publication authority

Three things must be mechanically true before a claim can support a field.

**Identity is bound, not merely non-empty.** A claim names a source; that source must be one
of the trusted Standard-2 records, the body must hash to the recorded digest, and the URL and
digest must match. A fabricated digest or a URL that does not correspond to a trusted record
is rejected - it can never become support.

**The relation is proven, not inferred from a type.** A date in the span does not make the
span a release date. Each field has a relation binder that requires the span to actually
express that field's relation (a release cue for a release date), refuses when the value is
ambiguous (two dates in one span), and otherwise declines. A declined relation yields
``SPAN_BOUND`` - the span is verified, the value is not promoted to ``SUPPORT``.

**The role comes from the source, not the claim.** Provenance is a property of the trusted
record; a caller cannot label a third-party page as primary.

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

# The statuses that leave a field unresolved.
UNRESOLVED_STATES = (CONFLICT, SPAN_BOUND, INSUFFICIENT, NOT_EVALUATED)

_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_SEMVER = re.compile(r"\b(\d+\.\d+(?:\.\d+)?)\b")

# Explicit, enumerated grammar. A release date is proven only by one of these forms - we do
# not add fuzzy synonyms ("published", "available") to raise coverage, because "the sentence
# contains published and a date" is not a mechanical proof of a release date.
_DATE_GRAMMAR = (
    r"\brelease date\b\s*[:\-]?\s*(?P<d>\d{4}-\d{2}-\d{2})\b",
    r"\breleased on\s+(?P<d>\d{4}-\d{2}-\d{2})\b",
    r"\breleased\s+(?P<d>\d{4}-\d{2}-\d{2})\b",
)
_VERSION_GRAMMAR = (
    r"\bversion\s*(?P<v>\d+\.\d+(?:\.\d+)?)",
    r"\brelease[sd]?\s+(?P<v>\d+\.\d+(?:\.\d+)?)\b",
    r"\bv(?P<v>\d+\.\d+(?:\.\d+)?)\b",
)


@dataclass(frozen=True)
class TrustedSource:
    """A Standard-2 source record. The body is trusted only if it hashes to the digest."""

    url: str
    content_sha256: str
    body: str
    source_role: str = ""

    def digest_matches(self) -> bool:
        return hashlib.sha256(str(self.body).encode("utf-8")).hexdigest() == str(
            self.content_sha256
        ).lower()


@dataclass(frozen=True)
class Claim:
    """A proposed fact binding. The span must be verifiable in the body.

    ``span_start`` is cross-checked against the located offset; ``span_end`` is *ignored* -
    the recorded end is re-derived from the located span, so a caller cannot shorten or
    lengthen the evidence it is credited with.
    """

    field: str
    source_url: str
    source_sha256: str
    span_text: str
    normalized_value: str = ""
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
        }


def _to_iso(match: re.Match[str]) -> str | None:
    try:
        return date(
            int(match.group(1)), int(match.group(2)), int(match.group(3))
        ).isoformat()
    except ValueError:
        return None


def _bind_date_relation(span: str) -> str | None:
    """A release date, only when the span matches the grammar and the value is unique."""

    text = str(span)
    dates = list(_ISO_DATE.finditer(text))
    if len(dates) != 1:
        # Two dates in one span is ambiguous; refuse rather than pick the first.
        return None
    if not any(re.search(pattern, text, re.I) for pattern in _DATE_GRAMMAR):
        return None
    return _to_iso(dates[0])


def _bind_version_relation(span: str) -> str | None:
    text = str(span)
    matches = list(_SEMVER.finditer(text))
    if len(matches) != 1:
        return None
    if not any(re.search(pattern, text, re.I) for pattern in _VERSION_GRAMMAR):
        return None
    return matches[0].group(1)


# Field-level relation binders. A field with no binder yields SPAN_BOUND, never SUPPORT -
# we will not promote "this text exists" to "this text supports this field".
_RELATIONS: dict[str, Callable[[str], str | None]] = {
    "release_date": _bind_date_relation,
    "date": _bind_date_relation,
    "published": _bind_date_relation,
    "version": _bind_version_relation,
    "release_version": _bind_version_relation,
}


def relation_binder_for(field: str) -> Callable[[str], str | None] | None:
    """The field's relation binder, or None when the relation cannot be mechanically proven."""

    name = str(field or "").lower()
    if name in _RELATIONS:
        return _RELATIONS[name]
    if name.endswith("_date") or name.endswith("_on"):
        return _bind_date_relation
    if name.endswith("_version"):
        return _bind_version_relation
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
    relation = relation_binder_for(field)

    # claim, trusted source, span start, span end, derived value (None = not proven)
    verified: list[tuple[Claim, TrustedSource, int, int, str | None]] = []
    rejected: list[dict[str, str]] = []
    for claim in claims:
        if claim.field != field:
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

        derived = relation(claim.span_text) if relation else None
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
        verified.append((claim, source, start, end, derived))

    if not verified:
        return {
            "field": field,
            "status": INSUFFICIENT if rejected else NOT_EVALUATED,
            "supports": [],
            "conflicts": [],
            "span_bound": [],
            "rejected": rejected,
        }

    def _record(
        claim: Claim, source: TrustedSource, start: int, end: int, derived: str | None
    ) -> dict[str, Any]:
        row = claim.to_dict()
        # The recorded span and value are where the text is and what it yields; the role is
        # the source's, not the claim's.
        row["span_start"], row["span_end"] = start, end
        row["normalized_value"] = derived if derived is not None else ""
        row["source_role"] = source.source_role
        return row

    if any(derived is None for *_, derived in verified):
        # Span verified, relation not proven - honest about what was shown.
        return {
            "field": field,
            "status": SPAN_BOUND,
            "supports": [],
            "conflicts": [],
            "span_bound": [_record(*row) for row in verified],
            "rejected": rejected,
        }

    by_value: dict[str, list[tuple[Claim, TrustedSource, int, int, str | None]]] = {}
    for row in verified:
        by_value.setdefault(str(row[4]), []).append(row)

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

    A binding for a field the run never requested is ignored - bindings cannot invent gaps.
    ``unresolved_gaps`` is recomputed from the final support status, so a field that was
    supported and is later re-bound as a conflict or a bound span returns to unresolved.
    ``publication_authority`` is forced back to ``False``: a verified support is evidence, not
    a publication licence.
    """

    updated = dict(result)
    gap_states = {
        field: dict(state)
        for field, state in (result.get("gap_states") or {}).items()
    }
    conflicts: list[dict[str, Any]] = []

    for field, binding in bindings.items():
        if field not in gap_states:
            # Not a requested field: never added to the result.
            continue
        status = str(binding.get("status") or NOT_EVALUATED)
        gap_states[field]["support_status"] = status
        if status == SUPPORT:
            gap_states[field]["research_state"] = "SUPPORTED"
        elif status == CONFLICT:
            gap_states[field]["research_state"] = "CONFLICT"
            conflicts.append(
                {"field": field, "conflicts": list(binding.get("conflicts") or [])}
            )
        elif status == SPAN_BOUND:
            gap_states[field]["research_state"] = "SPAN_BOUND"

    # Recomputed from the final state, not incrementally edited.
    unresolved = [
        field
        for field, state in gap_states.items()
        if str(state.get("support_status")) != SUPPORT
    ]
    for field in result.get("unresolved_gaps") or []:
        if field not in gap_states and field not in unresolved:
            unresolved.append(field)

    updated["gap_states"] = gap_states
    updated["conflicts"] = conflicts
    updated["unresolved_gaps"] = unresolved
    updated["publication_authority"] = False
    return updated
