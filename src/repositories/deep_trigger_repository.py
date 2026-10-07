"""Deep-3T: read-only discovery of durable Deep work items.

There is no queue table. The durable facts already in the database are the queue, and this
repository only re-discovers them: a completed Standard artifact with unresolved gaps and no
Deep terminal (ARM), and a pending Deep terminal (PENDING).

Discovery is deliberately coarse. It does not validate handoff digests, seeds or lineage - that
authority stays with DeepHandoffService and DeepExecutionService. Getting a candidate wrong here
costs one wasted call that those layers reject; duplicating their validation would create a
second authority for the same facts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.web.research.deep_handoff import (
    CONTINUATION_SCHEMA,
    DEEP_TERMINAL_SCHEMA,
    NON_UPGRADE_STOP_REASONS,
)

ARM: Literal["arm", "pending"] = "arm"
PENDING: Literal["arm", "pending"] = "pending"


@dataclass(frozen=True)
class DeepTriggerItem:
    kind: Literal["arm", "pending"]
    parent_turn_id: str
    thread_id: str


def _snapshot(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _terminal(snapshot: Mapping[str, Any], key: str) -> Any:
    return snapshot.get(key)


def _is_pending_deep_terminal(snapshot: Mapping[str, Any]) -> bool:
    terminal = _terminal(snapshot, "deep_terminal")
    if not isinstance(terminal, dict):
        # Absent, or present and not even a terminal: never a work item, never repaired here.
        return False
    return (
        terminal.get("schema_version") == DEEP_TERMINAL_SCHEMA
        and terminal.get("state") == "ESCALATE_DEEP"
        and terminal.get("dispatch_status") == "pending"
    )


def _is_arm_candidate(snapshot: Mapping[str, Any]) -> bool:
    """A completed Standard artifact that still has a gap and has no Deep terminal yet."""

    if _terminal(snapshot, "deep_terminal") is not None:
        return False
    lookup = _terminal(snapshot, "lookup_terminal")
    if not isinstance(lookup, dict):
        return False
    if (
        lookup.get("state") != "ESCALATE_STANDARD"
        or lookup.get("dispatch_status") != "completed"
    ):
        return False
    continuation = _terminal(snapshot, "standard_continuation")
    if not isinstance(continuation, dict):
        return False
    if (
        continuation.get("schema_version") != CONTINUATION_SCHEMA
        or continuation.get("publication_authority") is not False
    ):
        return False
    result = continuation.get("result")
    if not isinstance(result, dict):
        return False
    gaps = result.get("unresolved_gaps")
    if not isinstance(gaps, list) or not gaps:
        return False
    # A known non-upgrade stop is an execution failure, not a depth signal. An unknown stop is
    # still discovered: Deep-1 owns that decision and will block it.
    return str(result.get("stop_reason") or "") not in NON_UPGRADE_STOP_REASONS


class DeepTriggerRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database

    def discover(
        self,
        *,
        arm_limit: int = 8,
        pending_limit: int = 16,
        scan_limit: int = 200,
    ) -> tuple[DeepTriggerItem, ...]:
        """ARM candidates first, then PENDING.

        The order matters: a handoff prepared from an ARM candidate in this same scan becomes a
        pending terminal that the PENDING pass can then pick up, so one wake can carry a Standard
        terminal all the way to Deep execution without waiting for the next interval.
        """

        arm_budget = max(0, int(arm_limit))
        pending_budget = max(0, int(pending_limit))
        if arm_budget == 0 and pending_budget == 0:
            return ()

        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, thread_id, rag_snapshot
                FROM chat_turns
                WHERE status = 'completed'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (max(1, int(scan_limit)),),
            ).fetchall()

        arms: list[DeepTriggerItem] = []
        pending: list[DeepTriggerItem] = []
        for row in rows:
            snapshot = _snapshot(row["rag_snapshot"])
            if len(pending) < pending_budget and _is_pending_deep_terminal(snapshot):
                pending.append(
                    DeepTriggerItem(PENDING, str(row["id"]), str(row["thread_id"]))
                )
                continue
            if len(arms) < arm_budget and _is_arm_candidate(snapshot):
                arms.append(DeepTriggerItem(ARM, str(row["id"]), str(row["thread_id"])))
            if len(arms) >= arm_budget and len(pending) >= pending_budget:
                break
        return tuple(arms + pending)
