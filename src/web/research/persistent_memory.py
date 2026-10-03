"""Strict, bounded cross-run research-memory values (§150).

These are historical leads, never current-run evidence or answer authority.
The schema is deliberately independent of ``research-state-v1``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import re
import unicodedata
from typing import Any, Literal, Mapping

from src.domain.evidence import build_evidence_snapshot
from src.domain.runtime_entities import WebLookupRun
from src.web.research.contracts import ResearchState

MEMORY_SCHEMA_VERSION = "research-memory-v1"
MemoryClaimStatus = Literal["confirmed", "unresolved", "superseded", "contradicted"]
Freshness = Literal["current", "stale", "unknown"]
Relevance = Literal["same_topic", "unverified"]
_STATUSES = frozenset({"confirmed", "unresolved", "superseded", "contradicted"})
_ADEQUACY = frozenset({"adequate", "partial", "insufficient", "not_evaluated"})
_CONFLICT = frozenset({"none", "unresolved_conflict", "preferred_side"})
_PREFERRED = frozenset({"", "support", "contradict"})
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def state_digest(state: ResearchState) -> str:
    return hashlib.sha256(canonical_json(state.to_dict()).encode("utf-8")).hexdigest()


def known_research_evidence_ids(run: WebLookupRun) -> tuple[str, ...]:
    """Use the canonical run snapshot, not IDs supplied by a memory caller."""

    snapshot = build_evidence_snapshot(rag={"research_sources": {
        "run_id": run.id,
        "provider_status": run.provider_status,
        "source_truth_version": int(run.research_context.get("source_truth_version") or 0),
        "selected_sources": run.selected_sources,
        "rejected_sources": run.rejected_sources,
    }})
    return tuple(ref.id for ref in snapshot.refs)


def normalized_topic(question: str) -> str:
    """A bounded label for exact topical comparison; never an access key."""

    return " ".join(unicodedata.normalize("NFKC", question).casefold().split())[:200]


@dataclass(frozen=True)
class MemoryEvidenceRef:
    source_run_id: str
    evidence_id: str
    source: str = ""
    locator: str = ""
    modality: str = "unknown"
    page: int | None = None
    region: str = ""
    published_at: str = ""
    provenance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return vars(self).copy()

    @classmethod
    def from_dict(cls, raw: Any) -> MemoryEvidenceRef:
        value = _object(raw, {
            "source_run_id", "evidence_id", "source", "locator", "modality",
            "page", "region", "published_at", "provenance",
        })
        page = value["page"]
        if page is not None and (type(page) is not int or page < 0):
            raise ValueError("invalid memory evidence page")
        published = _string(value["published_at"], 40, allow_empty=True)
        if published:
            _date(published)
        return cls(
            source_run_id=_string(value["source_run_id"], 120),
            evidence_id=_string(value["evidence_id"], 120),
            source=_string(value["source"], 500, allow_empty=True),
            locator=_string(value["locator"], 500, allow_empty=True),
            modality=_string(value["modality"], 30),
            page=page,
            region=_string(value["region"], 200, allow_empty=True),
            published_at=published,
            provenance=_string(value["provenance"], 500, allow_empty=True),
        )


@dataclass(frozen=True)
class MemoryClaim:
    claim_id: str
    statement: str
    criticality: str
    status: MemoryClaimStatus
    semantic_adequacy: str
    conflict_status: str
    preferred_side: str
    required_units: tuple[str, ...]
    covered_units: tuple[str, ...]
    missing_units: tuple[str, ...]
    support_refs: tuple[str, ...]
    contradict_refs: tuple[str, ...]
    max_age_days: int | None = None
    requires_dated_evidence: bool = False
    audited_conclusion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            **{key: value for key, value in vars(self).items() if not isinstance(value, tuple)},
            **{
                key: list(value)
                for key, value in vars(self).items()
                if isinstance(value, tuple)
            },
        }

    @classmethod
    def from_dict(cls, raw: Any) -> MemoryClaim:
        value = _object(raw, {
            "claim_id", "statement", "criticality", "status",
            "semantic_adequacy", "conflict_status", "preferred_side",
            "required_units", "covered_units", "missing_units", "support_refs",
            "contradict_refs", "max_age_days", "requires_dated_evidence",
            "audited_conclusion",
        })
        status = _string(value["status"], 30)
        if status not in _STATUSES:
            raise ValueError("invalid memory claim status")
        age = value["max_age_days"]
        if age is not None and (type(age) is not int or age < 0):
            raise ValueError("invalid memory max age")
        dated = value["requires_dated_evidence"]
        if type(dated) is not bool:
            raise ValueError("invalid memory dated flag")
        conclusion = _string(value["audited_conclusion"], 2000, allow_empty=True)
        if status != "confirmed" and conclusion:
            raise ValueError("unapproved memory claim has a conclusion")
        adequacy = _string(value["semantic_adequacy"], 30)
        conflict = _string(value["conflict_status"], 30)
        preferred = _string(value["preferred_side"], 30, allow_empty=True)
        if adequacy not in _ADEQUACY or conflict not in _CONFLICT or preferred not in _PREFERRED:
            raise ValueError("invalid memory claim assessment")
        if (conflict == "preferred_side") != bool(preferred):
            raise ValueError("memory preferred side mismatch")
        required = _strings(value["required_units"], 32)
        covered = _strings(value["covered_units"], 32)
        missing = _strings(value["missing_units"], 32)
        if set(covered) & set(missing) or set(covered + missing) != set(required):
            raise ValueError("memory required unit coverage mismatch")
        return cls(
            claim_id=_string(value["claim_id"], 120),
            statement=_string(value["statement"], 2000),
            criticality=_string(value["criticality"], 30),
            status=status,  # type: ignore[arg-type]
            semantic_adequacy=adequacy,
            conflict_status=conflict,
            preferred_side=preferred,
            required_units=required,
            covered_units=covered,
            missing_units=missing,
            support_refs=_strings(value["support_refs"], 64),
            contradict_refs=_strings(value["contradict_refs"], 64),
            max_age_days=age,
            requires_dated_evidence=dated,
            audited_conclusion=conclusion,
        )


@dataclass(frozen=True)
class ResearchMemoryRevision:
    revision_id: str
    owner_thread_id: str
    topic: str
    source_run_id: str
    source_run_version: int
    state_digest: str
    generated_at: str
    question: str
    claims: tuple[MemoryClaim, ...]
    evidence_refs: tuple[MemoryEvidenceRef, ...]
    unresolved_gaps: tuple[str, ...]
    limitations: tuple[str, ...]
    prior_revision_ids: tuple[str, ...] = ()
    audit_verdict: str = "unverified"
    audit_judge: str = ""
    schema_version: str = MEMORY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "revision_id": self.revision_id,
            "owner_thread_id": self.owner_thread_id,
            "topic": self.topic,
            "source_run_id": self.source_run_id,
            "source_run_version": self.source_run_version,
            "state_digest": self.state_digest,
            "generated_at": self.generated_at,
            "question": self.question,
            "claims": [claim.to_dict() for claim in self.claims],
            "evidence_refs": [ref.to_dict() for ref in self.evidence_refs],
            "unresolved_gaps": list(self.unresolved_gaps),
            "limitations": list(self.limitations),
            "prior_revision_ids": list(self.prior_revision_ids),
            "audit_verdict": self.audit_verdict,
            "audit_judge": self.audit_judge,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> ResearchMemoryRevision:
        value = _object(raw, {
            "schema_version", "revision_id", "owner_thread_id", "topic",
            "source_run_id", "source_run_version", "state_digest", "generated_at",
            "question", "claims", "evidence_refs", "unresolved_gaps", "limitations",
            "prior_revision_ids", "audit_verdict", "audit_judge",
        })
        if value["schema_version"] != MEMORY_SCHEMA_VERSION:
            raise ValueError("unsupported research memory schema")
        version = value["source_run_version"]
        if type(version) is not int or version < 1:
            raise ValueError("invalid source run version")
        digest = _string(value["state_digest"], 64)
        if _HEX_64.fullmatch(digest) is None:
            raise ValueError("invalid state digest")
        generated = _string(value["generated_at"], 40)
        _timestamp(generated)
        claims = _models(value["claims"], MemoryClaim.from_dict, 64)
        refs = _models(value["evidence_refs"], MemoryEvidenceRef.from_dict, 256)
        revision = cls(
            revision_id=_string(value["revision_id"], 120),
            owner_thread_id=_string(value["owner_thread_id"], 120),
            topic=_string(value["topic"], 200, allow_empty=True),
            source_run_id=_string(value["source_run_id"], 120),
            source_run_version=version,
            state_digest=digest,
            generated_at=generated,
            question=_string(value["question"], 2000, allow_empty=True),
            claims=claims,
            evidence_refs=refs,
            unresolved_gaps=_strings(value["unresolved_gaps"], 64),
            limitations=_strings(value["limitations"], 64),
            prior_revision_ids=_strings(value["prior_revision_ids"], 20),
            audit_verdict=_string(value["audit_verdict"], 30),
            audit_judge=_string(value["audit_judge"], 120, allow_empty=True),
        )
        if any(ref.source_run_id != revision.source_run_id for ref in refs):
            raise ValueError("memory evidence source run mismatch")
        if any(not ref.evidence_id.startswith(f"{revision.source_run_id}:") for ref in refs):
            raise ValueError("memory evidence id lacks source run namespace")
        ids = {ref.evidence_id for ref in refs}
        if len(ids) != len(refs):
            raise ValueError("duplicate memory evidence ref")
        if len({claim.claim_id for claim in claims}) != len(claims):
            raise ValueError("duplicate memory claim")
        for claim in claims:
            if not set((*claim.support_refs, *claim.contradict_refs)) <= ids:
                raise ValueError("memory claim references unknown evidence")
            if claim.status == "confirmed":
                raise ValueError("confirmed memory lacks qualified audit authority")
        if revision.topic != normalized_topic(revision.question):
            raise ValueError("memory topic mismatch")
        if revision.audit_verdict != "unverified" or revision.audit_judge:
            raise ValueError("memory audit provenance is not qualified")
        if len(set(revision.prior_revision_ids)) != len(revision.prior_revision_ids):
            raise ValueError("duplicate prior memory revision")
        if revision.revision_id in revision.prior_revision_ids:
            raise ValueError("memory revision links itself")
        return revision


@dataclass(frozen=True)
class RecallCandidate:
    revision_id: str
    status: Literal["available", "unavailable"]
    reason: str
    relevance: Relevance = "unverified"
    freshness: Freshness = "unknown"
    revision: ResearchMemoryRevision | None = None


def revision_freshness(revision: ResearchMemoryRevision, *, today: date) -> Freshness:
    """Conservative: unknown dates or no declared age never become current."""

    refs = {ref.evidence_id: ref for ref in revision.evidence_refs}
    saw_current = False
    saw_unknown = False
    for claim in revision.claims:
        if not claim.support_refs or claim.max_age_days is None:
            saw_unknown = True
            continue
        for ref_id in claim.support_refs:
            ref = refs[ref_id]
            if not ref.published_at:
                saw_unknown = True
                continue
            age = (today - _date(ref.published_at)).days
            if age < 0 or age > claim.max_age_days:
                return "stale"
            saw_current = True
    return "unknown" if saw_unknown or not saw_current else "current"


def _object(raw: Any, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != keys:
        raise ValueError("invalid research memory object")
    return raw


def _string(raw: Any, limit: int, *, allow_empty: bool = False) -> str:
    if not isinstance(raw, str) or len(raw) > limit or (not raw.strip() and not allow_empty):
        raise ValueError("invalid research memory string")
    return raw


def _strings(raw: Any, limit: int) -> tuple[str, ...]:
    if not isinstance(raw, list) or len(raw) > limit:
        raise ValueError("invalid research memory list")
    return tuple(_string(value, 2000) for value in raw)


def _models(raw: Any, parser: Any, limit: int) -> tuple[Any, ...]:
    if not isinstance(raw, list) or len(raw) > limit:
        raise ValueError("invalid research memory collection")
    return tuple(parser(value) for value in raw)


def _timestamp(raw: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("invalid research memory timestamp") from exc
    if value.tzinfo is None:
        raise ValueError("research memory timestamp needs timezone")
    return value.astimezone(timezone.utc)


def _date(raw: str) -> date:
    try:
        if len(raw) == 10:
            return date.fromisoformat(raw)
        return _timestamp(raw).date()
    except ValueError as exc:
        raise ValueError("invalid research memory date") from exc
