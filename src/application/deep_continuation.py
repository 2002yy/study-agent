"""Deep-3: continue a pending Deep handoff and project the child terminal to the parent.

This is the layer that decides whether a Deep child needs to run, and then records what it
reached. It runs in the background trigger, never on the chat response path.

The rules that matter. A child that already reached a runtime terminal is never executed again -
it is finalized, which is the whole point of the child-terminal crash window. A research
terminal is not an integrity failure: a failed or cancelled child maps to a completed parent,
because Deep honestly reached the end of its work. Only a deterministic integrity failure
becomes blocked, and an unknown exception propagates so the trigger can rediscover the item
rather than freezing a parent permanently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from src.application.deep_execution import DeepExecutionService
from src.repositories.deep_continuation_repository import (
    REASON_CHILD_MISSING,
    REASON_HANDOFF_INTEGRITY,
    REASON_LINEAGE_MISMATCH,
    REASON_PARENT_UNAVAILABLE,
    REASON_TERMINAL_INTEGRITY,
    TERMINAL_CHILD_STATUSES,
    DeepContinuationRepository,
    DeepFinalizationError,
    validate_recorded_terminal,
)
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.deep_handoff import DEEP_TERMINAL_SCHEMA, load_deep_handoff


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DeepContinuationOutcome:
    status: Literal["not_requested", "deferred", "completed", "blocked"]
    parent_turn_id: str
    child_run_id: str
    reason: str
    result: dict[str, Any] | None = None


class DeepContinuationService:
    def __init__(
        self,
        repository: RuntimeRepository,
        runs: WebLookupRepository,
        execution: DeepExecutionService,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self.repository = repository
        self.runs = runs
        self.execution = execution
        self.clock = clock
        self.terminal = DeepContinuationRepository(repository.database)

    def continue_pending(
        self, *, parent_turn_id: str, thread_id: str
    ) -> DeepContinuationOutcome:
        # The parent and its thread are checked first: a caller who does not own the turn must
        # not be told anything about its terminal.
        parent = self.repository.get_chat_turn(parent_turn_id)
        if parent is None or parent.thread_id != thread_id:
            return self._block(parent_turn_id, thread_id, REASON_PARENT_UNAVAILABLE)

        read = self.terminal.read_terminal(parent_turn_id, thread_id)
        if not read.present:
            return self._outcome("not_requested", parent_turn_id, "", "no_deep_terminal")
        terminal = read.terminal
        if not isinstance(terminal, dict):
            # Recorded but not a terminal: fail closed, and never rewrite what is there.
            return self._outcome("blocked", parent_turn_id, "", REASON_TERMINAL_INTEGRITY)
        if (
            terminal.get("schema_version") != DEEP_TERMINAL_SCHEMA
            or terminal.get("state") != "ESCALATE_DEEP"
        ):
            return self._outcome("blocked", parent_turn_id, "", REASON_TERMINAL_INTEGRITY)

        status = str(terminal.get("dispatch_status") or "")
        if status in {"completed", "blocked"}:
            # First terminal wins, but a recorded terminal is not thereby trusted: a completed
            # terminal without a valid result, or with publication authority, is not settled.
            valid, why = validate_recorded_terminal(terminal)
            if not valid:
                return self._outcome("blocked", parent_turn_id, "", why)
            return DeepContinuationOutcome(
                status="completed" if status == "completed" else "blocked",
                parent_turn_id=parent_turn_id,
                child_run_id=str(terminal.get("child_run_id") or ""),
                reason=str(terminal.get("reason") or ""),
                result=terminal.get("result") if isinstance(terminal.get("result"), dict) else None,
            )
        if status != "pending":
            return self._block(parent_turn_id, thread_id, REASON_TERMINAL_INTEGRITY)

        if parent.status != "completed" or parent.cancel_requested_at:
            return self._block(parent_turn_id, thread_id, REASON_PARENT_UNAVAILABLE)

        owner = terminal.get("owner") or {}
        if owner.get("thread_id") != thread_id or owner.get("turn_id") != parent_turn_id:
            return self._block(parent_turn_id, thread_id, REASON_TERMINAL_INTEGRITY)
        raw_handoff = terminal.get("handoff")
        if not isinstance(raw_handoff, dict) or not str(
            raw_handoff.get("payload_sha256") or ""
        ):
            return self._block(parent_turn_id, thread_id, REASON_HANDOFF_INTEGRITY)
        try:
            handoff = load_deep_handoff(raw_handoff)
        except ValueError:
            return self._block(parent_turn_id, thread_id, REASON_HANDOFF_INTEGRITY)
        if str(handoff.get("parent_turn_id") or "") != parent_turn_id:
            return self._block(parent_turn_id, thread_id, REASON_HANDOFF_INTEGRITY)

        child_run_id = str(terminal.get("child_run_id") or "")
        if not child_run_id:
            return self._block(parent_turn_id, thread_id, REASON_CHILD_MISSING)
        child = self.runs.get(child_run_id)
        if child is None:
            return self._block(parent_turn_id, thread_id, REASON_CHILD_MISSING)
        if (
            child.owner_thread_id != thread_id
            or str(child.parent_run_id or "") != str(handoff.get("standard_child_run_id") or "")
            or child.query != str(handoff.get("query") or "")
            or child.query != parent.user_message
        ):
            return self._block(parent_turn_id, thread_id, REASON_LINEAGE_MISMATCH)

        if child.status in TERMINAL_CHILD_STATUSES:
            # The most important crash-recovery gate: a terminal child is never re-executed.
            return self._finalize(parent_turn_id, thread_id, child_run_id)

        execution = self.execution.execute(
            parent_turn_id=parent_turn_id, thread_id=thread_id
        )
        if execution.status == "deferred":
            # A live owner holds the child. The parent stays pending; nothing is written.
            return self._outcome("deferred", parent_turn_id, child_run_id, execution.reason)
        if execution.status == "blocked":
            return self._block(parent_turn_id, thread_id, execution.reason)

        # Completed (or an unexpected status): trust only a re-read of durable truth.
        refreshed = self.runs.get(child_run_id)
        if refreshed is None:
            return self._block(parent_turn_id, thread_id, REASON_CHILD_MISSING)
        if refreshed.status not in TERMINAL_CHILD_STATUSES:
            return self._outcome("deferred", parent_turn_id, child_run_id, "in_progress")
        return self._finalize(parent_turn_id, thread_id, child_run_id)

    def _finalize(
        self, parent_turn_id: str, thread_id: str, child_run_id: str
    ) -> DeepContinuationOutcome:
        try:
            terminal = self.terminal.finalize(
                parent_turn_id=parent_turn_id,
                thread_id=thread_id,
                expected_child_run_id=child_run_id,
            )
        except DeepFinalizationError as exc:
            return self._block(parent_turn_id, thread_id, exc.reason)
        result = terminal.get("result")
        return DeepContinuationOutcome(
            status="completed",
            parent_turn_id=parent_turn_id,
            child_run_id=child_run_id,
            reason=str(terminal.get("reason") or ""),
            result=result if isinstance(result, dict) else None,
        )

    def _block(
        self, parent_turn_id: str, thread_id: str, reason: str
    ) -> DeepContinuationOutcome:
        try:
            terminal = self.terminal.block(
                parent_turn_id=parent_turn_id, thread_id=thread_id, reason=reason
            )
        except DeepFinalizationError as exc:
            return self._outcome("blocked", parent_turn_id, "", exc.reason)
        return DeepContinuationOutcome(
            status="blocked",
            parent_turn_id=parent_turn_id,
            child_run_id=str(terminal.get("child_run_id") or ""),
            reason=str(terminal.get("reason") or reason),
            result=None,
        )

    @staticmethod
    def _outcome(
        status: str, parent_turn_id: str, child_run_id: str, reason: str
    ) -> DeepContinuationOutcome:
        return DeepContinuationOutcome(
            status=status,  # type: ignore[arg-type]
            parent_turn_id=parent_turn_id,
            child_run_id=child_run_id,
            reason=reason,
            result=None,
        )
