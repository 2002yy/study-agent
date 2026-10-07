"""Deep-1: prepare a Deep handoff from a completed Standard artifact.

This service only validates, decides, projects a seed and persists. It never calls a gateway or
a model, and it executes no research - the Deep child is left waiting.

Everything it needs is reloaded from server-owned persistence. A caller supplies a parent turn
and a thread, never a handoff, a budget, a field list or a digest, so a caller cannot steer
what Deep is told to research.

The Deep terminal lives in its own namespace. Standard's artifact is read once and never
rewritten.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from src.domain.runtime_entities import WebLookupRun
from src.repositories.deep_handoff_repository import NO_TERMINAL, DeepHandoffRepository
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.standard_execution_repository import StandardExecutionRepository
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.deep_handoff import (
    BLOCKED,
    CONTINUATION_SCHEMA,
    DEEP_TERMINAL_SCHEMA,
    NOT_REQUESTED,
    PENDING,
    build_deep_handoff,
    decide_deep_handoff,
    deep_child_identity,
    deep_terminal,
    load_deep_handoff,
)
from src.web.research.deep_seed import (
    SeedIntegrityError,
    project_standard_seed,
    seed_refs_match,
)

DEEP_STAGE = "deep_handoff"


@dataclass(frozen=True)
class DeepHandoffOutcome:
    status: Literal["not_requested", "prepared", "blocked"]
    parent_turn_id: str
    child_run_id: str
    reason: str
    handoff_sha256: str


def _blocked_reason(exc: BaseException) -> str:
    """A bounded reason code. Exception text is never persisted."""

    text = str(exc).lower()
    if "handoff" in text:
        return "handoff_integrity_failure"
    if "seed" in text or "digest mismatch" in text:
        return "seed_integrity_failure"
    if "continuation" in text:
        return "standard_artifact_invalid"
    if "source" in text or "lineage" in text:
        return "lineage_mismatch"
    if "owner" in text or "thread" in text:
        return "owner_mismatch"
    if "journal" in text or "ledger" in text:
        return "journal_invalid"
    if "parent" in text:
        return "parent_unavailable"
    return "admission_failed"


class DeepHandoffService:
    def __init__(
        self,
        repository: RuntimeRepository,
        runs: WebLookupRepository,
    ):
        self.repository = repository
        self.runs = runs
        self.terminal = DeepHandoffRepository(repository.database)
        self.standard = StandardExecutionRepository(repository.database)

    def prepare(self, *, parent_turn_id: str, thread_id: str) -> DeepHandoffOutcome:
        """Validate the Standard artifact and prepare the Deep child. No research is run."""

        existing = self.terminal.read_terminal(parent_turn_id, thread_id)
        if existing is not NO_TERMINAL:
            # Existence is the trigger, not validity: anything recorded goes to the retry path
            # so a tampered terminal fails closed instead of looking absent.
            return self._retry(existing, parent_turn_id, thread_id)

        try:
            return self._prepare(parent_turn_id, thread_id)
        except SeedIntegrityError:
            # The Standard journal contradicts itself: fail closed, create nothing.
            return self._blocked(parent_turn_id, thread_id, "seed_integrity_failure")
        except ValueError as exc:
            return self._blocked(parent_turn_id, thread_id, _blocked_reason(exc))

    def _retry(
        self, existing: dict, parent_turn_id: str, thread_id: str
    ) -> DeepHandoffOutcome:
        """Retry path: the durable terminal is the first authority, and it is never overwritten."""

        if not isinstance(existing, dict):
            # Something is recorded but it is not a terminal: fail closed, do not start fresh.
            return DeepHandoffOutcome(
                status="blocked",
                parent_turn_id=parent_turn_id,
                child_run_id="",
                reason="handoff_integrity_failure",
                handoff_sha256="",
            )
        status = str(existing.get("dispatch_status") or "")
        if status == BLOCKED:
            # A blocked terminal is complete. It legitimately has no handoff and no child, so it
            # is returned as decided - the first blocked reason is preserved, not re-derived.
            return DeepHandoffOutcome(
                status="blocked",
                parent_turn_id=parent_turn_id,
                child_run_id=str(existing.get("child_run_id") or ""),
                reason=str(existing.get("reason") or ""),
                handoff_sha256=str((existing.get("handoff") or {}).get("payload_sha256") or ""),
            )
        if status != PENDING:
            # The durable vocabulary is exactly pending/blocked; anything else is not guessed at.
            return DeepHandoffOutcome(
                status="blocked",
                parent_turn_id=parent_turn_id,
                child_run_id="",
                reason="handoff_integrity_failure",
                handoff_sha256="",
            )

        # A prepared terminal is never trusted: the handoff, the child and the seed must all
        # still agree before the same child is reported.
        handoff_sha256 = str((existing.get("handoff") or {}).get("payload_sha256") or "")
        child_run_id = str(existing.get("child_run_id") or "")
        try:
            if str(existing.get("schema_version") or "") != DEEP_TERMINAL_SCHEMA:
                raise ValueError("deep terminal schema mismatch")
            if str(existing.get("state") or "") != "ESCALATE_DEEP":
                raise ValueError("deep terminal state mismatch")
            owner = existing.get("owner") or {}
            if owner.get("thread_id") != thread_id or owner.get("turn_id") != parent_turn_id:
                raise ValueError("deep terminal owner mismatch")
            handoff = load_deep_handoff(existing.get("handoff") or {})
            if not child_run_id:
                raise ValueError("deep terminal has no child")
            child = self.runs.get(child_run_id)
            if (
                child is None
                or child.owner_thread_id != thread_id
                or str(child.parent_run_id or "")
                != str(handoff.get("standard_child_run_id") or "")
                or child.query != str(handoff.get("query") or "")
            ):
                raise ValueError("deep child lineage mismatch")
            seed = self.deep_seed(child_run_id, thread_id)
            if not seed_refs_match(
                list(handoff.get("seed_source_refs") or []), list(seed.get("refs") or [])
            ):
                raise ValueError("deep handoff seed refs mismatch")
        except ValueError as exc:
            return DeepHandoffOutcome(
                status="blocked",
                parent_turn_id=parent_turn_id,
                child_run_id=child_run_id,
                reason=_blocked_reason(exc),
                handoff_sha256="",
            )
        return DeepHandoffOutcome(
            status="prepared",
            parent_turn_id=parent_turn_id,
            child_run_id=child_run_id,
            reason=str(existing.get("reason") or ""),
            handoff_sha256=handoff_sha256,
        )

    def _prepare(self, parent_turn_id: str, thread_id: str) -> DeepHandoffOutcome:
        parent = self.repository.get_chat_turn(parent_turn_id)
        if (
            parent is None
            or parent.thread_id != thread_id
            or parent.status != "completed"
            or parent.cancel_requested_at
        ):
            raise ValueError("Deep parent turn owner/status mismatch")

        snapshot = parent.rag_snapshot or {}
        lookup_terminal = snapshot.get("lookup_terminal") or {}
        if (
            lookup_terminal.get("state") != "ESCALATE_STANDARD"
            or lookup_terminal.get("dispatch_status") != "completed"
        ):
            return DeepHandoffOutcome(
                status="not_requested",
                parent_turn_id=parent_turn_id,
                child_run_id="",
                reason="no_completed_standard_terminal",
                handoff_sha256="",
            )

        continuation = snapshot.get("standard_continuation") or {}
        if (
            continuation.get("schema_version") != CONTINUATION_SCHEMA
            or continuation.get("publication_authority") is not False
        ):
            raise ValueError("Standard continuation artifact is not valid")
        result = continuation.get("result")
        if not isinstance(result, dict):
            raise ValueError("Standard continuation result is missing")
        standard_child_run_id = str(continuation.get("child_run_id") or "")
        if not standard_child_run_id:
            raise ValueError("Standard child identity is missing")

        decision = decide_deep_handoff(result, stop_reason=str(result.get("stop_reason") or ""))
        if decision == NOT_REQUESTED:
            # Standard resolved the gap, or failed to execute. Neither is a depth signal.
            return DeepHandoffOutcome(
                status="not_requested",
                parent_turn_id=parent_turn_id,
                child_run_id="",
                reason=str(result.get("stop_reason") or ""),
                handoff_sha256="",
            )
        if decision == BLOCKED:
            raise ValueError("unknown Standard stop reason")

        child = self.runs.get(standard_child_run_id)
        if child is None:
            raise ValueError("Standard child lineage mismatch")
        ledger = self.standard.child_ledger(standard_child_run_id, thread_id)
        self._validate_lineage(
            parent=parent,
            thread_id=thread_id,
            continuation=continuation,
            child=child,
            ledger=ledger,
        )

        seed = project_standard_seed(ledger, standard_child_run_id=standard_child_run_id)
        handoff = build_deep_handoff(
            parent_turn_id=parent_turn_id,
            query=parent.user_message,
            standard_child_run_id=standard_child_run_id,
            standard_source_run_id=str(continuation.get("source_run_id") or ""),
            standard_handoff_sha256=str(continuation.get("handoff_sha256") or ""),
            standard_result=result,
            seed_source_refs=seed["refs"],
        )

        child_run_id, request_id = deep_child_identity(parent_turn_id, standard_child_run_id)
        run = self.runs.create_child(
            WebLookupRun(
                id=child_run_id,
                query=parent.user_message,
                stage=DEEP_STAGE,
                status="pending",
                owner_thread_id=thread_id,
                parent_run_id=standard_child_run_id,
                create_request_id=request_id,
                research_context={
                    "owner": {"thread_id": thread_id, "turn_id": parent_turn_id},
                    # The data plane: already-read bytes, nothing more.
                    "deep": {"seed": seed},
                },
            )
        )
        terminal = deep_terminal(
            parent_turn_id=parent_turn_id,
            thread_id=thread_id,
            source_run_id=str(continuation.get("source_run_id") or ""),
            child_run_id=run.id,
            handoff=handoff,
            dispatch_status=PENDING,
        )
        saved = self.terminal.persist(
            parent_turn_id=parent_turn_id, thread_id=thread_id, terminal=terminal
        )
        return DeepHandoffOutcome(
            status="prepared",
            parent_turn_id=parent_turn_id,
            child_run_id=str(saved.get("child_run_id") or run.id),
            reason=str(saved.get("reason") or ""),
            handoff_sha256=str((saved.get("handoff") or {}).get("payload_sha256") or ""),
        )

    def _blocked(
        self, parent_turn_id: str, thread_id: str, reason: str
    ) -> DeepHandoffOutcome:
        try:
            self.terminal.persist(
                parent_turn_id=parent_turn_id,
                thread_id=thread_id,
                terminal=deep_terminal(
                    parent_turn_id=parent_turn_id,
                    thread_id=thread_id,
                    source_run_id="",
                    child_run_id="",
                    handoff={},
                    dispatch_status=BLOCKED,
                    reason=reason,
                ),
            )
        except ValueError:
            # The parent moved under us; the outcome is still an honest "blocked".
            pass
        return DeepHandoffOutcome(
            status="blocked",
            parent_turn_id=parent_turn_id,
            child_run_id="",
            reason=reason,
            handoff_sha256="",
        )

    def deep_seed(self, child_run_id: str, thread_id: str) -> dict[str, Any]:
        """The Deep child's durable seed, for a later tier to ingest. Read-only."""

        run = self.runs.get(child_run_id)
        if run is None or run.owner_thread_id != thread_id:
            raise ValueError("Deep child owner mismatch")
        deep = run.research_context.get("deep") or {}
        seed = deep.get("seed")
        if not isinstance(seed, dict):
            raise ValueError("Deep child has no seed")
        return seed

    def _validate_lineage(
        self,
        *,
        parent: Any,
        thread_id: str,
        continuation: dict,
        child: Any,
        ledger: dict,
    ) -> None:
        """Re-verify the whole Standard lineage, not just the child row.

        The artifact, the child run, the child journal and the original source run must all
        agree. Deep only consumes a Standard artifact whose lineage is fully re-established.
        """

        source_run_id = str(continuation.get("source_run_id") or "")
        if (
            child.owner_thread_id != thread_id
            or child.parent_run_id != source_run_id
            or child.query != parent.user_message
        ):
            raise ValueError("Standard child lineage mismatch")
        if str(ledger.get("handoff_sha256") or "") != str(
            continuation.get("handoff_sha256") or ""
        ):
            raise ValueError("Standard handoff digest mismatch")
        if (
            str(ledger.get("thread_id") or "") != thread_id
            or str(ledger.get("source_run_id") or "") != source_run_id
        ):
            raise ValueError("Standard journal lineage mismatch")
        research = ledger.get("research") or {}
        if research.get("status") != "completed" or not isinstance(
            research.get("result"), dict
        ):
            # The journal itself must be terminal, not just the artifact that cites it.
            raise ValueError("Standard child journal is not terminal")

        source = self.runs.get(source_run_id)
        if (
            source is None
            or source.owner_thread_id != thread_id
            or source.status != "completed"
            or source.cancel_requested_at
            or source.query != parent.user_message
        ):
            raise ValueError("Standard source run lineage mismatch")
        if int(ledger.get("source_run_version") or -1) != int(source.version):
            raise ValueError("Standard source run version mismatch")
        owner = source.research_context.get("owner") or {}
        if owner.get("thread_id") != thread_id or owner.get("turn_id") != parent.id:
            raise ValueError("Standard source run owner mismatch")
