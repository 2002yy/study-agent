"""Runtime domain entities for the Architecture V2 persistence layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from src.domain.answer_claims import normalize_answer_claim_snapshot_for_turn
from src.domain.answer_validation import (
    normalize_answer_validation_audit_for_turn,
)
from src.domain.evidence import (
    MIN_VERIFIED_CITATION_CONFIDENCE,
    ClaimEvidenceLinkV1,
    build_evidence_snapshot,
)

# G14 decision 1: first-version temporary attachment types. Text types reuse
# the long-term loader; image types are stored (and only described when the
# vision switch is explicitly enabled).
SESSION_ATTACHMENT_EXTENSIONS = frozenset(
    {".md", ".markdown", ".txt", ".csv", ".pdf", ".docx"}
    | {".jpg", ".jpeg", ".png", ".gif", ".webp"}
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ChatThread:
    id: str = field(default_factory=lambda: new_id("chat"))
    status: str = "active"
    settings_snapshot: dict[str, Any] = field(default_factory=dict)
    learning_state: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    archived_at: str | None = None
    export_path: str = ""
    active_operation_id: str | None = None
    active_operation_started_at: str | None = None
    archive_operation_id: str | None = None
    archive_started_at: str | None = None
    # G12 decision 15: persisted "archive once this operation settles" marker.
    archive_after_cancel_operation_id: str | None = None
    version: int = 1


@dataclass(frozen=True)
class ChatTurn:
    id: str = field(default_factory=lambda: new_id("turn"))
    thread_id: str = ""
    user_message: str = ""
    assistant_message: str = ""
    status: str = "pending"
    role: str = ""
    mode: str = ""
    model: str = ""
    route_snapshot: dict[str, Any] = field(default_factory=dict)
    rag_snapshot: dict[str, Any] = field(default_factory=dict)
    pedagogy_snapshot: dict[str, Any] = field(default_factory=dict)
    # Message-level attachment identity bound by the server (id + content_hash),
    # never the raw client strings.
    attachment_refs: tuple[dict[str, Any], ...] = ()
    parent_turn_id: str | None = None
    operation_id: str | None = None
    conversation_instruction: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    cancel_requested_at: str | None = None
    cancel_stage: str | None = None
    cancel_reason: str | None = None

    def __post_init__(self) -> None:
        # ChatTurn owns versioned projections derived from already persisted raw
        # snapshots. New turns persist them inside rag_snapshot; legacy rows gain
        # the same projections in memory without requiring a schema migration.
        if not (self.rag_snapshot or self.pedagogy_snapshot):
            return
        base_evidence = self._project_evidence_snapshot()
        known_evidence_ids = tuple(
            str(ref.get("id", ""))
            for ref in base_evidence.get("refs", ())
            if isinstance(ref, dict) and str(ref.get("id", "")).strip()
        )
        claim_snapshot = normalize_answer_claim_snapshot_for_turn(
            raw_snapshot=self.rag_snapshot.get("answer_claim_snapshot"),
            assistant_message=self.assistant_message,
            turn_status=self.status,
            known_evidence_ids=known_evidence_ids,
        )
        self.rag_snapshot["answer_claim_snapshot"] = claim_snapshot.to_dict()
        # Server-owned answer-stage model audit: rebuilt against the assistant
        # message actually kept, so a client-shaped or stale audit never
        # survives with forged fields.
        audit = normalize_answer_validation_audit_for_turn(
            raw=self.rag_snapshot.get("answer_validation_audit"),
            assistant_message=self.assistant_message,
        )
        if audit is None:
            self.rag_snapshot.pop("answer_validation_audit", None)
        else:
            self.rag_snapshot["answer_validation_audit"] = audit
        # A source is a citation only when the answer that was actually kept
        # passed publication and links it. Selection is not citation.
        citation_source_ids = {
            str(row.get("evidence_id") or "").strip()
            for row in self.rag_snapshot.get("research_evidence_refs") or ()
            if isinstance(row, dict)
        }
        cited = _verified_citation_links(
            claim_snapshot,
            audit,
            (evidence_id for evidence_id in known_evidence_ids if evidence_id in citation_source_ids),
        )
        self.rag_snapshot["citation_links"] = [link.to_dict() for link in cited]
        self.rag_snapshot["evidence_snapshot"] = self._project_evidence_snapshot(
            claim_links=claim_snapshot.claim_links,
            cited_evidence_ids=tuple(link.evidence_id for link in cited),
        )

    @property
    def answer_claim_snapshot(self) -> dict[str, Any]:
        existing = self.rag_snapshot.get("answer_claim_snapshot")
        if isinstance(existing, dict):
            return dict(existing)
        base_evidence = self._project_evidence_snapshot()
        known_evidence_ids = tuple(
            str(ref.get("id", ""))
            for ref in base_evidence.get("refs", ())
            if isinstance(ref, dict) and str(ref.get("id", "")).strip()
        )
        return normalize_answer_claim_snapshot_for_turn(
            raw_snapshot={},
            assistant_message=self.assistant_message,
            turn_status=self.status,
            known_evidence_ids=known_evidence_ids,
        ).to_dict()

    @property
    def evidence_snapshot(self) -> dict[str, Any]:
        existing = self.rag_snapshot.get("evidence_snapshot")
        if isinstance(existing, dict):
            return dict(existing)
        claim_links = _claim_links_from_snapshot(self.answer_claim_snapshot)
        return self._project_evidence_snapshot(claim_links=claim_links)

    def _project_evidence_snapshot(
        self,
        *,
        claim_links: Iterable[ClaimEvidenceLinkV1] = (),
        cited_evidence_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        raw_units = self.pedagogy_snapshot.get("evidence_units") or ()
        units = (
            tuple(unit for unit in raw_units if isinstance(unit, dict))
            if isinstance(raw_units, (list, tuple))
            else ()
        )
        raw_ids = self.pedagogy_snapshot.get("evidence_ids") or ()
        evidence_ids = (
            tuple(str(value) for value in raw_ids)
            if isinstance(raw_ids, (list, tuple))
            else ()
        )
        return build_evidence_snapshot(
            rag=self.rag_snapshot,
            disclosed_units=units,
            disclosure_policy=str(
                self.pedagogy_snapshot.get("evidence_disclosure") or "none"
            ),
            pedagogy_evidence_ids=evidence_ids,
            claim_links=claim_links,
            cited_evidence_ids=cited_evidence_ids,
        ).to_dict()


@dataclass(frozen=True)
class GroupThread:
    id: str = field(default_factory=lambda: new_id("group"))
    status: str = "active"
    title: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    archived_at: str | None = None
    settings_snapshot: dict[str, Any] = field(default_factory=dict)
    active_operation_id: str | None = None
    active_operation_started_at: str | None = None
    unread_count: int = 0
    last_read_message_id: str | None = None
    archive_operation_id: str | None = None
    archive_started_at: str | None = None
    export_path: str = ""
    version: int = 1


@dataclass(frozen=True)
class GroupMessage:
    id: str = field(default_factory=lambda: new_id("group_msg"))
    thread_id: str = ""
    speaker: str = ""
    content: str = ""
    status: str = "committed"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    message_type: str = "chat"
    operation_id: str | None = None
    error: str = ""


@dataclass(frozen=True)
class NewsRun:
    id: str = field(default_factory=lambda: new_id("news"))
    query: str = ""
    stage: str = "created"
    status: str = "running"
    safe_mode: bool = False
    items: list[dict[str, Any]] = field(default_factory=list)
    digest: str = ""
    source_block: str = ""
    article_coverage: dict[str, Any] = field(default_factory=dict)
    discussion: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    group_thread_id: str | None = None
    active_operation_id: str | None = None
    active_operation_started_at: str | None = None
    stage_started_at: str | None = None
    completed_at: str | None = None
    version: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class WebLookupRun:
    id: str = field(default_factory=lambda: new_id("web_lookup"))
    query: str = ""
    stage: str = "created"
    status: str = "running"
    research_context: dict[str, Any] = field(default_factory=dict)
    query_attempts: list[dict[str, Any]] = field(default_factory=list)
    selected_sources: list[dict[str, Any]] = field(default_factory=list)
    rejected_sources: list[dict[str, Any]] = field(default_factory=list)
    provider_status: str = ""
    stop_reason: str = ""
    answer_confidence: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    source_block: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    max_items: int = 8
    active_operation_id: str | None = None
    active_operation_started_at: str | None = None
    stage_started_at: str | None = None
    cancel_requested_at: str | None = None
    owner_thread_id: str | None = None
    parent_run_id: str | None = None
    root_run_id: str | None = None
    lineage_depth: int = 0
    create_request_id: str | None = None
    lineage_summary: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    completed_at: str | None = None


@dataclass(frozen=True)
class MemoryRun:
    id: str = field(default_factory=lambda: new_id("memory"))
    status: str = "previewed"
    updates: list[dict[str, Any]] = field(default_factory=list)
    updates_hash: str = ""
    preview: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    active_operation_id: str | None = None
    active_operation_started_at: str | None = None
    previewed_at: str | None = None
    completed_at: str | None = None
    version: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class RagRun:
    id: str = field(default_factory=lambda: new_id("rag"))
    kind: str = "query"
    status: str = "running"
    request: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    index_version: int = 0
    version: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    completed_at: str | None = None


@dataclass(frozen=True)
class ToolRun:
    id: str = field(default_factory=lambda: new_id("tool"))
    tool_name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    args_hash: str = ""
    status: str = "previewed"
    preview: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    elapsed_ms: int = 0
    active_operation_id: str | None = None
    active_operation_started_at: str | None = None
    previewed_at: str | None = None
    completed_at: str | None = None
    version: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


# G14 decision 1/12: per-file lifecycle states for temporary session
# attachments. Only `ready` chunks are retrievable; `failed` files never
# contribute fragments to any question context.
SESSION_ATTACHMENT_STATUSES = frozenset(
    {"parsing", "chunking", "indexing", "ready", "failed"}
)


def is_session_attachment_kind(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in SESSION_ATTACHMENT_EXTENSIONS


@dataclass(frozen=True)
class SessionAttachment:
    id: str = field(default_factory=lambda: new_id("att"))
    thread_id: str = ""
    filename: str = ""
    content_hash: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    storage_path: str = ""
    status: str = "parsing"
    stage_error: str = ""
    stage_history: tuple[dict[str, Any], ...] = ()
    retry_count: int = 0
    promoted_rag_run_id: str = ""
    external_calls: tuple[dict[str, Any], ...] = ()
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    version: int = 1


@dataclass(frozen=True)
class OperationRecord:
    id: str = field(default_factory=lambda: new_id("op"))
    scope: str = ""
    owner_id: str | None = None
    status: str = "running"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


def _verified_citation_links(
    claim_snapshot: Any,
    audit: dict[str, Any] | None,
    known_evidence_ids: Iterable[str],
) -> tuple[ClaimEvidenceLinkV1, ...]:
    """The links the published answer may show as verified citations.

    Every condition is server-owned state, never a model claim:

    * the claim snapshot is ``validated`` - normalization already rejected it if
      its answer hash differs from the published message, which is what happens
      when the consistency gate replaced the answer;
    * the publication audit exists, bound the candidate (``passed``), and the
      learner answer hash still equals the candidate hash;
    * the link is positive support at or above the binder's strong bar, and the
      evidence id is a real ref of this turn.

    Selection alone never qualifies: a source can be selected and the answer
    still be refused or published without citing it.
    """

    if audit is None:
        return ()
    if str(getattr(claim_snapshot, "status", "")) != "validated":
        return ()
    phases = audit.get("phases") if isinstance(audit.get("phases"), dict) else {}
    binding = phases.get("answer_claim_binding") if isinstance(phases, dict) else None
    if not isinstance(binding, dict) or str(binding.get("outcome") or "") != "passed":
        return ()
    candidate = str(audit.get("candidate_answer_sha256") or "")
    learner = str(audit.get("learner_answer_sha256") or "")
    if not candidate or candidate != learner:
        return ()
    known = {str(evidence_id) for evidence_id in known_evidence_ids}
    cited: list[ClaimEvidenceLinkV1] = []
    for link in getattr(claim_snapshot, "claim_links", ()) or ():
        if link.support_type not in {"direct_support", "indirect_support"}:
            continue
        if float(link.confidence) < MIN_VERIFIED_CITATION_CONFIDENCE:
            continue
        if link.evidence_id not in known:
            continue
        # Retain every claim→evidence link. The snapshot normalizer already
        # rejects duplicate link tuples; ref status below only needs an id set.
        cited.append(link)
    return tuple(cited)


def _claim_links_from_snapshot(snapshot: dict[str, Any]) -> tuple[ClaimEvidenceLinkV1, ...]:
    raw_links = snapshot.get("claim_links")
    if not isinstance(raw_links, list):
        return ()
    links: list[ClaimEvidenceLinkV1] = []
    for raw in raw_links:
        if not isinstance(raw, dict):
            continue
        try:
            links.append(
                ClaimEvidenceLinkV1(
                    claim_id=str(raw.get("claim_id", "")),
                    evidence_id=str(raw.get("evidence_id", "")),
                    support_type=str(raw.get("support_type", "")),
                    confidence=float(raw.get("confidence", 0)),
                )
            )
        except (TypeError, ValueError):
            continue
    return tuple(links)
