"""Deep-1: project a validated Standard journal into the Deep evidence seed.

This is what makes evidence reuse a hard contract rather than a hope. Deep must not re-fetch a
URL Standard already read, so the bytes Standard already has are carried forward.

A source is admitted only when a readable read observation names a completed journal entry
whose body re-hashes to the digest the observation recorded. Anything else is not a seed, and a
mismatch is a hard stop rather than a silent drop.

The seed carries already-read bytes and nothing more. It is not support, not claim evidence,
not a primary source and not an independent cluster: the active runtime still has to assess,
extract and pass the Evidence Gate before any Deep evidence exists.
"""

from __future__ import annotations

import hashlib
from typing import Any

from src.web.research.standard_binding_projection import journal_work_key

DEEP_SEED_SCHEMA = "deep-seed-v1"


class SeedIntegrityError(ValueError):
    """A durable observation and a durable body contradict each other.

    This is not "the source is not eligible" - it is the journal disagreeing with itself, so it
    fails closed instead of dropping the source and continuing.
    """


def _body_of(entry: dict) -> str:
    result = entry.get("result") or {}
    body = result.get("content") or result.get("readme") or ""
    return body if isinstance(body, str) else ""


def project_standard_seed(ledger: dict, *, standard_child_run_id: str) -> dict:
    """Return ``{"sources": [...], "refs": [...]}`` from a validated Standard ledger.

    ``sources`` is the data plane (bytes for the Deep child). ``refs`` is the control plane
    (url, digest, field association, origin) and is the only part allowed into a parent
    snapshot.

    Raises ``SeedIntegrityError`` when a readable observation's recorded digest does not
    describe the journal body it points at.
    """

    observations = ((ledger or {}).get("research") or {}).get("observations") or []
    entries = (ledger or {}).get("entries") or {}

    sources: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    for observation in observations:
        if observation.get("kind") != "read" or not observation.get("readable"):
            continue
        url = str(observation.get("target") or "")
        entry = entries.get(journal_work_key("read", url))
        if not isinstance(entry, dict) or entry.get("state") != "completed":
            continue
        body = _body_of(entry)
        if not body.strip():
            continue
        digest = hashlib.sha256(body.encode()).hexdigest()
        if digest != str(observation.get("content_sha256") or ""):
            # The journal contradicts itself. Fail closed rather than drop and continue.
            raise SeedIntegrityError("Standard seed body digest mismatch")
        fields = list(observation.get("fields") or [])
        origin = str(observation.get("origin") or "")
        sources.append(
            {
                "url": url,
                "content_sha256": digest,
                "content": body,
                "fields": fields,
                "origin": origin,
            }
        )
        refs.append(
            {"url": url, "content_sha256": digest, "fields": fields, "origin": origin}
        )

    return {
        "schema_version": DEEP_SEED_SCHEMA,
        "standard_child_run_id": str(standard_child_run_id),
        "sources": sources,
        "refs": refs,
    }


def seed_refs_match(claimed: list[dict], actual: list[dict]) -> bool:
    """True when a handoff's seed refs describe exactly the durable journal's sources.

    Deep admission blocks on a mismatch rather than dropping the difference and continuing.
    """

    def key(ref: dict) -> tuple[str, str]:
        return (str(ref.get("url") or ""), str(ref.get("content_sha256") or ""))

    return sorted(key(ref) for ref in claimed) == sorted(key(ref) for ref in actual)
