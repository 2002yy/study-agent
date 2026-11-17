"""Durable active-steering envelope and pure research-graph projection.

Steering remains metadata inside the owning ``WebLookupRun``.  This module
owns the bounded append/merge envelope and the deterministic projection of
pending entries into claims/gaps.  Persistence and checkpoint ordering stay
with the active runtime executor.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from src.web.research.contracts import (
    EvidenceGap,
    EvidenceRequirement,
    ResearchClaim,
    ResearchState,
    ResearchTraceEvent,
    build_research_state,
)

ACTIVE_RESEARCH_STEERING_KEY = "claim_engine_steering"
ACTIVE_RESEARCH_STEERING_STATUSES = frozenset({"pending", "applied", "late"})


def is_active_claim_engine_context(context: Mapping[str, Any]) -> bool:
    claim_engine = context.get("claim_engine")
    return isinstance(claim_engine, Mapping) and claim_engine.get("mode") == "active"


def active_steering_entries(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return copied, server-shaped entries without accepting anonymous data."""

    raw = context.get(ACTIVE_RESEARCH_STEERING_KEY)
    if not isinstance(raw, list):
        return []
    return [
        dict(item)
        for item in raw
        if isinstance(item, Mapping)
        and isinstance(item.get("id"), str)
        and bool(item["id"])
        and item.get("status") in ACTIVE_RESEARCH_STEERING_STATUSES
    ]


def _pending_active_steering_ids(context: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(item["id"])
        for item in active_steering_entries(context)
        if item.get("status") == "pending"
    )


def _unapplied_steering_blocks_completion(context: Mapping[str, Any]) -> bool:
    """Durable signal: a steering marked late against the exhausted hard or
    wave budget invalidates completion computed from the pre-steering graph.

    Recomputed from the merged durable context on every settlement (including
    a crash/resume), never taken from this invocation's mark return value.
    User-cancelled late entries stay owned by the cancellation lifecycle and
    do not participate in StopGate truth.
    """

    return any(
        item.get("status") == "late"
        and item.get("late_reason") in {"hard_budget_exhausted", "wave_limit_reached"}
        for item in active_steering_entries(context)
    )


def _steering_ids_for_claim(
    context: Mapping[str, Any],
    claim_id: str,
) -> tuple[str, ...]:
    return tuple(
        str(item["id"])
        for item in active_steering_entries(context)
        if item.get("status") == "applied" and item.get("claim_id") == claim_id
    )


def _steering_graph_ids(entry_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(entry_id.encode("utf-8")).hexdigest()[:24]
    return f"claim_steering_{digest}", f"gap_steering_{digest}"


def _apply_pending_active_steering(
    state: ResearchState,
    context: Mapping[str, Any],
    *,
    run_id: str,
    wave_index: int,
    applied_at: str,
    known_evidence_ids: tuple[str, ...],
) -> tuple[ResearchState, dict[str, Any], tuple[str, ...]]:
    """Map pending metadata into one user claim and critical gap per entry."""

    entries = active_steering_entries(context)
    pending = [item for item in entries if item.get("status") == "pending"]
    if not pending:
        return state, dict(context), ()
    if not state.questions:
        raise ValueError("active steering requires a planned research question")

    question_id = state.questions[0].id
    claims = list(state.claims)
    gaps = list(state.gaps)
    trace = list(state.trace)
    claim_ids = {item.id for item in claims}
    gap_ids = {item.id for item in gaps}
    next_sequence = max((item.sequence for item in trace), default=0) + 1
    applied_ids: list[str] = []

    for entry in entries:
        if entry.get("status") != "pending":
            continue
        entry_id = str(entry["id"])
        claim_id, gap_id = _steering_graph_ids(entry_id)
        if claim_id not in claim_ids:
            claims.append(
                ResearchClaim(
                    id=claim_id,
                    question_id=question_id,
                    text=str(entry.get("content") or "")[:2000],
                    kind="research_question",
                    priority="critical",
                    state="unresolved",
                    evidence_requirement=EvidenceRequirement(
                        min_independent_sources=1,
                        requires_successful_read=True,
                    ),
                    created_by="user",
                    created_reason=f"active_steering:{entry_id}",
                )
            )
            claim_ids.add(claim_id)
            trace.append(
                ResearchTraceEvent(
                    sequence=next_sequence,
                    timestamp=applied_at,
                    run_id=run_id,
                    event_type="claim_created",
                    reason="active_steering_applied",
                    claim_id=claim_id,
                )
            )
            next_sequence += 1
        if gap_id not in gap_ids:
            gaps.append(
                EvidenceGap(
                    id=gap_id,
                    claim_id=claim_id,
                    gap_type="user_steering",
                    priority="critical",
                    state="open",
                )
            )
            gap_ids.add(gap_id)
            trace.append(
                ResearchTraceEvent(
                    sequence=next_sequence,
                    timestamp=applied_at,
                    run_id=run_id,
                    event_type="gap_created",
                    reason="active_steering_applied",
                    claim_id=claim_id,
                    gap_id=gap_id,
                )
            )
            next_sequence += 1
        entry.update(
            {
                "status": "applied",
                "applied_wave": wave_index,
                "applied_at": applied_at,
                "claim_id": claim_id,
                "gap_id": gap_id,
                "late_reason": "",
            }
        )
        applied_ids.append(entry_id)

    updated_state = build_research_state(
        mode=state.mode,
        questions=state.questions,
        claims=claims,
        evidence=state.evidence,
        evidence_links=state.evidence_links,
        source_clusters=state.source_clusters,
        gaps=gaps,
        conflict_gaps=state.conflict_gaps,
        budget=state.budget,
        trace=trace,
        brief=None,
        reference_date=state.reference_date,
        known_evidence_ids=known_evidence_ids,
    )
    updated_context = dict(context)
    updated_context[ACTIVE_RESEARCH_STEERING_KEY] = entries
    return updated_state, updated_context, tuple(applied_ids)


def _mark_pending_active_steering_late(
    context: Mapping[str, Any],
    *,
    reason: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    entries = active_steering_entries(context)
    late_ids: list[str] = []
    for entry in entries:
        if entry.get("status") != "pending":
            continue
        entry.update(
            {
                "status": "late",
                "applied_wave": None,
                "applied_at": None,
                "claim_id": "",
                "gap_id": "",
                "late_reason": reason,
            }
        )
        late_ids.append(str(entry["id"]))
    updated = dict(context)
    if entries:
        updated[ACTIVE_RESEARCH_STEERING_KEY] = entries
    return updated, tuple(late_ids)


def append_active_steering(
    context: Mapping[str, Any],
    *,
    entry_id: str,
    content: str,
    received_at: str,
) -> dict[str, Any]:
    """Append one pending entry with a server-owned identity."""

    updated = dict(context)
    entries = active_steering_entries(context)
    if any(item["id"] == entry_id for item in entries):
        return updated
    entries.append(
        {
            "id": entry_id,
            "content": content,
            "received_at": received_at,
            "status": "pending",
            "applied_wave": None,
            "applied_at": None,
            "claim_id": "",
            "gap_id": "",
            "late_reason": "",
        }
    )
    updated[ACTIVE_RESEARCH_STEERING_KEY] = entries
    return updated


def merge_active_steering_context(
    incoming: Mapping[str, Any],
    durable: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge concurrent append-only entries by server-owned ID.

    The executor's incoming copy wins for an existing ID because it may have
    advanced that entry from pending to applied/late.  Durable-only IDs were
    received concurrently and must survive the checkpoint.
    """

    updated = dict(incoming)
    incoming_entries = active_steering_entries(incoming)
    durable_entries = active_steering_entries(durable)
    if not incoming_entries and not durable_entries:
        return updated

    merged: dict[str, dict[str, Any]] = {
        str(item["id"]): item for item in durable_entries
    }
    for item in incoming_entries:
        merged[str(item["id"])] = item
    updated[ACTIVE_RESEARCH_STEERING_KEY] = sorted(
        merged.values(),
        key=lambda item: (str(item.get("received_at") or ""), str(item["id"])),
    )
    return updated


def merge_deep_steering_context(
    incoming: Mapping[str, Any],
    durable: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge the legacy deep-research ``deep["steering"]`` list by identity.

    A concurrent ``append_steering`` writes into ``deep["steering"]`` while the
    Deep executor checkpoints a stale snapshot; without this merge the new
    condition is silently lost.  Entries are identified by
    ``(received_at, content)`` because the legacy envelope carries no id.
    Incoming wins for an existing key (it may have advanced
    ``incorporated_in_round``); durable-only entries survive.
    """

    updated = dict(incoming)
    incoming_deep = incoming.get("deep")
    durable_deep = durable.get("deep")
    if not isinstance(incoming_deep, dict) or not isinstance(durable_deep, dict):
        return updated
    durable_entries = [
        item for item in (durable_deep.get("steering") or []) if isinstance(item, dict)
    ]
    if not durable_entries:
        return updated
    incoming_entries = [
        item for item in (incoming_deep.get("steering") or []) if isinstance(item, dict)
    ]

    def key(item: dict[str, Any]) -> tuple[str, str]:
        return (str(item.get("received_at") or ""), str(item.get("content") or ""))

    merged: dict[tuple[str, str], dict[str, Any]] = {key(item): item for item in durable_entries}
    for item in incoming_entries:
        merged[key(item)] = item
    deep = dict(incoming_deep)
    deep["steering"] = sorted(
        merged.values(),
        key=lambda item: (str(item.get("received_at") or ""), str(item.get("content") or "")),
    )
    updated["deep"] = deep
    return updated


def merge_queued_followups(incoming: Mapping[str, Any], durable: Mapping[str, Any]) -> dict[str, Any]:
    """A concurrent queued message or completed delivery cannot be overwritten."""
    updated = dict(incoming)
    merged = {str(item["id"]): dict(item) for item in incoming.get("conversation_queue", []) if isinstance(item, dict) and item.get("id")}
    for item in durable.get("conversation_queue", []):
        if isinstance(item, dict) and item.get("id"):
            key = str(item["id"])
            if key not in merged or item.get("status") == "completed":
                merged[key] = dict(item)
    if merged:
        updated["conversation_queue"] = list(merged.values())
    return updated
