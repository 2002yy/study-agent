"""Deep-1: decide and describe a Standard to Deep handoff. Pure, no DB and no network.

Deep is not "Standard with more queries". It is the next tier, entered only when Standard
finished honestly and still has an unresolved evidence gap.

The escalation rule is deliberately narrow. A Standard result that failed to execute - a
cancelled run, an invalid or failed planner, an unknown dispatch - is *not* a deeper research
opportunity, and Deep must never launder an execution failure into a new research chance. Only
a normal research terminal with a non-empty gap list qualifies.

This module decides and describes. It does not create anything, and it never grants
publication authority.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

DEEP_HANDOFF_SCHEMA = "standard-deep-handoff-v1"
DEEP_TERMINAL_SCHEMA = "standard-deep-terminal-v1"
CONTINUATION_SCHEMA = "standard-auto-continuation-v1"

DEEP_REASON = "unresolved_after_standard"
DEEP_BUDGET_PROFILE = "deep-v1"

# Standard finished its own research and still has a gap: this is what Deep exists for.
UPGRADE_STOP_REASONS = frozenset(
    {
        "ready_for_binding",
        "plan_exhausted",
        "budget_exhausted",
        "deadline",
        "conflict_requires_binding",
    }
)

# Standard did not finish its research. These are execution failures, not depth signals.
NON_UPGRADE_STOP_REASONS = frozenset(
    {"cancelled", "planner_invalid", "planner_failed", "result_unknown"}
)

# Outcome vocabulary. There is no running/researching/completed: Deep-1 executes no research.
NOT_REQUESTED = "not_requested"
PENDING = "pending"
BLOCKED = "blocked"


def payload_digest(payload: dict) -> str:
    """Canonical digest over everything except the digest field itself."""

    snapshot = deepcopy(payload)
    snapshot.pop("payload_sha256", None)
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def decide_deep_handoff(standard_result: dict, *, stop_reason: str) -> str:
    """Return not_requested, pending or blocked for a completed Standard result."""

    reason = str(stop_reason or "")
    if reason in NON_UPGRADE_STOP_REASONS:
        # An execution failure is not a depth signal.
        return NOT_REQUESTED
    if reason not in UPGRADE_STOP_REASONS:
        # An unrecognised terminal is an integrity problem, not a research opportunity.
        return BLOCKED
    gaps = standard_result.get("unresolved_gaps") or []
    if not gaps:
        # Standard resolved everything it was asked; there is nothing deeper to do.
        return NOT_REQUESTED
    return PENDING


def build_deep_handoff(
    *,
    parent_turn_id: str,
    query: str,
    standard_child_run_id: str,
    standard_source_run_id: str,
    standard_handoff_sha256: str,
    standard_result: dict,
    seed_source_refs: list[dict],
) -> dict:
    """Assemble the durable handoff. Control plane only - never any raw body."""

    payload = {
        "schema_version": DEEP_HANDOFF_SCHEMA,
        "reason": DEEP_REASON,
        "query": str(query),
        "parent_turn_id": str(parent_turn_id),
        "standard_child_run_id": str(standard_child_run_id),
        "standard_source_run_id": str(standard_source_run_id),
        "standard_handoff_sha256": str(standard_handoff_sha256),
        "standard_result_sha256": hashlib.sha256(
            json.dumps(standard_result, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        "unresolved_fields": list(standard_result.get("unresolved_gaps") or []),
        "gap_states": deepcopy(standard_result.get("gap_states") or {}),
        "conflicts": deepcopy(standard_result.get("conflicts") or []),
        "known_assertion_refs": deepcopy(standard_result.get("known_assertion_refs") or []),
        # References only: url, digest, field association, origin. No content.
        "seed_source_refs": [dict(ref) for ref in seed_source_refs],
        "budget_profile": DEEP_BUDGET_PROFILE,
        "publication_authority": False,
    }
    payload["payload_sha256"] = payload_digest(payload)
    return payload


def load_deep_handoff(payload: dict) -> dict:
    """Validate an exact snapshot before reuse; this spends no budget."""

    snapshot = deepcopy(payload)
    digest = snapshot.pop("payload_sha256", None)
    if snapshot.get("schema_version") != DEEP_HANDOFF_SCHEMA or payload_digest(
        {**snapshot, "payload_sha256": digest}
    ) != digest:
        raise ValueError("deep handoff schema or digest mismatch")
    if snapshot.get("publication_authority") is not False:
        raise ValueError("deep handoff cannot grant publication authority")
    if snapshot.get("reason") != DEEP_REASON:
        raise ValueError("deep handoff reason mismatch")
    return snapshot


def deep_terminal(
    *,
    parent_turn_id: str,
    thread_id: str,
    source_run_id: str,
    child_run_id: str,
    handoff: dict,
    dispatch_status: str,
    reason: str = "",
) -> dict:
    """The independent Deep namespace. Standard's own artifact is never reopened."""

    terminal = {
        "schema_version": DEEP_TERMINAL_SCHEMA,
        "state": "ESCALATE_DEEP",
        "reason": reason or DEEP_REASON,
        "dispatch_status": str(dispatch_status),
        "owner": {
            "thread_id": str(thread_id),
            "turn_id": str(parent_turn_id),
            "run_id": str(source_run_id),
        },
        "handoff": deepcopy(handoff) if handoff else {},
    }
    if child_run_id:
        terminal["child_run_id"] = str(child_run_id)
    return terminal


def deep_child_identity(parent_turn_id: str, standard_child_run_id: str) -> tuple[str, str]:
    """Deterministic child id and request id: retries and restarts find the same child."""

    request_id = f"deep-handoff:{parent_turn_id}:{standard_child_run_id}"
    digest = hashlib.sha256(request_id.encode()).hexdigest()[:24]
    return f"deep-{digest}", request_id
