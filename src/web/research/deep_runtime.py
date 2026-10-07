"""Deep-2 runtime helpers: the execution envelope, the seed, and the absolute Deep clock.

Three durable facts live here, and each exists because a naive version was wrong.

**The execution envelope** fixes the Deep tier's own budget window at first admission. The
Deep tier is a separate tier, so its clock starts when Deep starts - not when the parent turn
was created - but it must never be extended by a retry or a crash.

**The seed** is Standard's already-read bytes. It is not evidence: it enters the candidate pool
as an ordinary candidate and only becomes content when the existing scheduler decides it is
worth using for some Deep claim. Nothing here grants semantic authority.

**The absolute clock** is what makes a crash cost real budget. The runtime's own elapsed time
is process-local, so a Deep run also compares against wall time since `admitted_at`.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from src.news.url_normalizer import canonicalize_url

DEEP_EXECUTION_SCHEMA = "deep-execution-v1"
DEEP_BUDGET_PROFILE = "deep-v1"
DEEP_HARD_SECONDS = 180
DEEP_SOURCE_LIMIT = 6000

SEED_SCHEMA = "deep-seed-v1"
MATERIALIZATION_SCHEMA = "deep-seed-materialization-v1"

SEED_DISCOVERY_METHOD = "deep_seed"
SEED_PROVIDER = "deep_seed"
SEED_FINAL_BACKEND = "deep_seed"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def seed_candidate_identity(canonical_url: str) -> str:
    """Deterministic candidate id for a seed URL. Identity is the canonical URL, not rank."""

    digest = hashlib.sha256(str(canonical_url).encode("utf-8")).hexdigest()[:16]
    return f"deep_seed_{digest}"


def build_execution_envelope(
    *,
    parent_turn_id: str,
    handoff_sha256: str,
    admitted_at: datetime,
) -> dict[str, Any]:
    """The first-admission envelope. ``deadline_at`` is derived, never supplied."""

    return {
        "schema_version": DEEP_EXECUTION_SCHEMA,
        "budget_profile": DEEP_BUDGET_PROFILE,
        "parent_turn_id": str(parent_turn_id),
        "handoff_sha256": str(handoff_sha256),
        "admitted_at": admitted_at.astimezone(timezone.utc).isoformat(),
        "deadline_at": (admitted_at.astimezone(timezone.utc) + timedelta(seconds=DEEP_HARD_SECONDS)).isoformat(),
        "publication_authority": False,
    }


def load_execution_envelope(context: Mapping[str, Any]) -> dict[str, Any] | None:
    """The recorded envelope, or None when this is not a Deep run."""

    deep = context.get("deep")
    if not isinstance(deep, Mapping):
        return None
    envelope = deep.get("execution")
    return dict(envelope) if isinstance(envelope, Mapping) else None


def validate_execution_envelope(envelope: Any) -> tuple[bool, str]:
    """Return (valid, reason). Anything malformed fails closed rather than being repaired."""

    if not isinstance(envelope, Mapping):
        return (False, "execution_envelope_absent")
    if envelope.get("schema_version") != DEEP_EXECUTION_SCHEMA:
        return (False, "execution_schema_mismatch")
    if envelope.get("budget_profile") != DEEP_BUDGET_PROFILE:
        return (False, "execution_budget_profile_mismatch")
    if envelope.get("publication_authority") is not False:
        return (False, "execution_cannot_publish")
    try:
        admitted = datetime.fromisoformat(str(envelope.get("admitted_at")))
        deadline = datetime.fromisoformat(str(envelope.get("deadline_at")))
    except ValueError:
        return (False, "execution_timestamp_invalid")
    if admitted.tzinfo is None or deadline.tzinfo is None:
        return (False, "execution_timestamp_naive")
    if deadline != admitted + timedelta(seconds=DEEP_HARD_SECONDS):
        return (False, "execution_deadline_mismatch")
    return (True, "")


def deep_wall_elapsed_seconds(envelope: Mapping[str, Any], now: datetime) -> float:
    """Seconds of wall time since Deep admission. A crash spends this budget."""

    admitted = datetime.fromisoformat(str(envelope.get("admitted_at")))
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0.0, (now - admitted).total_seconds())


def effective_deep_base_elapsed(
    *,
    durable_elapsed_seconds: float,
    envelope: Mapping[str, Any] | None,
    now: datetime,
) -> float:
    """The Deep tier's elapsed base: the larger of durable and wall time.

    A non-Deep run has no envelope, so this returns the durable value unchanged and the
    ordinary runtime behaviour is untouched.
    """

    if envelope is None:
        return max(0.0, float(durable_elapsed_seconds or 0.0))
    return max(
        max(0.0, float(durable_elapsed_seconds or 0.0)),
        deep_wall_elapsed_seconds(envelope, now),
    )


def load_seed(context: Mapping[str, Any]) -> dict[str, Any] | None:
    """The Deep child's durable seed, or None."""

    deep = context.get("deep")
    if not isinstance(deep, Mapping):
        return None
    seed = deep.get("seed")
    if not isinstance(seed, Mapping) or seed.get("schema_version") != SEED_SCHEMA:
        return None
    return dict(seed)


def seed_sources_by_url(seed: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Map canonical URL -> seed source. URL identity survives candidate merging."""

    sources: dict[str, dict[str, Any]] = {}
    if not isinstance(seed, Mapping):
        return sources
    for source in seed.get("sources") or []:
        if not isinstance(source, Mapping):
            continue
        url = str(source.get("url") or "")
        if not url:
            continue
        sources[canonicalize_url(url)] = dict(source)
    return sources


def verify_seed_sources(seed: Mapping[str, Any] | None) -> tuple[bool, str]:
    """Re-hash every seed body. A contradiction is refused, never silently dropped."""

    if not isinstance(seed, Mapping):
        return (False, "seed_absent")
    if seed.get("schema_version") != SEED_SCHEMA:
        return (False, "seed_schema_mismatch")
    for source in seed.get("sources") or []:
        if not isinstance(source, Mapping):
            return (False, "seed_source_invalid")
        body = source.get("content")
        if not isinstance(body, str) or not body:
            return (False, "seed_body_empty")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if digest != str(source.get("content_sha256") or ""):
            return (False, "seed_body_digest_mismatch")
    return (True, "")


def materialization_provenance(
    *,
    seed_source: Mapping[str, Any],
    materialized_content: str,
    full_body_length: int,
) -> dict[str, Any]:
    """Provenance for a locally materialized source.

    ``source_content_sha256`` describes the full durable body, never the truncated slice.
    """

    return {
        "schema_version": MATERIALIZATION_SCHEMA,
        "kind": SEED_FINAL_BACKEND,
        "origin": "standard_seed",
        "standard_origin": str(seed_source.get("origin") or ""),
        "source_content_sha256": str(seed_source.get("content_sha256") or ""),
        "materialized_chars": len(materialized_content),
        "truncated": len(materialized_content) < int(full_body_length),
    }


def materialized_content(seed_source: Mapping[str, Any], *, source_limit: int) -> str:
    """The Deep-visible slice of a seed body, bounded by the remaining char budget."""

    body = str(seed_source.get("content") or "")
    limit = max(0, min(DEEP_SOURCE_LIMIT, int(source_limit)))
    return body[:limit]


def seed_materialized_candidate_ids(selected_sources: list[dict[str, Any]]) -> frozenset[str]:
    """Candidate ids whose content came from a local seed materialization."""

    return frozenset(
        str(record.get("candidate_id") or "")
        for record in selected_sources
        if isinstance(record, Mapping)
        and str(record.get("final_backend") or "") == SEED_FINAL_BACKEND
        and str(record.get("read_status") or "") == "read"
    )


def content_available_ids(
    completed_read_ids: Any, selected_sources: list[dict[str, Any]]
) -> frozenset[str]:
    """Everything whose bytes are already durable, however they got here."""

    return frozenset(
        {str(item) for item in (completed_read_ids or ())}
        | seed_materialized_candidate_ids(selected_sources)
    )


def seed_char_charge(selected_sources: list[dict[str, Any]]) -> int:
    """Chars already charged for seed materializations, counted once per candidate.

    Source records carry the materialized text under ``read.content``; ``content_chars`` only
    exists on runtime read outcomes, which a local materialization never creates.
    """

    seen: set[str] = set()
    total = 0
    for record in selected_sources:
        if not isinstance(record, Mapping):
            continue
        if str(record.get("final_backend") or "") != SEED_FINAL_BACKEND:
            continue
        if str(record.get("read_status") or "") != "read":
            continue
        candidate_id = str(record.get("candidate_id") or "")
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        read = record.get("read")
        content = read.get("content") if isinstance(read, Mapping) else ""
        total += len(str(content or ""))
    return total


def reference_date_from(created_at: str) -> str:
    """The parent's request date, so a late Deep run cannot change 'today' semantics."""

    try:
        created = datetime.fromisoformat(str(created_at))
    except ValueError:
        return ""
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created.astimezone(timezone.utc).date().isoformat()
