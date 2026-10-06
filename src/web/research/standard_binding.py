"""Standard-3: bind a readable source to a fact, mechanically.

Standard-2 only marks a body as acquired and readable; a requested field stays
``NOT_EVALUATED``. This module is the next step: it turns a candidate claim into a
verifiable binding, or refuses to.

The invariant it exists to protect:

    readable source != factual support != publication authority

So a claim is only accepted when its span can be located in the body by offset - a
keyword merely appearing in the text is not support. Two sources that disagree produce a
conflict; they are never averaged or overwritten. Anything undecidable abstains. Nothing
here grants publication authority.

This is a pure, model-free core: the caller (or a later seam) proposes the claim text and
normalized value, and this decides whether the binding is mechanically sound.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

SUPPORT = "SUPPORT"
CONFLICT = "CONFLICT"
INSUFFICIENT = "INSUFFICIENT"
NOT_EVALUATED = "NOT_EVALUATED"

BINDING_STATES = (SUPPORT, CONFLICT, INSUFFICIENT, NOT_EVALUATED)


@dataclass(frozen=True)
class Claim:
    """A proposed fact binding. The span must be verifiable in the body."""

    field: str
    source_url: str
    source_sha256: str
    span_text: str
    normalized_value: str
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


def verify_claim(content: str, claim: Claim) -> tuple[bool, str]:
    """Return (verified, reason). A claim is verified only by an exact span match."""

    if not claim.normalized_value.strip():
        return (False, "empty_normalized_value")
    if not claim.source_url or not claim.source_sha256:
        return (False, "unbound_source_identity")
    start, end = locate_span(content, claim.span_text)
    if start < 0:
        return (False, "span_not_found_in_body")
    if claim.span_start >= 0 and claim.span_start != start:
        return (False, "span_offset_mismatch")
    return (True, "")


def bind_field(
    field: str,
    claims: Iterable[Claim],
    bodies: Mapping[str, str],
) -> dict[str, Any]:
    """Bind one field from proposed claims. Never raises; undecidable abstains.

    ``bodies`` maps ``source_sha256`` to the body text. A claim whose body is unknown, or
    whose span cannot be located, is dropped with a reason - it can never become support.
    """

    verified: list[Claim] = []
    located: dict[str, tuple[int, int]] = {}
    rejected: list[dict[str, str]] = []
    for claim in claims:
        if claim.field != field:
            continue
        # Identity and value are checked before the body so the reason names the real
        # defect rather than "body missing".
        if not claim.source_url or not claim.source_sha256:
            rejected.append(
                {"source_url": claim.source_url, "reason": "unbound_source_identity"}
            )
            continue
        if not claim.normalized_value.strip():
            rejected.append(
                {"source_url": claim.source_url, "reason": "empty_normalized_value"}
            )
            continue
        content = bodies.get(claim.source_sha256)
        if content is None:
            rejected.append(
                {"source_url": claim.source_url, "reason": "body_not_available"}
            )
            continue
        ok, reason = verify_claim(content, claim)
        if ok:
            verified.append(claim)
            located[claim.source_sha256] = locate_span(content, claim.span_text)
        else:
            rejected.append({"source_url": claim.source_url, "reason": reason})

    if not verified:
        return {
            "field": field,
            "status": INSUFFICIENT if rejected else NOT_EVALUATED,
            "supports": [],
            "conflicts": [],
            "rejected": rejected,
        }

    by_value: dict[str, list[Claim]] = {}
    for claim in verified:
        by_value.setdefault(claim.normalized_value, []).append(claim)

    def _record(claim: Claim) -> dict[str, Any]:
        row = claim.to_dict()
        start, end = located.get(claim.source_sha256, (-1, -1))
        # The recorded span is where the text actually is, not what the caller claimed.
        row["span_start"], row["span_end"] = start, end
        return row

    if len(by_value) > 1:
        # Disagreement is reported, never averaged or overwritten.
        return {
            "field": field,
            "status": CONFLICT,
            "supports": [],
            "conflicts": [
                {
                    "normalized_value": value,
                    "claims": [_record(c) for c in group],
                }
                for value, group in sorted(by_value.items())
            ],
            "rejected": rejected,
        }

    value = next(iter(by_value))
    return {
        "field": field,
        "status": SUPPORT,
        "supports": [_record(c) for c in by_value[value]],
        "conflicts": [],
        "rejected": rejected,
    }


def bind_fields(
    fields: Iterable[str],
    claims: Iterable[Claim],
    bodies: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Bind every requested field. Fields with no verified claim abstain."""

    materialized = list(claims)
    return {
        field: bind_field(field, materialized, bodies) for field in fields
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
        state["support_status"] = str(binding.get("status") or NOT_EVALUATED)
        if binding.get("status") == SUPPORT:
            state["research_state"] = "SUPPORTED"
        elif binding.get("status") == CONFLICT:
            state["research_state"] = "CONFLICT"
            conflicts.append(
                {
                    "field": field,
                    "conflicts": list(binding.get("conflicts") or []),
                }
            )
    updated["gap_states"] = gap_states
    updated["conflicts"] = conflicts
    updated["publication_authority"] = False
    return updated
