"""Attach immutable Git commit identity to nested source evidence payloads."""

from __future__ import annotations

from typing import Any


def _looks_like_evidence(value: dict[str, Any]) -> bool:
    return bool(
        value.get("path")
        and value.get("tree_sha")
        and "start_line" in value
        and "end_line" in value
    )


def pin_evidence_refs(value: Any, snapshot: dict[str, Any]) -> Any:
    """Recursively enrich JSON-safe evidence without changing legacy fields."""

    commit_sha = str(snapshot.get("commit_sha") or "")
    requested_ref = str(snapshot.get("requested_ref") or snapshot.get("ref") or "")
    if isinstance(value, list):
        return [pin_evidence_refs(item, snapshot) for item in value]
    if isinstance(value, tuple):
        return [pin_evidence_refs(item, snapshot) for item in value]
    if not isinstance(value, dict):
        return value
    payload = {
        str(key): pin_evidence_refs(item, snapshot)
        for key, item in value.items()
    }
    if _looks_like_evidence(payload):
        payload.setdefault("requested_ref", requested_ref)
        payload.setdefault("commit_sha", commit_sha)
    return payload
