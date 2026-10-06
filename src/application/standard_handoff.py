"""Server-owned handoff admission and source reuse; no automatic agent dispatch.

This adapter is not wired to an API or research loop yet. Durable operation
leases/cursors must be added before its counters are used across restarts.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.lookup_terminal import load_standard_handoff
from src.web.research_recovery import LOOKUP_BUDGET, STANDARD_BUDGET


@dataclass
class StandardHandoffContext:
    parent_turn_id: str
    thread_id: str
    source_run_id: str
    source_run_version: int
    handoff: dict[str, Any]
    deadline: datetime
    admitted_at: datetime
    new_reads: int = 0
    new_queries: int = 0
    reused_reads: int = 0
    _reads: dict[str, dict] = field(default_factory=dict, repr=False)
    _queries: dict[str, dict] = field(default_factory=dict, repr=False)

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

    def read(
        self, gateway: Any, url: str, *, now: datetime, cancelled: bool = False
    ) -> dict:
        self._active(now, cancelled)
        if url in self._reads:
            self.reused_reads += 1
            return deepcopy(self._reads[url])
        if self.new_reads >= STANDARD_BUDGET.max_reads:
            raise ValueError("Standard read budget exhausted")
        # Charge before dispatch: failures also cost a new read.
        self.new_reads += 1
        result = gateway.read(url, max_chars=STANDARD_BUDGET.max_source_chars)
        if not isinstance(result, dict):
            raise ValueError("invalid Standard read result")
        self._reads[url] = deepcopy(result)
        return deepcopy(result)

    def search(
        self, gateway: Any, query: str, *, now: datetime, cancelled: bool = False
    ) -> dict:
        self._active(now, cancelled)
        if query in self._queries:
            return deepcopy(self._queries[query])
        if self.new_queries >= STANDARD_BUDGET.max_queries:
            raise ValueError("Standard query budget exhausted")
        self.new_queries += 1
        result = gateway.search_exact(query, max_results=8)
        if not isinstance(result, dict):
            raise ValueError("invalid Standard search result")
        self._queries[query] = deepcopy(result)
        return deepcopy(result)


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
    for call in handoff["usable_sources"]:
        context._reads[str(call["arguments"]["url"])] = deepcopy(call["result"])
    for call in handoff["attempted"]:
        if call["name"] == "web_search" and call["result"].get("status") == "ok":
            context._queries[str(call["arguments"]["query"])] = deepcopy(call["result"])
    return context
