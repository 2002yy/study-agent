"""§39 atomic claim routing: route a read artifact to missing atomic claims.

Frozen responsibilities:

1. An atomic factual claim owns its own evidence qualification. A comparison /
   analytical parent claim never has to receive a single-page ``supports`` -
   the comparison belongs to a later synthesis step over two atomic facts.
2. A read page may be consumed by several *relevant* atomic claims, but the
   routing is bounded: only factual claims of the same run that still lack a
   ``supports`` link, at most ``ROUTED_CLAIMS_PER_READ_MAX`` per read artifact
   and ``ROUTED_TARGETS_PER_WAVE_MAX`` per wave. There is no page x all-claims
   cartesian product and no page re-reading.

Inactive by default (``RESEARCH_ATOMIC_ROUTING=on`` for the diagnostic run), so
the production behaviour is unchanged. Every decision is recorded with the
route reasons the observability contract requires.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

ATOMIC_ROUTING_ENV = "RESEARCH_ATOMIC_ROUTING"
ROUTED_CLAIMS_PER_READ_MAX = 2
ROUTED_TARGETS_PER_WAVE_MAX = 4

ROUTE_REASON_MISSING_ATOMIC_CHILD = "missing_atomic_child"
ROUTE_REASON_ORIGIN_CLAIM = "origin_claim"
ROUTE_REASON_ALREADY_SUPPORTED = "already_supported_skip"
ROUTE_REASON_UNRELATED = "unrelated_skip"
ROUTE_REASON_BOUNDED_CAP = "bounded_cap_skip"
ROUTE_REASON_ALREADY_BOUND = "already_bound_skip"


def atomic_routing_enabled() -> bool:
    raw = (os.getenv(ATOMIC_ROUTING_ENV) or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def route_missing_atomic_claims(
    targets: Sequence[Mapping[str, str]],
    *,
    claims: Sequence[Any],
    supported_claim_ids: frozenset[str],
    read_candidate_ids: frozenset[str],
    per_read_max: int = ROUTED_CLAIMS_PER_READ_MAX,
    per_wave_max: int = ROUTED_TARGETS_PER_WAVE_MAX,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Return (extended targets, routing records).

    ``targets`` are the existing ``(candidate, claim)`` extraction bindings;
    routed rows are appended for factual claims that still lack support. The
    input order and the origin rows are never changed.
    """

    extended = [dict(target) for target in targets]
    known_pairs = {
        (str(target.get("candidate_id")), str(target.get("claim_id")))
        for target in extended
    }
    records: list[dict[str, Any]] = []
    total_routed = 0

    for target in extended:
        candidate_id = str(target.get("candidate_id") or "")
        origin_claim_id = str(target.get("claim_id") or "")
        if candidate_id not in read_candidate_ids:
            continue
        record: dict[str, Any] = {
            "read_artifact_id": candidate_id,
            "origin_claim_id": origin_claim_id,
            "candidate_claim_ids": [str(getattr(claim, "id", "")) for claim in claims],
            "routed_claim_ids": [],
            "routes": [],
            "skips": [],
        }
        per_read = 0
        for claim in claims:
            claim_id = str(getattr(claim, "id", "") or "")
            if claim_id == origin_claim_id:
                record["skips"].append(
                    {"claim_id": claim_id, "reason": ROUTE_REASON_ORIGIN_CLAIM}
                )
                continue
            if str(getattr(claim, "kind", "") or "") != "factual":
                record["skips"].append(
                    {"claim_id": claim_id, "reason": ROUTE_REASON_UNRELATED}
                )
                continue
            if claim_id in supported_claim_ids:
                record["skips"].append(
                    {"claim_id": claim_id, "reason": ROUTE_REASON_ALREADY_SUPPORTED}
                )
                continue
            if (candidate_id, claim_id) in known_pairs:
                record["skips"].append(
                    {"claim_id": claim_id, "reason": ROUTE_REASON_ALREADY_BOUND}
                )
                continue
            if per_read >= per_read_max or total_routed >= per_wave_max:
                record["skips"].append(
                    {"claim_id": claim_id, "reason": ROUTE_REASON_BOUNDED_CAP}
                )
                continue
            extended.append({**dict(target), "claim_id": claim_id})
            known_pairs.add((candidate_id, claim_id))
            per_read += 1
            total_routed += 1
            record["routed_claim_ids"].append(claim_id)
            record["routes"].append(
                {
                    "claim_id": claim_id,
                    "reason": ROUTE_REASON_MISSING_ATOMIC_CHILD,
                }
            )
        if record["routed_claim_ids"] or record["skips"]:
            records.append(record)

    return extended, records


__all__ = [
    "ATOMIC_ROUTING_ENV",
    "ROUTE_REASON_ALREADY_BOUND",
    "ROUTE_REASON_ALREADY_SUPPORTED",
    "ROUTE_REASON_BOUNDED_CAP",
    "ROUTE_REASON_MISSING_ATOMIC_CHILD",
    "ROUTE_REASON_ORIGIN_CLAIM",
    "ROUTE_REASON_UNRELATED",
    "ROUTED_CLAIMS_PER_READ_MAX",
    "ROUTED_TARGETS_PER_WAVE_MAX",
    "atomic_routing_enabled",
    "route_missing_atomic_claims",
]
