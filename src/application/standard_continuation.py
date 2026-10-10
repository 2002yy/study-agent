"""Standard-4: continue a pending Standard handoff automatically, after the parent is durable.

The parent turn must already be ``completed`` before admission - that is what the existing
Standard admission requires, and it is why this runs after the answer, not before it.

Two invariants are load-bearing.

**The parent stays ``pending`` while the child works.** The dispatch journal re-requires
``dispatch_status == pending`` on every transaction, so moving the parent to ``running`` would
make the executor reject its own later writes. Only ``pending -> completed`` and
``pending -> blocked`` are allowed.

**The overall deadline is derived from the parent's creation time.** Re-entering Standard must
not restart the clock: the window is ``parent.created_at + Lookup.hard + Standard.hard`` and
admission rejects anything later.

Nothing here publishes. The artifact records evidence state with ``publication_authority``
false, and the assistant message is never touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal, Mapping

from src.application.standard_execution import StandardExecution
from src.application.standard_research import ModelStandardPlanner, StandardResearchLoop
from src.application.standard_shadow_seam import observe_shadow_for_standard
from src.application.shadow_isolation import BestEffortTelemetry
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.standard_execution_repository import (
    StandardExecutionRepository,
    StandardResearchBusy,
)
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.standard_binding import apply_bindings, bind_fields
from src.web.research.standard_binding_projection import (
    project_mechanical_claims,
    project_trusted_sources,
)
from src.web.research_recovery import LOOKUP_BUDGET, STANDARD_BUDGET, model_targets

CONTINUATION_SCHEMA = "standard-auto-continuation-v1"

# At most this many advance() calls: None means "paused at a persisted step boundary", and the
# total action budget is already bounded, so one extra call is enough to finish.
MAX_ADVANCES = 2

# The canonical target identity lives in research_recovery; Standard-4 must not keep a second
# identity grammar that would accept 3.14.1 for a query about 3.14.
def derive_target(query: str) -> tuple[str, str] | None:
    """The single unambiguous ``(name, version)`` target named by the query, or None."""

    targets = model_targets(str(query or ""))
    return targets[0] if len(targets) == 1 else None


def blocked_reason(exc: BaseException) -> str:
    """A bounded reason code. Exception text is never persisted."""

    text = str(exc).lower()
    if "handoff" in text:
        return "handoff_integrity_failure"
    if "source" in text:
        return "source_run_mismatch"
    if "owner" in text:
        return "owner_mismatch"
    if "journal" in text:
        return "journal_invalid"
    if "parent" in text:
        return "parent_unavailable"
    return "admission_failed"


@dataclass(frozen=True)
class StandardContinuationOutcome:
    status: Literal["not_requested", "completed", "deferred", "blocked"]
    parent_turn_id: str
    child_run_id: str
    reason: str
    result: dict[str, Any] | None


class StandardContinuationService:
    def __init__(
        self,
        repository: RuntimeRepository,
        runs: WebLookupRepository,
        gateway: Any,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        planner_factory: Callable[[], Callable[[dict], dict]] = ModelStandardPlanner,
        shadow_telemetry: BestEffortTelemetry | None = None,
        shadow_runner: Callable[[str, float], dict[str, Any]] | None = None,
    ):
        self.repository = repository
        self.runs = runs
        self.gateway = gateway
        self.clock = clock
        self.planner_factory = planner_factory
        self.shadow_telemetry = shadow_telemetry
        self.shadow_runner = shadow_runner
        self.journal = StandardExecutionRepository(repository.database)

    def continue_pending(
        self, *, parent_turn_id: str, thread_id: str
    ) -> StandardContinuationOutcome:
        """Resume or finish the single Standard child for a pending handoff."""

        existing = self.journal.continuation_artifact(parent_turn_id, thread_id)
        if existing is not None:
            # Exactly-once: a terminal artifact is returned, never re-researched.
            blocked = bool(existing.get("reason"))
            return StandardContinuationOutcome(
                status="blocked" if blocked else "completed",
                parent_turn_id=parent_turn_id,
                child_run_id=str(existing.get("child_run_id") or ""),
                reason=str(existing.get("reason") or ""),
                result=existing.get("result")
                if isinstance(existing.get("result"), dict)
                else None,
            )

        parent = self.repository.get_chat_turn(parent_turn_id)
        if parent is None or parent.thread_id != thread_id:
            return self._blocked(parent_turn_id, thread_id, "parent_unavailable")
        terminal = parent.rag_snapshot.get("lookup_terminal") or {}
        if (
            terminal.get("state") != "ESCALATE_STANDARD"
            or terminal.get("dispatch_status") != "pending"
        ):
            return StandardContinuationOutcome(
                status="not_requested",
                parent_turn_id=parent_turn_id,
                child_run_id="",
                reason="no_pending_handoff",
                result=None,
            )

        created = datetime.fromisoformat(parent.created_at)
        overall_deadline = created + timedelta(
            seconds=LOOKUP_BUDGET.hard_seconds + STANDARD_BUDGET.hard_seconds
        )
        try:
            execution = StandardExecution.start(
                self.repository,
                self.runs,
                parent_turn_id=parent_turn_id,
                thread_id=thread_id,
                overall_deadline=overall_deadline,
                clock=self.clock,
            )
        except StandardResearchBusy:
            # Another owner holds the lease: the parent stays pending.
            return StandardContinuationOutcome(
                status="deferred",
                parent_turn_id=parent_turn_id,
                child_run_id="",
                reason="lease_busy",
                result=None,
            )
        except ValueError as exc:
            return self._blocked(parent_turn_id, thread_id, blocked_reason(exc))

        loop = StandardResearchLoop(execution, self.planner_factory())
        result: dict | None = None
        for _ in range(MAX_ADVANCES):
            result = loop.advance(self.gateway, max_steps=48)
            if result is not None:
                break
        if result is None:
            # Paused at a durable step boundary: not a failure, and the parent stays pending.
            return StandardContinuationOutcome(
                status="deferred",
                parent_turn_id=parent_turn_id,
                child_run_id=execution.run_id,
                reason="step_boundary",
                result=None,
            )

        query = (terminal.get("handoff") or {}).get("query") or parent.user_message
        # M4-A read-only shadow: submitted, never awaited, and its result cannot be
        # read by anything below. Flag OFF makes this a no-op.
        self._observe_standard_shadow(query=query, handoff=terminal.get("handoff"))
        ledger = self.journal.child_ledger(execution.run_id, thread_id)
        fields = result.get("unresolved_gaps") or []
        trusted = project_trusted_sources(ledger)
        claims = project_mechanical_claims(fields, trusted, target=derive_target(query))
        bound = apply_bindings(result, bind_fields(fields, claims, trusted))

        saved = self.journal.finalize_continuation(
            execution.run_id,
            thread_id,
            self.clock(),
            artifact={
                "schema_version": CONTINUATION_SCHEMA,
                "result": bound,
                "publication_authority": False,
            },
        )
        return StandardContinuationOutcome(
            status="completed",
            parent_turn_id=parent_turn_id,
            child_run_id=execution.run_id,
            reason=str(bound.get("stop_reason") or ""),
            result=saved.get("result") if isinstance(saved.get("result"), dict) else bound,
        )

    def _observe_standard_shadow(
        self, *, query: str, handoff: Mapping[str, Any] | None
    ) -> None:
        """Best-effort, non-blocking, read-only B-Search shadow.

        The submission returns immediately; the outcome is only ever recorded as
        telemetry. Any failure here is swallowed so the main research chain cannot
        be slowed or interrupted by the observer.
        """
        try:
            observe_shadow_for_standard(
                query=query,
                handoff=handoff,
                telemetry=self.shadow_telemetry,
                runner=self.shadow_runner,
            )
        except Exception:  # noqa: BLE001 - shadow must never break the main chain
            return

    def _blocked(
        self, parent_turn_id: str, thread_id: str, reason: str
    ) -> StandardContinuationOutcome:
        try:
            self.journal.block_continuation(parent_turn_id, thread_id, reason)
        except ValueError:
            # The parent moved under us; the outcome is still an honest "blocked".
            pass
        return StandardContinuationOutcome(
            status="blocked",
            parent_turn_id=parent_turn_id,
            child_run_id="",
            reason=reason,
            result=None,
        )
