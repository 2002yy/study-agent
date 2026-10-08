"""Server-owned handoff admission snapshot; no network dispatch authority.

The durable StandardExecution adapter owns dispatch and accounting. This
admission object never consumes a budget or calls a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.lookup_terminal import load_standard_handoff
from src.web.research_recovery import LOOKUP_BUDGET, STANDARD_BUDGET


@dataclass(frozen=True)
class StandardHandoffContext:
    parent_turn_id: str
    thread_id: str
    source_run_id: str
    source_run_version: int
    handoff: dict[str, Any]
    deadline: datetime
    admitted_at: datetime

    def _active(self, now: datetime, cancelled: bool) -> None:
        if cancelled:
            raise ValueError("Standard handoff cancelled")
        if now.tzinfo is None or now < self.admitted_at:
            raise ValueError("invalid Standard clock")
        end = min(
            self.deadline,
            self.admitted_at + timedelta(seconds=STANDARD_BUDGET.hard_seconds),
        )
        if now >= end - timedelta(seconds=STANDARD_BUDGET.finalization_reserve):
            raise ValueError("Standard handoff deadline exhausted")


def admit_standard_handoff(
    repository: RuntimeRepository,
    runs: WebLookupRepository,
    *,
    parent_turn_id: str,
    thread_id: str,
    overall_deadline: datetime,
    now: datetime,
) -> StandardHandoffContext:
    """Load from repositories, not from a caller-provided handoff payload."""
    parent = repository.get_chat_turn(parent_turn_id)
    if (
        parent is None
        or parent.thread_id != thread_id
        or parent.status != "completed"
        or parent.cancel_requested_at
    ):
        raise ValueError("Standard parent turn owner/status mismatch")
    terminal = parent.rag_snapshot.get("lookup_terminal") or {}
    owner = terminal.get("owner") or {}
    if (
        terminal.get("state") != "ESCALATE_STANDARD"
        or terminal.get("dispatch_status") != "pending"
        or owner.get("thread_id") != thread_id
        or owner.get("turn_id") != parent_turn_id
    ):
        raise ValueError("no pending server-owned Standard handoff")
    source = runs.get(str(owner.get("run_id") or ""))
    if (
        source is None
        or source.owner_thread_id != thread_id
        or source.cancel_requested_at
        or source.status != "completed"
        or source.query != parent.user_message
    ):
        raise ValueError("Standard source run owner/status mismatch")
    source_owner = source.research_context.get("owner") or {}
    if (
        source_owner.get("turn_id") != parent_turn_id
        or source_owner.get("thread_id") != thread_id
    ):
        raise ValueError("Standard source run parent mismatch")
    handoff = load_standard_handoff(terminal.get("handoff") or {})
    if handoff["query"] != parent.user_message:
        raise ValueError("Standard original query mismatch")
    created = datetime.fromisoformat(parent.created_at)
    if (
        created.tzinfo is None
        or now.tzinfo is None
        or overall_deadline.tzinfo is None
        or now < created
        or overall_deadline
        > created
        + timedelta(seconds=LOOKUP_BUDGET.hard_seconds + STANDARD_BUDGET.hard_seconds)
    ):
        raise ValueError("Standard deadline cannot restart original clock")
    context = StandardHandoffContext(
        parent_turn_id,
        thread_id,
        source.id,
        source.version,
        handoff,
        overall_deadline,
        now,
    )
    context._active(now, False)
    return context
