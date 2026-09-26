"""Versioned, deterministic contracts for the shared research quality engine.

This module owns no search, read, persistence, prompt, or answer behavior. It
only validates a bounded research-state projection. Evidence identity remains
server-owned by :mod:`src.domain.evidence`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import isfinite
from typing import Any, Iterable, Literal, Mapping

from src.domain.evidence import (
    ClaimEvidenceLinkV1,
    EvidenceLifecycleStatus,
)
from src.web.research.evidence_units import (
    EvidenceUnit,
    RequiredUnit,
    parse_evidence_units,
    parse_required_units,
)

RESEARCH_STATE_SCHEMA_VERSION = "research-state-v1"

ResearchMode = Literal["shadow", "active"]
ResearchClaimKind = Literal[
    "research_question",
    "hypothesis",
    "factual",
    "analytical",
]
ResearchClaimPriority = Literal["critical", "major", "context"]
ResearchClaimState = Literal[
    "pending",
    "searching",
    "satisfied",
    "partially_satisfied",
    "unresolved",
    "unavailable",
    "contested",
]
ClaimEvidenceRelation = Literal[
    "supports",
    "contradicts",
    "qualifies",
    "background",
    "lead",
]
GapState = Literal["open", "searching", "resolved", "unavailable"]
ResearchEvidenceExtractionStatus = Literal[
    "not_attempted",
    "eligible",
    "read_failed",
    "extractor_failed",
]
ResearchTraceEventType = Literal[
    "claim_created",
    "gap_created",
    "query_planned",
    "search_completed",
    "candidate_ranked",
    "read_completed",
    "evidence_extracted",
    "claim_linked",
    "gate_evaluated",
    "stop_blocked",
    "stop_allowed",
    "budget_changed",
    "failure_recorded",
]

_MODES = {"shadow", "active"}
_CLAIM_KINDS = {"research_question", "hypothesis", "factual", "analytical"}
_CLAIM_PRIORITIES = {"critical", "major", "context"}
_CLAIM_STATES = {
    "pending",
    "searching",
    "satisfied",
    "partially_satisfied",
    "unresolved",
    "unavailable",
    "contested",
}
_EVIDENCE_RELATIONS = {
    "supports",
    "contradicts",
    "qualifies",
    "background",
    "lead",
}
_GAP_STATES = {"open", "searching", "resolved", "unavailable"}
_EVIDENCE_LIFECYCLE_STATES = {"candidate", "read", "selected", "rejected"}
_EXTRACTION_STATES = {"not_attempted", "eligible", "read_failed", "extractor_failed"}
_SOURCE_ROLES = {
    "primary",
    "authoritative_secondary",
    "independent_secondary",
    "community",
    "aggregator",
}
_TRACE_EVENT_TYPES = {
    "claim_created",
    "gap_created",
    "query_planned",
    "search_completed",
    "candidate_ranked",
    "read_completed",
    "evidence_extracted",
    "claim_linked",
    "gate_evaluated",
    "stop_blocked",
    "stop_allowed",
    "budget_changed",
    "failure_recorded",
}


@dataclass(frozen=True)
class ResearchQuestion:
    id: str
    question_surface: str
    priority: ResearchClaimPriority = "major"
    state: ResearchClaimState = "unresolved"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question_surface": self.question_surface,
            "priority": self.priority,
            "state": self.state,
        }


@dataclass(frozen=True)
class EvidenceRequirement:
    source_roles: tuple[str, ...] = ()
    min_independent_sources: int = 1
    requires_primary_source: bool = False
    requires_successful_read: bool = True
    max_age_days: int | None = None
    requires_dated_evidence: bool = False
    #: Content units the claim needs; declared claim-side, never inferred.
    required_units: tuple[RequiredUnit, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_roles": list(self.source_roles),
            "min_independent_sources": self.min_independent_sources,
            "requires_primary_source": self.requires_primary_source,
            "requires_successful_read": self.requires_successful_read,
            "max_age_days": self.max_age_days,
            "requires_dated_evidence": self.requires_dated_evidence,
            "required_units": [unit.to_dict() for unit in self.required_units],
        }


@dataclass(frozen=True)
class ResearchClaim:
    id: str
    question_id: str
    text: str
    kind: ResearchClaimKind
    priority: ResearchClaimPriority
    state: ResearchClaimState
    evidence_requirement: EvidenceRequirement
    parent_id: str = ""
    alias_to: str = ""
    created_by: str = "system"
    created_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question_id": self.question_id,
            "text": self.text,
            "kind": self.kind,
            "priority": self.priority,
            "state": self.state,
            "evidence_requirement": self.evidence_requirement.to_dict(),
            "parent_id": self.parent_id,
            "alias_to": self.alias_to,
            "created_by": self.created_by,
            "created_reason": self.created_reason,
        }


@dataclass(frozen=True)
class ResearchEvidence:
    """Bounded metadata referencing server-owned evidence, never a page dump."""

    evidence_id: str
    locator: str = ""
    anchored_spans: tuple[str, ...] = ()
    lifecycle_status: EvidenceLifecycleStatus = "candidate"
    extraction_status: ResearchEvidenceExtractionStatus = "not_attempted"
    published_at: str = ""
    #: Units this evidence actually covers (text or visual), locator-backed.
    units: tuple[EvidenceUnit, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "locator": self.locator,
            "anchored_spans": list(self.anchored_spans),
            "lifecycle_status": self.lifecycle_status,
            "extraction_status": self.extraction_status,
            "published_at": self.published_at,
            "units": [unit.to_dict() for unit in self.units],
        }


@dataclass(frozen=True)
class ResearchClaimEvidenceLink:
    """Research metadata composed around the canonical evidence-link value."""

    link: ClaimEvidenceLinkV1
    source_role: str = ""
    source_cluster_id: str = ""
    locator: str = ""
    caveats: tuple[str, ...] = ()

    @property
    def claim_id(self) -> str:
        return self.link.claim_id

    @property
    def evidence_id(self) -> str:
        return self.link.evidence_id

    @property
    def relation(self) -> str:
        return self.link.support_type

    @property
    def strength(self) -> float:
        return self.link.confidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "evidence_id": self.evidence_id,
            "relation": self.relation,
            "strength": self.strength,
            "source_role": self.source_role,
            "source_cluster_id": self.source_cluster_id,
            "locator": self.locator,
            "caveats": list(self.caveats),
        }


@dataclass(frozen=True)
class EvidenceGap:
    id: str
    claim_id: str
    gap_type: str
    desired_source_role: str = ""
    priority: ResearchClaimPriority = "major"
    attempt_count: int = 0
    state: GapState = "open"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "claim_id": self.claim_id,
            "gap_type": self.gap_type,
            "desired_source_role": self.desired_source_role,
            "priority": self.priority,
            "attempt_count": self.attempt_count,
            "state": self.state,
        }


@dataclass(frozen=True)
class ConflictGap:
    id: str
    claim_id: str
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    state: GapState = "open"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "claim_id": self.claim_id,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "contradicting_evidence_ids": list(self.contradicting_evidence_ids),
            "state": self.state,
        }


@dataclass(frozen=True)
class EvidenceCluster:
    id: str
    evidence_ids: tuple[str, ...]
    source_role: str = ""
    independence_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "evidence_ids": list(self.evidence_ids),
            "source_role": self.source_role,
            "independence_key": self.independence_key,
        }


@dataclass(frozen=True)
class ResearchBudget:
    max_candidates: int
    max_reads: int
    soft_timeout_seconds: float
    hard_timeout_seconds: float
    max_total_chars: int = 0
    candidates_used: int = 0
    reads_used: int = 0
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_candidates": self.max_candidates,
            "max_reads": self.max_reads,
            "soft_timeout_seconds": self.soft_timeout_seconds,
            "hard_timeout_seconds": self.hard_timeout_seconds,
            "max_total_chars": self.max_total_chars,
            "candidates_used": self.candidates_used,
            "reads_used": self.reads_used,
            "elapsed_seconds": self.elapsed_seconds,
        }


@dataclass(frozen=True)
class ResearchTraceEvent:
    sequence: int
    timestamp: str
    run_id: str
    event_type: ResearchTraceEventType
    reason: str
    claim_id: str = ""
    gap_id: str = ""
    evidence_id: str = ""
    budget_before: ResearchBudget | None = None
    budget_after: ResearchBudget | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "reason": self.reason,
            "claim_id": self.claim_id,
            "gap_id": self.gap_id,
            "evidence_id": self.evidence_id,
            "budget_before": (
                self.budget_before.to_dict() if self.budget_before else None
            ),
            "budget_after": self.budget_after.to_dict() if self.budget_after else None,
        }


@dataclass(frozen=True)
class ResearchBrief:
    claim_ids: tuple[str, ...] = ()
    unresolved_claim_ids: tuple[str, ...] = ()
    conflict_gap_ids: tuple[str, ...] = ()
    outline: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_ids": list(self.claim_ids),
            "unresolved_claim_ids": list(self.unresolved_claim_ids),
            "conflict_gap_ids": list(self.conflict_gap_ids),
            "outline": list(self.outline),
        }


@dataclass(frozen=True)
class ResearchState:
    mode: ResearchMode
    questions: tuple[ResearchQuestion, ...]
    claims: tuple[ResearchClaim, ...]
    evidence: tuple[ResearchEvidence, ...]
    evidence_links: tuple[ResearchClaimEvidenceLink, ...]
    source_clusters: tuple[EvidenceCluster, ...]
    gaps: tuple[EvidenceGap, ...]
    conflict_gaps: tuple[ConflictGap, ...]
    budget: ResearchBudget
    trace: tuple[ResearchTraceEvent, ...] = ()
    brief: ResearchBrief | None = None
    reference_date: str = ""
    schema_version: str = RESEARCH_STATE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "questions": [item.to_dict() for item in self.questions],
            "claims": [item.to_dict() for item in self.claims],
            "evidence": [item.to_dict() for item in self.evidence],
            "evidence_links": [item.to_dict() for item in self.evidence_links],
            "source_clusters": [item.to_dict() for item in self.source_clusters],
            "gaps": [item.to_dict() for item in self.gaps],
            "conflict_gaps": [item.to_dict() for item in self.conflict_gaps],
            "budget": self.budget.to_dict(),
            "trace": [item.to_dict() for item in self.trace],
            "brief": self.brief.to_dict() if self.brief else None,
            "reference_date": self.reference_date,
        }

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, Any],
        *,
        known_evidence_ids: Iterable[str],
    ) -> ResearchState:
        data = _mapping(raw, "research state")
        _only_keys(
            data,
            {
                "schema_version",
                "mode",
                "questions",
                "claims",
                "evidence",
                "evidence_links",
                "source_clusters",
                "gaps",
                "conflict_gaps",
                "budget",
                "trace",
                "brief",
                "reference_date",
            },
            "research state",
        )
        if data.get("schema_version") != RESEARCH_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported research state schema_version")
        brief_raw = data.get("brief")
        return build_research_state(
            mode=_enum(data.get("mode"), _MODES, "research mode"),
            questions=[_parse_question(item) for item in _sequence(data, "questions")],
            claims=[_parse_claim(item) for item in _sequence(data, "claims")],
            evidence=[_parse_evidence(item) for item in _sequence(data, "evidence")],
            evidence_links=[
                _parse_evidence_link(item)
                for item in _sequence(data, "evidence_links")
            ],
            source_clusters=[
                _parse_cluster(item) for item in _sequence(data, "source_clusters")
            ],
            gaps=[_parse_gap(item) for item in _sequence(data, "gaps")],
            conflict_gaps=[
                _parse_conflict_gap(item)
                for item in _sequence(data, "conflict_gaps")
            ],
            budget=_parse_budget(data.get("budget")),
            trace=[_parse_trace(item) for item in _sequence(data, "trace")],
            brief=_parse_brief(brief_raw) if brief_raw is not None else None,
            reference_date=_optional_date(data.get("reference_date"), "reference date"),
            known_evidence_ids=known_evidence_ids,
        )


def build_research_state(
    *,
    mode: ResearchMode,
    questions: Iterable[ResearchQuestion],
    claims: Iterable[ResearchClaim],
    evidence: Iterable[ResearchEvidence],
    evidence_links: Iterable[ResearchClaimEvidenceLink],
    source_clusters: Iterable[EvidenceCluster],
    gaps: Iterable[EvidenceGap],
    conflict_gaps: Iterable[ConflictGap],
    budget: ResearchBudget,
    known_evidence_ids: Iterable[str],
    trace: Iterable[ResearchTraceEvent] = (),
    brief: ResearchBrief | None = None,
    reference_date: str = "",
) -> ResearchState:
    """Validate and deterministically order a research-state projection."""

    checked_mode = _enum(mode, _MODES, "research mode")
    checked_budget = _validate_budget(budget)
    allowed_evidence_ids = {_id(value, "known evidence id") for value in known_evidence_ids}

    checked_questions = tuple(sorted((_validate_question(v) for v in questions), key=_by_id))
    _unique_ids(checked_questions, "question")
    question_ids = {item.id for item in checked_questions}

    checked_claims = tuple(sorted((_validate_claim(v) for v in claims), key=_by_id))
    _unique_ids(checked_claims, "claim")
    claim_ids = {item.id for item in checked_claims}
    for claim in checked_claims:
        if claim.question_id not in question_ids:
            raise ValueError(f"unknown question id for claim {claim.id}: {claim.question_id}")
        for name, target in (("parent_id", claim.parent_id), ("alias_to", claim.alias_to)):
            if target and target not in claim_ids:
                raise ValueError(f"unknown {name} for claim {claim.id}: {target}")
            if target == claim.id:
                raise ValueError(f"claim {claim.id} cannot reference itself as {name}")

    checked_evidence = tuple(
        sorted((_validate_evidence(v) for v in evidence), key=lambda item: item.evidence_id)
    )
    _unique_values((item.evidence_id for item in checked_evidence), "research evidence id")
    for evidence_item in checked_evidence:
        if evidence_item.evidence_id not in allowed_evidence_ids:
            raise ValueError(
                f"unknown server-owned evidence id: {evidence_item.evidence_id}"
            )

    checked_clusters = tuple(
        sorted((_validate_cluster(v) for v in source_clusters), key=_by_id)
    )
    _unique_ids(checked_clusters, "evidence cluster")
    cluster_ids = {item.id for item in checked_clusters}
    for cluster in checked_clusters:
        _require_known_evidence(cluster.evidence_ids, allowed_evidence_ids)

    checked_links = tuple(
        sorted(
            (_validate_evidence_link(v) for v in evidence_links),
            key=lambda item: (item.claim_id, item.evidence_id, item.relation),
        )
    )
    link_keys: set[tuple[str, str, str]] = set()
    relations_by_claim_evidence: dict[tuple[str, str], set[str]] = {}
    for link_item in checked_links:
        if link_item.claim_id not in claim_ids:
            raise ValueError(f"unknown claim id in evidence link: {link_item.claim_id}")
        if link_item.evidence_id not in allowed_evidence_ids:
            raise ValueError(f"unknown evidence id in claim link: {link_item.evidence_id}")
        if link_item.source_cluster_id and link_item.source_cluster_id not in cluster_ids:
            raise ValueError(f"unknown source cluster id: {link_item.source_cluster_id}")
        key = (link_item.claim_id, link_item.evidence_id, link_item.relation)
        if key in link_keys:
            raise ValueError("duplicate research claim evidence link")
        link_keys.add(key)
        relations_by_claim_evidence.setdefault(
            (link_item.claim_id, link_item.evidence_id), set()
        ).add(link_item.relation)

    checked_gaps = tuple(sorted((_validate_gap(v) for v in gaps), key=_by_id))
    _unique_ids(checked_gaps, "evidence gap")
    gap_ids = {item.id for item in checked_gaps}
    for gap_item in checked_gaps:
        if gap_item.claim_id not in claim_ids:
            raise ValueError(f"unknown claim id in evidence gap: {gap_item.claim_id}")

    checked_conflicts = tuple(
        sorted((_validate_conflict_gap(v) for v in conflict_gaps), key=_by_id)
    )
    _unique_ids(checked_conflicts, "conflict gap")
    conflict_ids = {item.id for item in checked_conflicts}
    for conflict_item in checked_conflicts:
        if conflict_item.claim_id not in claim_ids:
            raise ValueError(
                f"unknown claim id in conflict gap: {conflict_item.claim_id}"
            )
        _require_known_evidence(
            conflict_item.supporting_evidence_ids, allowed_evidence_ids
        )
        _require_known_evidence(
            conflict_item.contradicting_evidence_ids, allowed_evidence_ids
        )
        for evidence_id in conflict_item.supporting_evidence_ids:
            relations = relations_by_claim_evidence.get(
                (conflict_item.claim_id, evidence_id), set()
            )
            if "supports" not in relations:
                raise ValueError(
                    "conflict supporting evidence requires a supports link: "
                    f"{conflict_item.claim_id}/{evidence_id}"
                )
        for evidence_id in conflict_item.contradicting_evidence_ids:
            relations = relations_by_claim_evidence.get(
                (conflict_item.claim_id, evidence_id), set()
            )
            if "contradicts" not in relations:
                raise ValueError(
                    "conflict contradicting evidence requires a contradicts link: "
                    f"{conflict_item.claim_id}/{evidence_id}"
                )

    checked_trace = tuple(sorted((_validate_trace(v) for v in trace), key=lambda v: v.sequence))
    _unique_values((str(item.sequence) for item in checked_trace), "trace sequence")
    trace_run_ids = {item.run_id for item in checked_trace}
    if len(trace_run_ids) > 1:
        raise ValueError("research trace cannot contain multiple run ids")
    for trace_item in checked_trace:
        if trace_item.claim_id and trace_item.claim_id not in claim_ids:
            raise ValueError(f"unknown claim id in trace: {trace_item.claim_id}")
        if trace_item.gap_id and trace_item.gap_id not in gap_ids | conflict_ids:
            raise ValueError(f"unknown gap id in trace: {trace_item.gap_id}")
        if (
            trace_item.evidence_id
            and trace_item.evidence_id not in allowed_evidence_ids
        ):
            raise ValueError(f"unknown evidence id in trace: {trace_item.evidence_id}")

    checked_brief = _validate_brief(brief) if brief is not None else None
    if checked_brief is not None:
        _require_subset(checked_brief.claim_ids, claim_ids, "brief claim id")
        _require_subset(
            checked_brief.unresolved_claim_ids,
            claim_ids,
            "brief unresolved claim id",
        )
        _require_subset(
            checked_brief.conflict_gap_ids,
            conflict_ids,
            "brief conflict gap id",
        )
        claim_states = {claim.id: claim.state for claim in checked_claims}
        for claim_id in checked_brief.unresolved_claim_ids:
            if claim_states[claim_id] == "satisfied":
                raise ValueError(
                    f"satisfied claim cannot be unresolved in brief: {claim_id}"
                )

    return ResearchState(
        mode=checked_mode,
        questions=checked_questions,
        claims=checked_claims,
        evidence=checked_evidence,
        evidence_links=checked_links,
        source_clusters=checked_clusters,
        gaps=checked_gaps,
        conflict_gaps=checked_conflicts,
        budget=checked_budget,
        trace=checked_trace,
        brief=checked_brief,
        reference_date=_optional_date(reference_date, "reference date"),
    )


def _parse_question(raw: Any) -> ResearchQuestion:
    data = _mapping(raw, "research question")
    _only_keys(data, {"id", "question_surface", "priority", "state"}, "research question")
    return _validate_question(
        ResearchQuestion(
            id=_id(data.get("id"), "question id"),
            question_surface=_text(data.get("question_surface"), "question surface", 2000),
            priority=_enum(data.get("priority"), _CLAIM_PRIORITIES, "question priority"),
            state=_enum(data.get("state"), _CLAIM_STATES, "question state"),
        )
    )


def _parse_requirement(raw: Any) -> EvidenceRequirement:
    data = _mapping(raw, "evidence requirement")
    _only_keys(
        data,
        {
            "source_roles",
            "min_independent_sources",
            "requires_primary_source",
            "requires_successful_read",
            "max_age_days",
            "requires_dated_evidence",
            "required_units",
        },
        "evidence requirement",
    )
    return _validate_requirement(
        EvidenceRequirement(
            source_roles=_string_tuple(data.get("source_roles"), "source roles", max_items=12),
            min_independent_sources=_integer(
                data.get("min_independent_sources"), "min independent sources"
            ),
            requires_primary_source=_boolean(
                data.get("requires_primary_source"), "requires primary source"
            ),
            requires_successful_read=_boolean(
                data.get("requires_successful_read"), "requires successful read"
            ),
            max_age_days=_optional_non_negative_int(
                data.get("max_age_days"), "max evidence age days"
            ),
            requires_dated_evidence=_boolean(
                data.get("requires_dated_evidence", False),
                "requires dated evidence",
            ),
            required_units=parse_required_units(data.get("required_units")),
        )
    )


def _parse_claim(raw: Any) -> ResearchClaim:
    data = _mapping(raw, "research claim")
    _only_keys(
        data,
        {
            "id",
            "question_id",
            "text",
            "kind",
            "priority",
            "state",
            "evidence_requirement",
            "parent_id",
            "alias_to",
            "created_by",
            "created_reason",
        },
        "research claim",
    )
    return _validate_claim(
        ResearchClaim(
            id=_id(data.get("id"), "claim id"),
            question_id=_id(data.get("question_id"), "claim question id"),
            text=_text(data.get("text"), "claim text", 2000),
            kind=_enum(data.get("kind"), _CLAIM_KINDS, "claim kind"),
            priority=_enum(data.get("priority"), _CLAIM_PRIORITIES, "claim priority"),
            state=_enum(data.get("state"), _CLAIM_STATES, "claim state"),
            evidence_requirement=_parse_requirement(data.get("evidence_requirement")),
            parent_id=_optional_id(data.get("parent_id"), "parent id"),
            alias_to=_optional_id(data.get("alias_to"), "alias id"),
            created_by=_text(data.get("created_by"), "claim creator", 100),
            created_reason=_optional_text(data.get("created_reason"), "created reason", 1000),
        )
    )


def _parse_evidence(raw: Any) -> ResearchEvidence:
    data = _mapping(raw, "research evidence")
    _only_keys(
        data,
        {
            "evidence_id",
            "locator",
            "anchored_spans",
            "lifecycle_status",
            "extraction_status",
            "published_at",
            "units",
        },
        "research evidence",
    )
    return _validate_evidence(
        ResearchEvidence(
            evidence_id=_id(data.get("evidence_id"), "research evidence id"),
            locator=_optional_text(data.get("locator"), "evidence locator", 500),
            anchored_spans=_string_tuple(
                data.get("anchored_spans"),
                "anchored spans",
                max_items=8,
                item_max_length=1000,
            ),
            lifecycle_status=_enum(
                data.get("lifecycle_status"),
                _EVIDENCE_LIFECYCLE_STATES,
                "evidence lifecycle status",
            ),
            extraction_status=_enum(
                data.get("extraction_status"),
                _EXTRACTION_STATES,
                "evidence extraction status",
            ),
            published_at=_optional_date(data.get("published_at"), "evidence published at"),
            units=parse_evidence_units(data.get("units")),
        )
    )


def _parse_evidence_link(raw: Any) -> ResearchClaimEvidenceLink:
    data = _mapping(raw, "research evidence link")
    _only_keys(
        data,
        {
            "claim_id",
            "evidence_id",
            "relation",
            "strength",
            "source_role",
            "source_cluster_id",
            "locator",
            "caveats",
        },
        "research evidence link",
    )
    relation = _enum(data.get("relation"), _EVIDENCE_RELATIONS, "evidence relation")
    return _validate_evidence_link(
        ResearchClaimEvidenceLink(
            link=ClaimEvidenceLinkV1(
                claim_id=_id(data.get("claim_id"), "link claim id"),
                evidence_id=_id(data.get("evidence_id"), "link evidence id"),
                support_type=relation,
                confidence=_number(data.get("strength"), "link strength"),
            ),
            source_role=_optional_source_role(data.get("source_role"), "source role"),
            source_cluster_id=_optional_id(data.get("source_cluster_id"), "source cluster id"),
            locator=_optional_text(data.get("locator"), "link locator", 500),
            caveats=_string_tuple(data.get("caveats"), "link caveats", max_items=8),
        )
    )


def _parse_gap(raw: Any) -> EvidenceGap:
    data = _mapping(raw, "evidence gap")
    _only_keys(
        data,
        {
            "id",
            "claim_id",
            "gap_type",
            "desired_source_role",
            "priority",
            "attempt_count",
            "state",
        },
        "evidence gap",
    )
    return _validate_gap(
        EvidenceGap(
            id=_id(data.get("id"), "gap id"),
            claim_id=_id(data.get("claim_id"), "gap claim id"),
            gap_type=_text(data.get("gap_type"), "gap type", 100),
            desired_source_role=_optional_source_role(
                data.get("desired_source_role"), "desired source role"
            ),
            priority=_enum(data.get("priority"), _CLAIM_PRIORITIES, "gap priority"),
            attempt_count=_integer(data.get("attempt_count"), "gap attempt count"),
            state=_enum(data.get("state"), _GAP_STATES, "gap state"),
        )
    )


def _parse_conflict_gap(raw: Any) -> ConflictGap:
    data = _mapping(raw, "conflict gap")
    _only_keys(
        data,
        {
            "id",
            "claim_id",
            "supporting_evidence_ids",
            "contradicting_evidence_ids",
            "state",
        },
        "conflict gap",
    )
    return _validate_conflict_gap(
        ConflictGap(
            id=_id(data.get("id"), "conflict gap id"),
            claim_id=_id(data.get("claim_id"), "conflict claim id"),
            supporting_evidence_ids=_id_tuple(
                data.get("supporting_evidence_ids"), "supporting evidence ids"
            ),
            contradicting_evidence_ids=_id_tuple(
                data.get("contradicting_evidence_ids"), "contradicting evidence ids"
            ),
            state=_enum(data.get("state"), _GAP_STATES, "conflict gap state"),
        )
    )


def _parse_cluster(raw: Any) -> EvidenceCluster:
    data = _mapping(raw, "evidence cluster")
    _only_keys(
        data,
        {"id", "evidence_ids", "source_role", "independence_key"},
        "evidence cluster",
    )
    return _validate_cluster(
        EvidenceCluster(
            id=_id(data.get("id"), "cluster id"),
            evidence_ids=_id_tuple(data.get("evidence_ids"), "cluster evidence ids"),
            source_role=_optional_source_role(
                data.get("source_role"), "cluster source role"
            ),
            independence_key=_optional_text(
                data.get("independence_key"), "cluster independence key", 500
            ),
        )
    )


def _parse_budget(raw: Any) -> ResearchBudget:
    data = _mapping(raw, "research budget")
    _only_keys(
        data,
        {
            "max_candidates",
            "max_reads",
            "soft_timeout_seconds",
            "hard_timeout_seconds",
            "max_total_chars",
            "candidates_used",
            "reads_used",
            "elapsed_seconds",
        },
        "research budget",
    )
    return _validate_budget(
        ResearchBudget(
            max_candidates=_integer(data.get("max_candidates"), "max candidates"),
            max_reads=_integer(data.get("max_reads"), "max reads"),
            soft_timeout_seconds=_number(
                data.get("soft_timeout_seconds"), "soft timeout seconds"
            ),
            hard_timeout_seconds=_number(
                data.get("hard_timeout_seconds"), "hard timeout seconds"
            ),
            max_total_chars=_integer(data.get("max_total_chars"), "max total chars"),
            candidates_used=_integer(data.get("candidates_used"), "candidates used"),
            reads_used=_integer(data.get("reads_used"), "reads used"),
            elapsed_seconds=_number(data.get("elapsed_seconds"), "elapsed seconds"),
        )
    )


def _parse_trace(raw: Any) -> ResearchTraceEvent:
    data = _mapping(raw, "research trace event")
    _only_keys(
        data,
        {
            "sequence",
            "timestamp",
            "run_id",
            "event_type",
            "reason",
            "claim_id",
            "gap_id",
            "evidence_id",
            "budget_before",
            "budget_after",
        },
        "research trace event",
    )
    return _validate_trace(
        ResearchTraceEvent(
            sequence=_integer(data.get("sequence"), "trace sequence"),
            timestamp=_timestamp(data.get("timestamp")),
            run_id=_id(data.get("run_id"), "trace run id"),
            event_type=_enum(
                data.get("event_type"), _TRACE_EVENT_TYPES, "trace event type"
            ),
            reason=_text(data.get("reason"), "trace reason", 1000),
            claim_id=_optional_id(data.get("claim_id"), "trace claim id"),
            gap_id=_optional_id(data.get("gap_id"), "trace gap id"),
            evidence_id=_optional_id(data.get("evidence_id"), "trace evidence id"),
            budget_before=(
                _parse_budget(data.get("budget_before"))
                if data.get("budget_before") is not None
                else None
            ),
            budget_after=(
                _parse_budget(data.get("budget_after"))
                if data.get("budget_after") is not None
                else None
            ),
        )
    )


def _parse_brief(raw: Any) -> ResearchBrief:
    data = _mapping(raw, "research brief")
    _only_keys(
        data,
        {"claim_ids", "unresolved_claim_ids", "conflict_gap_ids", "outline"},
        "research brief",
    )
    return _validate_brief(
        ResearchBrief(
            claim_ids=_id_tuple(data.get("claim_ids"), "brief claim ids", allow_empty=True),
            unresolved_claim_ids=_id_tuple(
                data.get("unresolved_claim_ids"),
                "brief unresolved claim ids",
                allow_empty=True,
            ),
            conflict_gap_ids=_id_tuple(
                data.get("conflict_gap_ids"),
                "brief conflict gap ids",
                allow_empty=True,
            ),
            outline=_string_tuple(data.get("outline"), "brief outline", max_items=24),
        )
    )


def _validate_question(value: ResearchQuestion) -> ResearchQuestion:
    return ResearchQuestion(
        id=_id(value.id, "question id"),
        question_surface=_text(value.question_surface, "question surface", 2000),
        priority=_enum(value.priority, _CLAIM_PRIORITIES, "question priority"),
        state=_enum(value.state, _CLAIM_STATES, "question state"),
    )


def _validate_requirement(value: EvidenceRequirement) -> EvidenceRequirement:
    roles = _normalized_strings(value.source_roles, "source roles", max_items=12)
    invalid_roles = sorted(set(roles) - _SOURCE_ROLES)
    if invalid_roles:
        raise ValueError(f"invalid source roles: {', '.join(invalid_roles)}")
    minimum = _integer(value.min_independent_sources, "min independent sources")
    if minimum < 0 or minimum > 20:
        raise ValueError("min independent sources must be between 0 and 20")
    return EvidenceRequirement(
        source_roles=roles,
        min_independent_sources=minimum,
        requires_primary_source=_boolean(
            value.requires_primary_source, "requires primary source"
        ),
        requires_successful_read=_boolean(
            value.requires_successful_read, "requires successful read"
        ),
        max_age_days=_optional_non_negative_int(
            value.max_age_days, "max evidence age days"
        ),
        requires_dated_evidence=_boolean(
            value.requires_dated_evidence, "requires dated evidence"
        ),
        required_units=parse_required_units(
            [unit.to_dict() for unit in value.required_units]
        ),
    )


def _validate_claim(value: ResearchClaim) -> ResearchClaim:
    return ResearchClaim(
        id=_id(value.id, "claim id"),
        question_id=_id(value.question_id, "claim question id"),
        text=_text(value.text, "claim text", 2000),
        kind=_enum(value.kind, _CLAIM_KINDS, "claim kind"),
        priority=_enum(value.priority, _CLAIM_PRIORITIES, "claim priority"),
        state=_enum(value.state, _CLAIM_STATES, "claim state"),
        evidence_requirement=_validate_requirement(value.evidence_requirement),
        parent_id=_optional_id(value.parent_id, "parent id"),
        alias_to=_optional_id(value.alias_to, "alias id"),
        created_by=_text(value.created_by, "claim creator", 100),
        created_reason=_optional_text(value.created_reason, "created reason", 1000),
    )


def _validate_evidence(value: ResearchEvidence) -> ResearchEvidence:
    return ResearchEvidence(
        evidence_id=_id(value.evidence_id, "research evidence id"),
        locator=_optional_text(value.locator, "evidence locator", 500),
        anchored_spans=_normalized_strings(
            value.anchored_spans,
            "anchored spans",
            max_items=8,
            item_max_length=1000,
        ),
        lifecycle_status=_enum(
            value.lifecycle_status,
            _EVIDENCE_LIFECYCLE_STATES,
            "evidence lifecycle status",
        ),
        extraction_status=_enum(
            value.extraction_status,
            _EXTRACTION_STATES,
            "evidence extraction status",
        ),
        published_at=_optional_date(value.published_at, "evidence published at"),
        units=parse_evidence_units([unit.to_dict() for unit in value.units]),
    )


def _validate_evidence_link(value: ResearchClaimEvidenceLink) -> ResearchClaimEvidenceLink:
    relation = _enum(value.relation, _EVIDENCE_RELATIONS, "evidence relation")
    strength = _number(value.strength, "link strength")
    if not 0.0 <= strength <= 1.0:
        raise ValueError("link strength must be between 0 and 1")
    return ResearchClaimEvidenceLink(
        link=ClaimEvidenceLinkV1(
            claim_id=_id(value.claim_id, "link claim id"),
            evidence_id=_id(value.evidence_id, "link evidence id"),
            support_type=relation,
            confidence=strength,
        ),
        source_role=_optional_source_role(value.source_role, "source role"),
        source_cluster_id=_optional_id(value.source_cluster_id, "source cluster id"),
        locator=_optional_text(value.locator, "link locator", 500),
        caveats=_normalized_strings(value.caveats, "link caveats", max_items=8),
    )


def _validate_gap(value: EvidenceGap) -> EvidenceGap:
    attempts = _integer(value.attempt_count, "gap attempt count")
    if attempts < 0:
        raise ValueError("gap attempt count cannot be negative")
    return EvidenceGap(
        id=_id(value.id, "gap id"),
        claim_id=_id(value.claim_id, "gap claim id"),
        gap_type=_text(value.gap_type, "gap type", 100),
        desired_source_role=_optional_source_role(
            value.desired_source_role, "desired source role"
        ),
        priority=_enum(value.priority, _CLAIM_PRIORITIES, "gap priority"),
        attempt_count=attempts,
        state=_enum(value.state, _GAP_STATES, "gap state"),
    )


def _validate_conflict_gap(value: ConflictGap) -> ConflictGap:
    supporting = _normalized_ids(value.supporting_evidence_ids, "supporting evidence ids")
    contradicting = _normalized_ids(
        value.contradicting_evidence_ids, "contradicting evidence ids"
    )
    if not supporting or not contradicting:
        raise ValueError("conflict gap requires supporting and contradicting evidence")
    if set(supporting) & set(contradicting):
        raise ValueError("conflict evidence cannot support and contradict simultaneously")
    return ConflictGap(
        id=_id(value.id, "conflict gap id"),
        claim_id=_id(value.claim_id, "conflict claim id"),
        supporting_evidence_ids=supporting,
        contradicting_evidence_ids=contradicting,
        state=_enum(value.state, _GAP_STATES, "conflict gap state"),
    )


def _validate_cluster(value: EvidenceCluster) -> EvidenceCluster:
    evidence_ids = _normalized_ids(value.evidence_ids, "cluster evidence ids")
    if not evidence_ids:
        raise ValueError("evidence cluster requires at least one evidence id")
    return EvidenceCluster(
        id=_id(value.id, "cluster id"),
        evidence_ids=evidence_ids,
        source_role=_optional_source_role(value.source_role, "cluster source role"),
        independence_key=_optional_text(
            value.independence_key, "cluster independence key", 500
        ),
    )


def _validate_budget(value: ResearchBudget) -> ResearchBudget:
    candidates = _integer(value.max_candidates, "max candidates")
    reads = _integer(value.max_reads, "max reads")
    soft = _number(value.soft_timeout_seconds, "soft timeout seconds")
    hard = _number(value.hard_timeout_seconds, "hard timeout seconds")
    chars = _integer(value.max_total_chars, "max total chars")
    candidates_used = _integer(value.candidates_used, "candidates used")
    reads_used = _integer(value.reads_used, "reads used")
    elapsed = _number(value.elapsed_seconds, "elapsed seconds")
    if candidates < 1 or candidates > 1000:
        raise ValueError("max candidates must be between 1 and 1000")
    if reads < 0 or reads > candidates:
        raise ValueError("max reads must be between 0 and max candidates")
    if soft <= 0 or hard <= 0 or soft > hard:
        raise ValueError("timeouts must be positive and soft must not exceed hard")
    if chars < 0:
        raise ValueError("max total chars cannot be negative")
    if candidates_used < 0 or candidates_used > candidates:
        raise ValueError("candidates used must be between 0 and max candidates")
    if reads_used < 0 or reads_used > reads:
        raise ValueError("reads used must be between 0 and max reads")
    if elapsed < 0:
        raise ValueError("elapsed seconds cannot be negative")
    return ResearchBudget(
        candidates,
        reads,
        soft,
        hard,
        chars,
        candidates_used,
        reads_used,
        elapsed,
    )


def _validate_trace(value: ResearchTraceEvent) -> ResearchTraceEvent:
    sequence = _integer(value.sequence, "trace sequence")
    if sequence < 0:
        raise ValueError("trace sequence cannot be negative")
    return ResearchTraceEvent(
        sequence=sequence,
        timestamp=_timestamp(value.timestamp),
        run_id=_id(value.run_id, "trace run id"),
        event_type=_enum(value.event_type, _TRACE_EVENT_TYPES, "trace event type"),
        reason=_text(value.reason, "trace reason", 1000),
        claim_id=_optional_id(value.claim_id, "trace claim id"),
        gap_id=_optional_id(value.gap_id, "trace gap id"),
        evidence_id=_optional_id(value.evidence_id, "trace evidence id"),
        budget_before=(
            _validate_budget(value.budget_before) if value.budget_before else None
        ),
        budget_after=_validate_budget(value.budget_after) if value.budget_after else None,
    )


def _validate_brief(value: ResearchBrief) -> ResearchBrief:
    return ResearchBrief(
        claim_ids=_normalized_ids(value.claim_ids, "brief claim ids", allow_empty=True),
        unresolved_claim_ids=_normalized_ids(
            value.unresolved_claim_ids,
            "brief unresolved claim ids",
            allow_empty=True,
        ),
        conflict_gap_ids=_normalized_ids(
            value.conflict_gap_ids,
            "brief conflict gap ids",
            allow_empty=True,
        ),
        outline=_normalized_strings(value.outline, "brief outline", max_items=24),
    )


def _mapping(raw: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be an object")
    return raw


def _only_keys(raw: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(str(key) for key in raw if key not in allowed)
    if unknown:
        raise ValueError(f"unknown {label} fields: {', '.join(unknown)}")


def _sequence(raw: Mapping[str, Any], key: str) -> list[Any]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value


def _text(raw: Any, label: str, max_length: int) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{label} must be text")
    value = " ".join(raw.strip().split())
    if not value:
        raise ValueError(f"{label} is required")
    if len(value) > max_length:
        raise ValueError(f"{label} exceeds {max_length} characters")
    return value


def _optional_text(raw: Any, label: str, max_length: int) -> str:
    if raw is None or raw == "":
        return ""
    return _text(raw, label, max_length)


def _id(raw: Any, label: str) -> str:
    return _text(raw, label, 200)


def _optional_id(raw: Any, label: str) -> str:
    if raw is None or raw == "":
        return ""
    return _id(raw, label)


def _optional_source_role(raw: Any, label: str) -> str:
    value = _optional_text(raw, label, 100)
    if value and value not in _SOURCE_ROLES:
        raise ValueError(f"invalid {label}: {value}")
    return value


def _enum(raw: Any, allowed: set[str], label: str) -> Any:
    value = _text(raw, label, 100)
    if value not in allowed:
        raise ValueError(f"invalid {label}: {value}")
    return value


def _integer(raw: Any, label: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{label} must be an integer")
    return raw


def _number(raw: Any, label: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{label} must be numeric")
    value = float(raw)
    if not isfinite(value):
        raise ValueError(f"{label} must be finite")
    return value


def _optional_non_negative_int(raw: Any, label: str) -> int | None:
    if raw is None:
        return None
    value = _integer(raw, label)
    if value < 0:
        raise ValueError(f"{label} cannot be negative")
    return value


def _optional_date(raw: Any, label: str) -> str:
    if raw is None or raw == "":
        return ""
    value = _text(raw, label, 100)
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 date") from exc


def _timestamp(raw: Any) -> str:
    value = _text(raw, "trace timestamp", 100)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("trace timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("trace timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _boolean(raw: Any, label: str) -> bool:
    if not isinstance(raw, bool):
        raise ValueError(f"{label} must be boolean")
    return raw


def _string_tuple(
    raw: Any,
    label: str,
    *,
    max_items: int,
    item_max_length: int = 500,
) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{label} must be a list")
    return _normalized_strings(
        raw,
        label,
        max_items=max_items,
        item_max_length=item_max_length,
    )


def _normalized_strings(
    raw: Iterable[str],
    label: str,
    *,
    max_items: int,
    item_max_length: int = 500,
) -> tuple[str, ...]:
    if isinstance(raw, (str, bytes)):
        raise ValueError(f"{label} must be a collection, not text")
    values = tuple(_text(value, label, item_max_length) for value in raw)
    if len(values) > max_items:
        raise ValueError(f"{label} exceeds {max_items} items")
    _unique_values(values, label)
    return tuple(sorted(values))


def _id_tuple(raw: Any, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{label} must be a list")
    return _normalized_ids(raw, label, allow_empty=allow_empty)


def _normalized_ids(
    raw: Iterable[str],
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if isinstance(raw, (str, bytes)):
        raise ValueError(f"{label} must be a collection, not text")
    values = tuple(_id(value, label) for value in raw)
    if not values and not allow_empty:
        raise ValueError(f"{label} cannot be empty")
    _unique_values(values, label)
    return tuple(sorted(values))


def _unique_values(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)


def _unique_ids(values: Iterable[Any], label: str) -> None:
    _unique_values((value.id for value in values), f"{label} id")


def _require_known_evidence(values: Iterable[str], known: set[str]) -> None:
    for value in values:
        if value not in known:
            raise ValueError(f"unknown server-owned evidence id: {value}")


def _require_subset(values: Iterable[str], known: set[str], label: str) -> None:
    for value in values:
        if value not in known:
            raise ValueError(f"unknown {label}: {value}")


def _by_id(value: Any) -> str:
    return value.id
