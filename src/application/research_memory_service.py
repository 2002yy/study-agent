"""Explicit publication and read-only recall of historical research leads."""

from __future__ import annotations

from datetime import date
from typing import Any

from src.domain.runtime_entities import new_id, utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.research_memory_repository import ResearchMemoryRepository
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.claim_conflict_assessment import assess_claim_conflict
from src.web.research.claim_evidence_assessment import assess_claim_evidence
from src.web.research.persistent_memory import (
    MemoryClaim,
    MemoryEvidenceRef,
    RecallCandidate,
    ResearchMemoryRevision,
    known_research_evidence_ids,
    normalized_topic,
    state_digest,
)
from src.web.research.research_brief_projection import build_research_brief_projection
from src.web.research.state import load_claim_engine_state


class ResearchMemoryService:
    """Opt-in only. No runtime call site injects these leads into evidence or answers."""

    def __init__(self, database: RuntimeDatabase):
        self.runs = WebLookupRepository(database)
        self.memory = ResearchMemoryRepository(database)

    def publish(
        self, source_run_id: str, *, expected_cursor_version: int,
        prior_revision_ids: tuple[str, ...] = (),
    ) -> ResearchMemoryRevision:
        run = self.runs.get(source_run_id)
        if run is None or not run.owner_thread_id:
            raise ValueError("research memory requires a server-owned thread")
        if run.status not in {"completed", "partial"} or run.active_operation_id:
            raise ValueError("research memory requires a terminal run")
        loaded = load_claim_engine_state(
            run.research_context,
            known_evidence_ids=known_research_evidence_ids(run),
        )
        if not loaded.available or loaded.effective_mode != "active" or loaded.state is None:
            raise ValueError("research memory requires a validated active state")
        state = loaded.state
        if not state.questions or not run.query.strip():
            raise ValueError("research memory requires a question")
        question = run.query
        projection = build_research_brief_projection(state)
        assessments = {claim.id: assess_claim_evidence(state, claim) for claim in state.claims}
        conflicts = {claim.id: assess_claim_conflict(state, claim) for claim in state.claims}
        evidence_by_id = {item.evidence_id: item for item in state.evidence}
        used_ids: set[str] = set()
        claims: list[MemoryClaim] = []
        for claim in state.claims:
            assessment = assessments[claim.id]
            conflict = conflicts[claim.id]
            used_ids.update((*assessment.supporting_evidence, *assessment.contradicting_evidence))
            claims.append(MemoryClaim(
                claim_id=claim.id,
                statement=claim.text,
                criticality=claim.priority,
                status="unresolved",
                semantic_adequacy=assessment.semantic_adequacy,
                conflict_status=conflict.status,
                preferred_side=conflict.preferred_side,
                required_units=tuple(item.unit_id for item in assessment.required_units),
                covered_units=tuple(item.unit_id for item in assessment.covered_units),
                missing_units=tuple(item.unit_id for item in assessment.missing_units),
                support_refs=tuple(f"{run.id}:{item}" for item in assessment.supporting_evidence),
                contradict_refs=tuple(f"{run.id}:{item}" for item in assessment.contradicting_evidence),
                max_age_days=claim.evidence_requirement.max_age_days,
                requires_dated_evidence=claim.evidence_requirement.requires_dated_evidence,
            ))
        refs: list[MemoryEvidenceRef] = []
        for evidence_id in sorted(used_ids):
            item = evidence_by_id[evidence_id]
            unit = item.units[0] if item.units else None
            refs.append(MemoryEvidenceRef(
                source_run_id=run.id,
                evidence_id=f"{run.id}:{evidence_id}",
                source=_bounded(unit.source if unit else "", 500),
                locator=_bounded(item.locator, 500),
                modality=unit.source_type if unit else "unknown",
                page=unit.page if unit else None,
                region=_bounded(unit.region if unit else "", 200),
                published_at=item.published_at,
                provenance=_bounded(unit.provenance if unit else "", 500),
            ))
        gaps = [
            f"{item.claim_id}:{item.gap_type}"
            for item in state.gaps if item.state != "resolved"
        ]
        gaps += [
            f"{item.claim_id}:conflict"
            for item in state.conflict_gaps if item.state != "resolved"
        ]
        if len(claims) > 64 or len(refs) > 256 or len(gaps) > 64:
            raise ValueError("research memory record exceeds bounds")
        revision = ResearchMemoryRevision(
            revision_id=new_id("research_memory"),
            owner_thread_id=run.owner_thread_id,
            topic=normalized_topic(question),
            source_run_id=run.id,
            source_run_version=run.version,
            state_digest=state_digest(state),
            generated_at=utc_now(),
            question=question,
            claims=tuple(claims),
            evidence_refs=tuple(refs),
            unresolved_gaps=tuple(gaps),
            limitations=tuple(projection.limitations[:64]),
            prior_revision_ids=prior_revision_ids,
        )
        return self.memory.publish(revision, expected_cursor_version=expected_cursor_version)

    def recall(
        self, owner_thread_id: str, question: str, *, today: date | None = None,
    ) -> tuple[RecallCandidate, ...]:
        return self.memory.recall(owner_thread_id, question, today=today or date.today())


def _bounded(value: Any, limit: int) -> str:
    return str(value or "")[:limit]
