"""Deep-3T: read-only discovery of durable Deep work items.

There is no queue table. The durable facts already in the database are the queue, and this
repository only re-discovers them: a completed Standard artifact with unresolved gaps and no
Deep terminal (ARM), and a pending Deep terminal (PENDING).

Discovery is deliberately coarse. It does not validate handoff digests, seeds or lineage - that
authority stays with DeepHandoffService and DeepExecutionService. Getting a candidate wrong here
costs one wasted call that those layers reject; duplicating their validation would create a
second authority for the same facts.

Two things this module is careful about.

**The whole durable queue must stay reachable.** Scanning a fixed window of the newest turns
would make older work permanently invisible - a pending Deep terminal behind a few hundred newer
turns would never be discovered by a startup scan, a wake or the periodic rescan. So discovery
pages through completed turns until the requested budgets are filled or the rows run out. The
page cursor lives only on this call stack: it is not persisted and never becomes scheduler
state.

**Absent and malformed are different.** A ``deep_terminal`` key that is present but null or
otherwise malformed means a terminal was recorded and is unusable - not that no terminal exists.
Treating it as absent would offer it as ARM work forever, because the layers below refuse to
overwrite a recorded terminal.
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

DEEP_TERMINAL_KEY = "deep_terminal"
PAGE_SIZE = 200


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


def _is_pending_deep_terminal(snapshot: Mapping[str, Any]) -> bool:
    terminal = snapshot.get(DEEP_TERMINAL_KEY)
    if not isinstance(terminal, dict):
        # Absent, null, or not even a terminal: never a work item, and never repaired here.
        return False
    return (
        terminal.get("schema_version") == DEEP_TERMINAL_SCHEMA
        and terminal.get("state") == "ESCALATE_DEEP"
        and terminal.get("dispatch_status") == "pending"
    )


def _is_arm_candidate(snapshot: Mapping[str, Any]) -> bool:
    """A completed Standard artifact that still has a gap and has no Deep terminal recorded.

    Existence, not truthiness: a recorded-but-unusable terminal is not the same as no terminal.
    """

    if DEEP_TERMINAL_KEY in snapshot:
        return False
    lookup = snapshot.get("lookup_terminal")
    if not isinstance(lookup, dict):
        return False
    if (
        lookup.get("state") != "ESCALATE_STANDARD"
        or lookup.get("dispatch_status") != "completed"
    ):
        return False
    continuation = snapshot.get("standard_continuation")
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

    def _page(self, cursor: tuple[str, str] | None, size: int) -> list[Any]:
        with self.database.connect() as connection:
            if cursor is None:
                return connection.execute(
                    """
                    SELECT id, thread_id, rag_snapshot, updated_at
                    FROM chat_turns
                    WHERE status = 'completed'
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (size,),
                ).fetchall()
            updated_at, row_id = cursor
            return connection.execute(
                """
                SELECT id, thread_id, rag_snapshot, updated_at
                FROM chat_turns
                WHERE status = 'completed'
                  AND (updated_at < ? OR (updated_at = ? AND id < ?))
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (updated_at, updated_at, row_id, size),
            ).fetchall()

    def discover(
        self,
        *,
        arm_limit: int = 8,
        pending_limit: int = 16,
        page_size: int = PAGE_SIZE,
    ) -> tuple[DeepTriggerItem, ...]:
        """ARM candidates first, then PENDING, scanning the whole completed queue.

        The order matters: a handoff prepared from an ARM candidate in this same scan becomes a
        pending terminal that the PENDING pass can then pick up, so one wake can carry a Standard
        terminal all the way to Deep execution without waiting for the next interval.
        """

        arm_budget = max(0, int(arm_limit))
        pending_budget = max(0, int(pending_limit))
        if arm_budget == 0 and pending_budget == 0:
            return ()

        size = max(1, int(page_size))
        arms: list[DeepTriggerItem] = []
        pending: list[DeepTriggerItem] = []
        cursor: tuple[str, str] | None = None
        while True:
            rows = self._page(cursor, size)
            if not rows:
                break
            for row in rows:
                snapshot = _snapshot(row["rag_snapshot"])
                if len(pending) < pending_budget and _is_pending_deep_terminal(snapshot):
                    pending.append(
                        DeepTriggerItem(PENDING, str(row["id"]), str(row["thread_id"]))
                    )
                elif len(arms) < arm_budget and _is_arm_candidate(snapshot):
                    arms.append(
                        DeepTriggerItem(ARM, str(row["id"]), str(row["thread_id"]))
                    )
                if len(arms) >= arm_budget and len(pending) >= pending_budget:
                    return tuple(arms + pending)
            if len(rows) < size:
                break
            cursor = (str(rows[-1]["updated_at"]), str(rows[-1]["id"]))
        return tuple(arms + pending)
