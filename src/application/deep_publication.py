"""Deep-4A: turn a completed Deep child into an audited publication candidate.

This service runs in the background trigger, never on the chat response path. It produces an
audit artifact and stops there: it does not publish, does not touch the answer, and does not
grant any authority.

Three rules shape it.

**It is deterministic and offline.** The synthesis writer is the extractive one and the auditor
gets no judge, so after the Deep child is terminal this makes zero model calls, zero network
calls and zero reads.

**Audited is not approved.** With no qualified semantic judge the honest terminal is
audited-but-not-approved, and publication authority stays false. A mechanically rejected
synthesis is that same honest terminal, not an integrity failure - research insufficiency is not
corruption.

**Only integrity blocks.** A missing child, a lineage mismatch, a changed source run or an
unusable research state are blocked; everything else that merely falls short of publication is
recorded as an audited candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from src.application.research_web_lookup_dispatch import claim_engine_load
from src.repositories.deep_continuation_repository import DeepFinalizationError
from src.repositories.deep_publication_repository import (
    AUDIT_RESULT_SCHEMA,
    AUDITED,
    BLOCKED,
    PENDING,
    REASON_CLAIM_ENGINE_UNUSABLE,
    REASON_CHILD_MISSING,
    REASON_PUBLICATION_INTEGRITY,
    DeepPublicationRepository,
    canonical_digest,
    source_run_digest,
    validate_recorded_publication,
)
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.final_answer_auditor import audit_final_answer
from src.web.research.research_brief_projection import build_research_brief_projection
from src.web.research.synthesis_assembler import (
    SynthesisContractViolation,
    assemble_synthesis_draft,
    collect_evidence_payloads,
    extractive_writer,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DeepPublicationOutcome:
    status: Literal["not_requested", "audited", "blocked"]
    parent_turn_id: str
    child_run_id: str
    reason: str
    result: dict[str, Any] | None = None


def _audit_projection(audit: Any, draft: Any) -> dict[str, Any]:
    """The bounded audit facts that may be hashed. Never raw text."""

    return {
        "verdict": str(getattr(audit, "verdict", "")),
        "approval_status": str(getattr(audit, "approval_status", "")),
        "question_coverage": str(getattr(audit, "question_coverage", "")),
        "evidence_grounding": str(getattr(audit, "evidence_grounding", "")),
        "issue_codes": sorted(
            {str(getattr(issue, "issue_type", "")) for issue in getattr(audit, "issues", ())}
        ),
        "unanswered_aspects": list(getattr(audit, "unanswered_aspects", ())),
        "contradiction_gap_count": len(getattr(audit, "contradiction_gaps", ())),
        "citation_support_gap_count": len(getattr(audit, "citation_support_gaps", ())),
        "repair_used": bool(getattr(audit, "repair_used", False)),
    }


class DeepPublicationService:
    def __init__(
        self,
        repository: RuntimeRepository,
        runs: WebLookupRepository,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self.repository = repository
        self.runs = runs
        self.clock = clock
        self.publication = DeepPublicationRepository(repository.database)

    def process(self, *, parent_turn_id: str, thread_id: str) -> DeepPublicationOutcome:
        parent = self.repository.get_chat_turn(parent_turn_id)
        if (
            parent is None
            or parent.thread_id != thread_id
            or parent.status != "completed"
            or parent.cancel_requested_at
        ):
            return self._outcome("blocked", parent_turn_id, "", "parent_unavailable")

        read = self.publication.read(parent_turn_id, thread_id)
        if read.present and not isinstance(read.publication, dict):
            # Recorded but not a publication: fail closed and never rewrite what is there.
            return self._outcome("blocked", parent_turn_id, "", REASON_PUBLICATION_INTEGRITY)

        if read.present:
            recorded = read.publication
            status = str(recorded.get("dispatch_status") or "")
            if status in {AUDITED, BLOCKED}:
                # First terminal wins, but a recorded terminal is not thereby trusted.
                valid, why = validate_recorded_publication(
                    recorded, parent_turn_id=parent_turn_id, thread_id=thread_id
                )
                if not valid:
                    return self._outcome("blocked", parent_turn_id, "", why)
                result = recorded.get("result")
                return DeepPublicationOutcome(
                    status="audited" if status == AUDITED else "blocked",
                    parent_turn_id=parent_turn_id,
                    child_run_id=str((recorded.get("owner") or {}).get("child_run_id") or ""),
                    reason=str(recorded.get("reason") or ""),
                    result=result if isinstance(result, dict) else None,
                )
            if status != PENDING:
                return self._outcome("blocked", parent_turn_id, "", REASON_PUBLICATION_INTEGRITY)
            child_run_id = str((read.publication.get("owner") or {}).get("child_run_id") or "")
            if not child_run_id:
                return self._block(parent_turn_id, thread_id, REASON_CHILD_MISSING)
        else:
            child_run_id = self._deep_child_run_id(parent)
            if not child_run_id:
                return self._outcome(
                    "not_requested", parent_turn_id, "", "no_completed_deep_terminal"
                )
            try:
                self.publication.attach_pending(
                    parent_turn_id=parent_turn_id,
                    thread_id=thread_id,
                    child_run_id=child_run_id,
                )
            except DeepFinalizationError as exc:
                return self._block(parent_turn_id, thread_id, exc.reason)

        return self._audit(parent_turn_id, thread_id, child_run_id)

    def _deep_child_run_id(self, parent: Any) -> str:
        """The child of a valid completed Deep terminal, or "" when there is no such terminal."""

        terminal = (parent.rag_snapshot or {}).get("deep_terminal")
        if not isinstance(terminal, dict):
            return ""
        if (
            terminal.get("schema_version") != "standard-deep-terminal-v1"
            or terminal.get("state") != "ESCALATE_DEEP"
            or terminal.get("dispatch_status") != "completed"
        ):
            return ""
        return str(terminal.get("child_run_id") or "")

    def _audit(
        self, parent_turn_id: str, thread_id: str, child_run_id: str
    ) -> DeepPublicationOutcome:
        row = self._child_row(child_run_id)
        if row is None:
            return self._block(parent_turn_id, thread_id, REASON_CHILD_MISSING)
        digest = source_run_digest(row)
        child = self.runs.get(child_run_id)
        if child is None or child.owner_thread_id != thread_id:
            return self._block(parent_turn_id, thread_id, REASON_CHILD_MISSING)
        # The row digested above and the object used for the audit must be the same snapshot,
        # otherwise the projection could come from one child while the provenance claims another.
        if int(getattr(child, "version", -1)) != int(row["version"]):
            return self._block(parent_turn_id, thread_id, "source_run_changed")

        loaded = claim_engine_load(child)
        if not (loaded.available and loaded.effective_mode == "active" and loaded.state):
            return self._block(parent_turn_id, thread_id, REASON_CLAIM_ENGINE_UNUSABLE)
        state = loaded.state

        projection = build_research_brief_projection(state)
        payloads = collect_evidence_payloads(state)
        state_digest = canonical_digest(state.to_dict())
        projection_digest = canonical_digest(projection.to_dict())

        candidate_status = "assembled"
        draft_digest = ""
        try:
            draft = assemble_synthesis_draft(
                projection=projection, payloads=payloads, writer=extractive_writer
            )
        except SynthesisContractViolation:
            # Research insufficiency is an honest non-approval, not corruption.
            draft = None
            candidate_status = "mechanically_rejected"

        if draft is not None:
            draft_digest = canonical_digest(draft.to_dict())
            audit = audit_final_answer(
                draft=draft,
                projection=projection,
                payloads=payloads,
                judge=None,
                repairer=None,
            )
            audit_projection = _audit_projection(audit, draft)
            verdict = str(getattr(audit, "verdict", ""))
            approval = str(getattr(audit, "approval_status", ""))
            question_coverage = str(getattr(audit, "question_coverage", ""))
            evidence_grounding = str(getattr(audit, "evidence_grounding", ""))
        else:
            audit_projection = {
                "verdict": "fail",
                "approval_status": "audited-but-not-approved",
                "question_coverage": "unverified",
                "evidence_grounding": "unverified",
                "issue_codes": ["synthesis_contract_violation"],
                "unanswered_aspects": [],
                "contradiction_gap_count": 0,
                "citation_support_gap_count": 0,
                "repair_used": False,
            }
            verdict = "fail"
            approval = "audited-but-not-approved"
            question_coverage = "unverified"
            evidence_grounding = "unverified"

        result = {
            "schema_version": AUDIT_RESULT_SCHEMA,
            "child_run_id": child_run_id,
            "child_status": str(child.status or ""),
            "deep_terminal_sha256": self._deep_terminal_digest_for(parent_turn_id, thread_id),
            "child_terminal_sha256": self._child_terminal_digest(parent_turn_id),
            "source_run_sha256": digest,
            "research_state_sha256": state_digest,
            "projection_sha256": projection_digest,
            "draft_sha256": draft_digest,
            "audit_sha256": canonical_digest(audit_projection),
            "candidate_status": candidate_status,
            "audit_verdict": verdict,
            "approval_status": approval,
            "question_coverage": question_coverage,
            "evidence_grounding": evidence_grounding,
            "issue_codes": list(audit_projection["issue_codes"]),
            "judge_authority": "none",
            "publication_authority": False,
            "audited_at": self.clock().astimezone(timezone.utc).isoformat(),
        }
        try:
            publication = self.publication.finalize_audited(
                parent_turn_id=parent_turn_id,
                thread_id=thread_id,
                audit_source_digest=digest,
                result=result,
            )
        except DeepFinalizationError as exc:
            return self._block(parent_turn_id, thread_id, exc.reason)
        # First terminal wins: if a concurrent block committed first, report what is durable.
        status = str(publication.get("dispatch_status") or "")
        if status != AUDITED:
            return DeepPublicationOutcome(
                status="blocked",
                parent_turn_id=parent_turn_id,
                child_run_id=child_run_id,
                reason=str(publication.get("reason") or ""),
                result=None,
            )
        return DeepPublicationOutcome(
            status="audited",
            parent_turn_id=parent_turn_id,
            child_run_id=child_run_id,
            reason="",
            result=publication.get("result")
            if isinstance(publication.get("result"), dict)
            else result,
        )

    def _child_row(self, child_run_id: str) -> Any:
        with self.repository.database.connect() as connection:
            return connection.execute(
                "SELECT * FROM web_lookup_runs WHERE id = ?", (child_run_id,)
            ).fetchone()

    def _child_terminal_digest(self, parent_turn_id: str) -> str:
        """The digest Deep-3 recorded for the child terminal, read from the parent terminal."""

        parent = self.repository.get_chat_turn(parent_turn_id)
        terminal = (parent.rag_snapshot or {}).get("deep_terminal") if parent else None
        if not isinstance(terminal, dict):
            return ""
        result = terminal.get("result")
        if not isinstance(result, dict):
            return ""
        return str(result.get("child_terminal_sha256") or "")

    def _deep_terminal_digest_for(self, parent_turn_id: str, thread_id: str) -> str:
        from src.repositories.deep_publication_repository import deep_terminal_digest

        read = self.publication.read(parent_turn_id, thread_id)
        if read.present and isinstance(read.publication, dict):
            recorded = str((read.publication.get("source") or {}).get("deep_terminal_sha256") or "")
            if recorded:
                return recorded
        parent = self.repository.get_chat_turn(parent_turn_id)
        terminal = (parent.rag_snapshot or {}).get("deep_terminal") if parent else None
        return deep_terminal_digest(terminal) if isinstance(terminal, dict) else ""

    def _block(
        self, parent_turn_id: str, thread_id: str, reason: str
    ) -> DeepPublicationOutcome:
        try:
            publication = self.publication.block(
                parent_turn_id=parent_turn_id, thread_id=thread_id, reason=reason
            )
        except DeepFinalizationError as exc:
            return self._outcome("blocked", parent_turn_id, "", exc.reason)
        status = str(publication.get("dispatch_status") or "")
        result = publication.get("result")
        return DeepPublicationOutcome(
            status="audited" if status == AUDITED else "blocked",
            parent_turn_id=parent_turn_id,
            child_run_id=str((publication.get("owner") or {}).get("child_run_id") or ""),
            reason=str(publication.get("reason") or reason),
            result=result if isinstance(result, dict) else None,
        )

    @staticmethod
    def _outcome(
        status: str, parent_turn_id: str, child_run_id: str, reason: str
    ) -> DeepPublicationOutcome:
        return DeepPublicationOutcome(
            status=status,  # type: ignore[arg-type]
            parent_turn_id=parent_turn_id,
            child_run_id=child_run_id,
            reason=reason,
            result=None,
        )
