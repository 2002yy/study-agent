"""Deep-2: admit a prepared Deep child into the existing active research runtime.

This service is the Deep tier's front door. It validates the Deep-1 authority chain again
rather than trusting it, attaches the Deep execution envelope and an active Claim Engine state
in one compare-and-swap, and then hands the child to the existing dispatcher. It executes no
research itself and creates no research machinery.

Two rules are load-bearing.

**Absent and unusable are different.** The generic dispatcher treats an invalid or non-active
Claim Engine state as "run legacy", which is a silent downgrade out of the Claim Engine. Deep
must separate those cases before dispatching, because a Deep run that quietly became a legacy
run would burn budget and produce results outside the Deep contract.

**The parent is never touched.** The Deep terminal stays pending for the whole of Deep-2;
finalization belongs to Deep-3. Nothing here writes the parent snapshot, the assistant message,
pedagogy or learning state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from src.application.research_web_lookup_dispatch import (
    ClaimEngineDispatchWebLookupService,
    claim_engine_load,
)
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.contracts import ResearchBudget, build_research_state
from src.web.research.deep_handoff import DEEP_TERMINAL_SCHEMA, load_deep_handoff
from src.web.research.deep_runtime import (
    DEEP_BUDGET_PROFILE,
    DEEP_HARD_SECONDS,
    build_execution_envelope,
    load_execution_envelope,
    load_seed,
    reference_date_from,
    validate_execution_envelope,
    verify_seed_sources,
)
from src.web.research.deep_seed import seed_refs_match
from src.web.research.state import attach_claim_engine_state

# The frozen Deep v1 profile. Independent of the Lookup and Standard tiers.
DEEP_V1_BUDGET = ResearchBudget(
    max_candidates=40,
    max_reads=12,
    soft_timeout_seconds=120,
    hard_timeout_seconds=DEEP_HARD_SECONDS,
    max_total_chars=80_000,
)

TERMINAL_CHILD_STATUSES = frozenset({"completed", "partial", "failed", "cancelled"})


@dataclass(frozen=True)
class DeepExecutionOutcome:
    status: Literal["not_requested", "deferred", "completed", "blocked"]
    parent_turn_id: str
    child_run_id: str
    reason: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DeepExecutionService:
    def __init__(
        self,
        repository: RuntimeRepository,
        runs: WebLookupRepository,
        dispatch: Any = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self.repository = repository
        self.runs = runs
        self.dispatch = dispatch or ClaimEngineDispatchWebLookupService(runs)
        self.clock = clock

    def execute(self, *, parent_turn_id: str, thread_id: str) -> DeepExecutionOutcome:
        """Admit and run the Deep child, or report why not. Never guesses at integrity."""

        try:
            return self._execute(parent_turn_id, thread_id)
        except ValueError as exc:
            # Only deterministic admission failures reach here; the reasons are bounded.
            return DeepExecutionOutcome(
                status="blocked",
                parent_turn_id=parent_turn_id,
                child_run_id="",
                reason=_blocked_reason(exc),
            )

    def _execute(self, parent_turn_id: str, thread_id: str) -> DeepExecutionOutcome:
        parent = self.repository.get_chat_turn(parent_turn_id)
        if (
            parent is None
            or parent.thread_id != thread_id
            or parent.status != "completed"
            or parent.cancel_requested_at
        ):
            raise ValueError("Deep parent turn owner/status mismatch")

        terminal = (parent.rag_snapshot or {}).get("deep_terminal")
        if terminal is None:
            return self._outcome("not_requested", parent_turn_id, "", "no_deep_terminal")
        if not isinstance(terminal, dict):
            raise ValueError("Deep terminal is not a terminal")
        if (
            terminal.get("schema_version") != DEEP_TERMINAL_SCHEMA
            or terminal.get("state") != "ESCALATE_DEEP"
        ):
            raise ValueError("Deep terminal schema or state mismatch")
        if str(terminal.get("dispatch_status") or "") != "pending":
            return self._outcome(
                "not_requested", parent_turn_id, "", "deep_terminal_not_pending"
            )
        owner = terminal.get("owner") or {}
        if owner.get("thread_id") != thread_id or owner.get("turn_id") != parent_turn_id:
            raise ValueError("Deep terminal owner mismatch")

        handoff = load_deep_handoff(terminal.get("handoff") or {})
        if str(handoff.get("parent_turn_id") or "") != parent_turn_id:
            raise ValueError("Deep handoff parent mismatch")

        child_run_id = str(terminal.get("child_run_id") or "")
        if not child_run_id:
            raise ValueError("Deep terminal has no child")
        child = self.runs.get(child_run_id)
        if child is None:
            raise ValueError("Deep child is missing")
        if (
            child.owner_thread_id != thread_id
            or str(child.parent_run_id or "")
            != str(handoff.get("standard_child_run_id") or "")
            or child.query != str(handoff.get("query") or "")
            or child.query != parent.user_message
        ):
            raise ValueError("Deep child lineage mismatch")

        seed = load_seed(child.research_context)
        ok, reason = verify_seed_sources(seed)
        if not ok or seed is None:
            raise ValueError(f"Deep seed unusable: {reason}")
        if str(seed.get("standard_child_run_id") or "") != str(
            handoff.get("standard_child_run_id") or ""
        ):
            raise ValueError("Deep seed lineage mismatch")
        if not seed_refs_match(
            list(handoff.get("seed_source_refs") or []), list(seed.get("refs") or [])
        ):
            raise ValueError("Deep handoff seed refs mismatch")

        # A child that already reached a runtime terminal is done: no second execution.
        if child.status in TERMINAL_CHILD_STATUSES:
            return self._outcome("completed", parent_turn_id, child_run_id, "child_terminal")

        envelope = load_execution_envelope(child.research_context)
        loaded = claim_engine_load(child)
        if loaded.status == "absent" and envelope is None:
            return self._first_admission(parent, parent_turn_id, thread_id, child, handoff)
        if not (loaded.available and loaded.effective_mode == "active"):
            # Present but unusable. The dispatcher would silently run legacy here; Deep must not.
            raise ValueError("Claim Engine state is present but unusable")
        if envelope is None:
            raise ValueError("Deep execution and Claim Engine state are asymmetric")
        valid, why = validate_execution_envelope(envelope)
        if not valid:
            raise ValueError(f"Deep execution envelope invalid: {why}")
        if child.status == "running":
            return self._outcome("deferred", parent_turn_id, child_run_id, "lease_busy")
        return self._dispatch(parent_turn_id, child_run_id)

    def _first_admission(
        self,
        parent: Any,
        parent_turn_id: str,
        thread_id: str,
        child: Any,
        handoff: dict,
    ) -> DeepExecutionOutcome:
        """Attach the envelope and an active state in one compare-and-swap.

        Both facts land together, so there is no legal crash window in which one exists without
        the other. A losing racer reloads and reuses whatever the winner wrote.
        """

        now = self.clock()
        envelope = build_execution_envelope(
            parent_turn_id=parent_turn_id,
            handoff_sha256=str(handoff.get("payload_sha256") or ""),
            admitted_at=now,
        )
        state = build_research_state(
            mode="active",
            questions=(),
            claims=(),
            evidence=(),
            evidence_links=(),
            source_clusters=(),
            gaps=(),
            conflict_gaps=(),
            budget=DEEP_V1_BUDGET,
            known_evidence_ids=(),
            reference_date=reference_date_from(parent.created_at),
        )
        context = attach_claim_engine_state(
            child.research_context, state, known_evidence_ids=()
        )
        deep = dict(context.get("deep") or {})
        deep["execution"] = envelope
        context["deep"] = deep

        updated = self.runs.attach_pending_context(
            child.id,
            expected_version=child.version,
            research_context=context,
        )
        if updated is None:
            return self._resolve_attach_conflict(parent_turn_id, thread_id, child.id)
        if updated.status in TERMINAL_CHILD_STATUSES:
            return self._outcome("completed", parent_turn_id, child.id, "child_terminal")
        return self._dispatch(parent_turn_id, child.id)

    def _resolve_attach_conflict(
        self, parent_turn_id: str, thread_id: str, child_run_id: str
    ) -> DeepExecutionOutcome:
        """A concurrent first admission won. Reuse it rather than attaching again."""

        reloaded = self.runs.get(child_run_id)
        if reloaded is None or reloaded.owner_thread_id != thread_id:
            raise ValueError("Deep child owner mismatch after attach conflict")
        if reloaded.status in TERMINAL_CHILD_STATUSES:
            return self._outcome("completed", parent_turn_id, child_run_id, "child_terminal")
        loaded = claim_engine_load(reloaded)
        envelope = load_execution_envelope(reloaded.research_context)
        if loaded.available and loaded.effective_mode == "active" and envelope is not None:
            valid, why = validate_execution_envelope(envelope)
            if not valid:
                raise ValueError(f"Deep execution envelope invalid: {why}")
            if reloaded.status == "running":
                return self._outcome("deferred", parent_turn_id, child_run_id, "lease_busy")
            return self._dispatch(parent_turn_id, child_run_id)
        if loaded.status == "absent" and envelope is None:
            # The other racer lost too (it released without writing); nothing was attached.
            return self._outcome("deferred", parent_turn_id, child_run_id, "attach_retry")
        raise ValueError("Deep execution and Claim Engine state are asymmetric")

    def _dispatch(self, parent_turn_id: str, child_run_id: str) -> DeepExecutionOutcome:
        """Hand the child to the existing dispatcher. It owns all execution semantics."""

        run = self.dispatch.execute(child_run_id)
        status = str(getattr(run, "status", "") or "")
        if status in TERMINAL_CHILD_STATUSES:
            return self._outcome("completed", parent_turn_id, child_run_id, status)
        return self._outcome("deferred", parent_turn_id, child_run_id, "in_progress")

    @staticmethod
    def _outcome(
        status: str, parent_turn_id: str, child_run_id: str, reason: str
    ) -> DeepExecutionOutcome:
        return DeepExecutionOutcome(
            status=status,  # type: ignore[arg-type]
            parent_turn_id=parent_turn_id,
            child_run_id=child_run_id,
            reason=reason,
        )


def _blocked_reason(exc: BaseException) -> str:
    """A bounded reason code. Exception text is never persisted or returned raw."""

    text = str(exc).lower()
    if "seed" in text:
        return "seed_integrity_failure"
    if "handoff" in text:
        return "handoff_integrity_failure"
    if "lineage" in text:
        return "lineage_mismatch"
    if "owner" in text:
        return "owner_mismatch"
    if "execution" in text:
        return "execution_envelope_invalid"
    if "claim engine" in text:
        return "claim_engine_unusable"
    if "parent" in text:
        return "parent_unavailable"
    return "admission_failed"


def deep_budget_profile() -> str:
    """The frozen Deep budget profile name, for diagnostics and tests."""

    return DEEP_BUDGET_PROFILE
