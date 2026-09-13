"""Bounded operational cursor for Claim Engine runtime execution.

``ResearchState`` remains the semantic durable truth.  This module stores only
resume/audit cursor data needed to continue one active run after a checkpoint;
it owns no database writes and contains no page bodies, prompts, or raw model
responses.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping

from src.web.research.model_gateway import (
    ResearchModelAttemptStart,
    ResearchModelCallAudit,
)
from src.web.research.evidence_gain import EvidenceGainResult, SaturationState
from src.web.research.lead_discovery import LeadDiscoveryPayload
from src.web.research.failure_contracts import (
    ResearchFailureCode,
    require_research_failure_code,
)

CLAIM_ENGINE_RUNTIME_CONTEXT_KEY = "claim_engine_runtime"
RESEARCH_RUNTIME_SCHEMA_VERSION_V1 = "research-runtime-v1"
RESEARCH_RUNTIME_SCHEMA_VERSION_V2 = "research-runtime-v2"
SUPPORTED_RESEARCH_RUNTIME_SCHEMA_VERSIONS = frozenset(
    {
        RESEARCH_RUNTIME_SCHEMA_VERSION_V1,
        RESEARCH_RUNTIME_SCHEMA_VERSION_V2,
    }
)
# Batch B: new production cursors write v2.  A loaded v1 cursor retains its
# explicit schema_version and therefore still reserializes byte-shape
# compatibly; readers never guess or silently migrate its legacy failures.
RESEARCH_RUNTIME_SCHEMA_VERSION = RESEARCH_RUNTIME_SCHEMA_VERSION_V2
LATEST_RESEARCH_RUNTIME_SCHEMA_VERSION = RESEARCH_RUNTIME_SCHEMA_VERSION_V2

RuntimeLoadStatus = Literal["absent", "available", "unavailable"]
RuntimeExternalPurpose = Literal["search", "read"]
RuntimePhase = Literal[
    "bootstrap",
    "planning",
    "searching",
    "assessing",
    "ranking",
    "reading",
    "extracting",
    "gating",
    "synthesizing",
    "completed",
    "unavailable",
]

_PHASES = {
    "bootstrap",
    "planning",
    "searching",
    "assessing",
    "ranking",
    "reading",
    "extracting",
    "gating",
    "synthesizing",
    "completed",
    "unavailable",
}
_QUERY_STATUSES = {"ok", "empty", "unavailable"}
_READ_STATUSES = {"success", "failed", "skipped"}
_MAX_CURSOR_ITEMS = 100
# P1-C batch 2: durable gain history keeps only the most recent entries so a
# long multi-wave run can never outgrow the cursor serialization limit.
_MAX_GAIN_HISTORY_ENTRIES = 24
# Slice 1: bounded lead discovery keeps at most the run-level lead-read budget
# of durable discovery payloads (never evidence).
MAX_LEAD_READS_PER_RUN = 2
_MAX_LEAD_DISCOVERIES = MAX_LEAD_READS_PER_RUN
# Slice 2: bounded re-entry of lead-discovered URLs. Discovery depth 1 only
# (no lead -> lead -> lead recursion), and a small run-level cap so discovery
# can never refill the candidate pool or the budget.
MAX_LEAD_DISCOVERY_DEPTH = 1
MAX_LEAD_DISCOVERED_CANDIDATES_PER_RUN = 4
# Evidence Lead Follow-up admission (strict; shares the frozen read/model/time
# budget - it never adds budget of its own).
MAX_EVIDENCE_LEAD_FOLLOWUPS_PER_RUN = 2
MAX_EVIDENCE_LEAD_FOLLOWUPS_PER_WAVE = 1
EVIDENCE_LEAD_FOLLOWUP_MIN_REMAINING_SECONDS = 20.0
_MAX_EVIDENCE_LEAD_FOLLOWUPS = MAX_EVIDENCE_LEAD_FOLLOWUPS_PER_RUN
# Frozen wave ceiling for the bounded multi-wave loop: saturation (2 batches,
# 3 for critical/conflict) always fits, and the ceiling guards against any
# endless loop if gain/saturation bookkeeping were ever inconsistent.
MAX_RESEARCH_WAVES = 8


@dataclass(frozen=True)
class RuntimePlannedQuery:
    id: str
    gap_id: str
    claim_id: str
    intent: str
    query: str
    desired_source_role: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "gap_id": self.gap_id,
            "claim_id": self.claim_id,
            "intent": self.intent,
            "query": self.query,
            "desired_source_role": self.desired_source_role,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RuntimePlannedQuery":
        data = _strict_mapping(
            raw,
            {"id", "gap_id", "claim_id", "intent", "query", "desired_source_role"},
            "runtime planned query",
        )
        return cls(
            id=_required_text(data.get("id"), 300, "query id"),
            gap_id=_required_text(data.get("gap_id"), 300, "gap id"),
            claim_id=_required_text(data.get("claim_id"), 300, "claim id"),
            intent=_required_text(data.get("intent"), 100, "query intent"),
            query=_required_text(data.get("query"), 1000, "query"),
            desired_source_role=_optional_text(data.get("desired_source_role"), 100),
        )


@dataclass(frozen=True)
class RuntimeQueryOutcome:
    query_id: str
    status: str
    result_count: int
    providers: tuple[str, ...] = ()
    error_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "status": self.status,
            "result_count": self.result_count,
            "providers": list(self.providers),
            "error_code": self.error_code,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RuntimeQueryOutcome":
        data = _strict_mapping(
            raw,
            {"query_id", "status", "result_count", "providers", "error_code"},
            "runtime query outcome",
        )
        status = _required_text(data.get("status"), 50, "query status")
        if status not in _QUERY_STATUSES:
            raise ValueError("invalid runtime query status")
        return cls(
            query_id=_required_text(data.get("query_id"), 300, "query id"),
            status=status,
            result_count=_bounded_int(data.get("result_count"), 0, 10000, "result_count"),
            providers=_text_tuple(data.get("providers"), 20, 100),
            error_code=_optional_text(data.get("error_code"), 200),
        )


@dataclass(frozen=True)
class RuntimeCandidate:
    id: str
    url: str
    title: str
    snippet: str = ""
    source: str = ""
    published_at: str = ""
    query_ids: tuple[str, ...] = ()
    intents: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()
    first_seen_rank: int = 0
    # Slice 2 provenance: a candidate discovered by a bounded lead read records
    # how it was found. Provenance only - identity stays the canonical URL.
    parent_lead_candidate_id: str = ""
    discovery_method: str = ""
    discovery_depth: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "source": self.source,
            "published_at": self.published_at,
            "query_ids": list(self.query_ids),
            "intents": list(self.intents),
            "providers": list(self.providers),
            "first_seen_rank": self.first_seen_rank,
            "parent_lead_candidate_id": self.parent_lead_candidate_id,
            "discovery_method": self.discovery_method,
            "discovery_depth": self.discovery_depth,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RuntimeCandidate":
        compatible = dict(raw)
        # Slice 2 added lead-discovery provenance. Pre-Slice-2 cursors have no
        # provenance fields; accept only those absent fields so a durable
        # checkpoint survives the upgrade.
        compatible.setdefault("parent_lead_candidate_id", "")
        compatible.setdefault("discovery_method", "")
        compatible.setdefault("discovery_depth", 0)
        data = _strict_mapping(
            compatible,
            {
                "id",
                "url",
                "title",
                "snippet",
                "source",
                "published_at",
                "query_ids",
                "intents",
                "providers",
                "first_seen_rank",
                "parent_lead_candidate_id",
                "discovery_method",
                "discovery_depth",
            },
            "runtime candidate",
        )
        return cls(
            id=_required_text(data.get("id"), 300, "candidate id"),
            url=_required_text(data.get("url"), 2000, "candidate url"),
            title=_required_text(data.get("title"), 500, "candidate title"),
            snippet=_optional_text(data.get("snippet"), 2000),
            source=_optional_text(data.get("source"), 200),
            published_at=_optional_text(data.get("published_at"), 100),
            query_ids=_text_tuple(data.get("query_ids"), 20, 300),
            intents=_text_tuple(data.get("intents"), 20, 100),
            providers=_text_tuple(data.get("providers"), 20, 100),
            first_seen_rank=_bounded_int(
                data.get("first_seen_rank"), 0, 10000, "first_seen_rank"
            ),
            parent_lead_candidate_id=_optional_text(
                data.get("parent_lead_candidate_id"), 300
            ),
            discovery_method=_optional_text(data.get("discovery_method"), 50),
            discovery_depth=_bounded_int(
                data.get("discovery_depth"), 0, 5, "discovery_depth"
            ),
        )


@dataclass(frozen=True)
class RuntimeReadOutcome:
    candidate_id: str
    status: str
    evidence_id: str = ""
    content_chars: int = 0
    error_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status,
            "evidence_id": self.evidence_id,
            "content_chars": self.content_chars,
            "error_code": self.error_code,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RuntimeReadOutcome":
        data = _strict_mapping(
            raw,
            {"candidate_id", "status", "evidence_id", "content_chars", "error_code"},
            "runtime read outcome",
        )
        status = _required_text(data.get("status"), 50, "read status")
        if status not in _READ_STATUSES:
            raise ValueError("invalid runtime read status")
        return cls(
            candidate_id=_required_text(
                data.get("candidate_id"), 300, "candidate id"
            ),
            status=status,
            evidence_id=_optional_text(data.get("evidence_id"), 300),
            content_chars=_bounded_int(
                data.get("content_chars"), 0, 10_000_000, "content_chars"
            ),
            error_code=_optional_text(data.get("error_code"), 200),
        )


@dataclass(frozen=True)
class RuntimeFailure:
    code: str
    phase: str
    item_id: str = ""
    # v2 durable fields (frozen 7A): failure_id is the deterministic
    # exactly-once identity; detail / provider_code / exception_type /
    # attempt_id carry the dynamic specifics that must never become codes.
    failure_id: str = ""
    detail: str = ""
    provider_code: str = ""
    exception_type: str = ""
    attempt_id: str = ""
    # In-memory marker for values read from legacy cursors; never serialized.
    # Legacy rows keep their raw code and are never normalized (frozen 7A).
    legacy_input: bool = False

    def to_dict(
        self, schema_version: str = RESEARCH_RUNTIME_SCHEMA_VERSION
    ) -> dict[str, Any]:
        if schema_version not in SUPPORTED_RESEARCH_RUNTIME_SCHEMA_VERSIONS:
            raise ValueError("unsupported research runtime schema")
        if schema_version == RESEARCH_RUNTIME_SCHEMA_VERSION_V2:
            return {
                "failure_id": self.failure_id,
                "code": self.code,
                "phase": self.phase,
                "item_id": self.item_id,
                "detail": self.detail,
                "provider_code": self.provider_code,
                "exception_type": self.exception_type,
                "attempt_id": self.attempt_id,
            }
        # v1 wire shape stays exactly the original three fields so Batch A can
        # never silently migrate a durable cursor (frozen 7A).
        return {"code": self.code, "phase": self.phase, "item_id": self.item_id}

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, Any],
        *,
        schema_version: str = RESEARCH_RUNTIME_SCHEMA_VERSION,
    ) -> "RuntimeFailure":
        # The version is an explicit contract boundary, never guessed from the
        # field set: a v1 cursor must only carry 3-field failures and a v2
        # cursor only 8-field ones (frozen 7A).  Forward compatibility applies
        # to the code *value*, not to the wire shape.
        if schema_version not in SUPPORTED_RESEARCH_RUNTIME_SCHEMA_VERSIONS:
            raise ValueError("unsupported research runtime schema")
        if not isinstance(raw, Mapping):
            raise TypeError("runtime failure must be an object")
        if schema_version == RESEARCH_RUNTIME_SCHEMA_VERSION_V2:
            data = _strict_mapping(
                raw,
                {
                    "failure_id",
                    "code",
                    "phase",
                    "item_id",
                    "detail",
                    "provider_code",
                    "exception_type",
                    "attempt_id",
                },
                "runtime failure",
            )
            phase = _required_text(data.get("phase"), 50, "failure phase")
            if phase not in _PHASES:
                raise ValueError("invalid runtime failure phase")
            # The v2 reader stays forward compatible: unknown future codes are
            # readable and only the writer-side validator rejects them.
            return cls(
                failure_id=_required_text(
                    data.get("failure_id"), 300, "failure id"
                ),
                code=_required_text(data.get("code"), 200, "failure code"),
                phase=phase,
                item_id=_optional_text(data.get("item_id"), 300),
                detail=_optional_text(data.get("detail"), 2000),
                provider_code=_optional_text(data.get("provider_code"), 200),
                exception_type=_optional_text(data.get("exception_type"), 200),
                attempt_id=_optional_text(data.get("attempt_id"), 300),
                legacy_input=False,
            )
        data = _strict_mapping(raw, {"code", "phase", "item_id"}, "runtime failure")
        phase = _required_text(data.get("phase"), 50, "failure phase")
        if phase not in _PHASES:
            raise ValueError("invalid runtime failure phase")
        # v1 rows keep their raw code untouched (frozen 7A): no normalization,
        # no catalog validation, never merged with other legacy rows.
        return cls(
            code=_required_text(data.get("code"), 200, "failure code"),
            phase=phase,
            item_id=_optional_text(data.get("item_id"), 300),
            legacy_input=True,
        )


def build_runtime_failure(
    *,
    failure_id: str,
    code: ResearchFailureCode,
    phase: RuntimePhase,
    item_id: str = "",
    detail: str = "",
    provider_code: str = "",
    exception_type: str = "",
    attempt_id: str = "",
) -> RuntimeFailure:
    """Canonical v2 failure factory for production writers (Batch B onward).

    Validates catalog membership, requires a deterministic failure_id, and
    bounds every free-text field so dynamic provider/Python specifics never
    leak into the durable code (frozen 3A/9A).  Never used by readers.
    """
    require_research_failure_code(code)
    if not isinstance(failure_id, str) or not failure_id:
        raise ValueError("failure id must be non-empty")
    return RuntimeFailure(
        failure_id=failure_id,
        code=code,
        phase=phase,
        item_id=_optional_text(item_id, 300),
        detail=_optional_text(detail, 2000),
        provider_code=_optional_text(provider_code, 200),
        exception_type=_optional_text(exception_type, 200),
        attempt_id=_optional_text(attempt_id, 300),
        legacy_input=False,
    )


def runtime_failure_id(*, logical_call_id: str, code: str) -> str:
    """Deterministic exactly-once identity for one logical attempt (8A).

    Same logical call + same canonical code always produce the same id; a new
    attempt produces a new id.  Random ids are forbidden.
    """
    return _failure_id_from_parts(logical_call_id, code)


def runtime_failure_id_unattached(
    *, phase: str, item_id: str, attempt_id: str, code: str
) -> str:
    """Fallback identity when no logical call id exists (frozen 8A)."""
    return _failure_id_from_parts(phase, item_id, attempt_id, code)


def _failure_id_from_parts(*parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"failure:{digest}"


def append_runtime_failure(
    failures: tuple[RuntimeFailure, ...],
    failure: RuntimeFailure,
) -> tuple[RuntimeFailure, ...]:
    """Append by failure_id; exactly-once for durable ids (frozen 8A).

    Legacy failures (empty failure_id) are never deduplicated: historical
    rows may represent genuinely different attempts with identical
    (code, phase, item_id) triples.
    """
    if failure.failure_id and any(
        item.failure_id == failure.failure_id for item in failures
    ):
        return failures
    return (*failures, failure)


@dataclass(frozen=True)
class RuntimeExternalAttemptStart:
    """Durable pre-call marker for a read-only external operation.

    A process crash can leave the remote side completed while the local result
    was never checkpointed.  The marker therefore records an unknown attempt;
    it is never interpreted as proof that the external call did not happen.
    """

    call_id: str
    purpose: RuntimeExternalPurpose
    item_id: str
    attempt: int
    started_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "purpose": self.purpose,
            "item_id": self.item_id,
            "attempt": self.attempt,
            "started_at": self.started_at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RuntimeExternalAttemptStart":
        data = _strict_mapping(
            raw,
            {"call_id", "purpose", "item_id", "attempt", "started_at"},
            "runtime external attempt",
        )
        purpose = _required_text(data.get("purpose"), 50, "external purpose")
        if purpose not in {"search", "read"}:
            raise ValueError("invalid runtime external purpose")
        return cls(
            call_id=_required_text(data.get("call_id"), 300, "external call id"),
            purpose=purpose,  # type: ignore[arg-type]
            item_id=_required_text(data.get("item_id"), 300, "external item id"),
            attempt=_bounded_int(data.get("attempt"), 1, 2, "external attempt"),
            started_at=_required_text(data.get("started_at"), 100, "external started_at"),
        )


@dataclass(frozen=True)
class ResearchRuntimeCursor:
    round_index: int = 0
    phase: RuntimePhase = "bootstrap"
    planned_queries: tuple[RuntimePlannedQuery, ...] = ()
    query_outcomes: tuple[RuntimeQueryOutcome, ...] = ()
    candidates: tuple[RuntimeCandidate, ...] = ()
    planned_read_ids: tuple[str, ...] = ()
    read_outcomes: tuple[RuntimeReadOutcome, ...] = ()
    model_calls: tuple[ResearchModelCallAudit, ...] = ()
    inflight_model_call: ResearchModelAttemptStart | None = None
    inflight_external_call: RuntimeExternalAttemptStart | None = None
    failures: tuple[RuntimeFailure, ...] = ()
    # P1-C batch 2: durable multi-wave state. wave_index counts the wave the
    # executor is currently running (0 = before the first wave marker);
    # wave_id is the deterministic wave identity; active_gap_ids freezes which
    # gaps the wave decided to attempt (handled-truth: a gap is handled and
    # no-gain whenever its wave strategy ran, even if the planner only
    # produced duplicate queries or search found nothing new); gain_history
    # holds one serialized EvidenceGainResult per completed wave; the two
    # counters mirror SaturationState's per-gap/per-claim no-gain batches so a
    # crash between waves resumes at the right saturation point.
    wave_index: int = 0
    wave_id: str = ""
    active_gap_ids: tuple[str, ...] = ()
    gain_history: tuple[dict[str, Any], ...] = ()
    no_gain_batches_by_claim: dict[str, int] = field(default_factory=dict)
    no_gain_batches_by_gap: dict[str, int] = field(default_factory=dict)
    # Lead discovery (Slice 1): bounded lead reads and their discovery assets.
    # Leads are discovery assets, never evidence: the durable cursor stores the
    # typed LeadDiscoveryPayload only, and lead reads spend the same shared
    # read/model budget as evidence reads.
    lead_read_ids: tuple[str, ...] = ()
    lead_discoveries: tuple[dict[str, Any], ...] = ()
    # Evidence Lead Follow-up: an eligible evidence link with relation="lead"
    # means the read page did not answer the claim but points deeper. Bounded
    # per wave/run; consumes the already-read content (never re-reads).
    evidence_lead_followups: tuple[dict[str, Any], ...] = ()
    schema_version: str = RESEARCH_RUNTIME_SCHEMA_VERSION

    @property
    def completed_query_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.query_id for item in self.query_outcomes))

    @property
    def completed_read_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.candidate_id for item in self.read_outcomes))

    def to_dict(self) -> dict[str, Any]:
        # The cursor serializer never fails open on an unknown schema version:
        # an unsupported top-level version would otherwise emit its own
        # version next to a v1-shaped failure payload (frozen 7A).
        if self.schema_version not in SUPPORTED_RESEARCH_RUNTIME_SCHEMA_VERSIONS:
            raise ValueError("unsupported research runtime schema")
        return {
            "schema_version": self.schema_version,
            "round_index": self.round_index,
            "phase": self.phase,
            "planned_queries": [item.to_dict() for item in self.planned_queries],
            "query_outcomes": [item.to_dict() for item in self.query_outcomes],
            "candidates": [item.to_dict() for item in self.candidates],
            "planned_read_ids": list(self.planned_read_ids),
            "read_outcomes": [item.to_dict() for item in self.read_outcomes],
            "model_calls": [item.to_dict() for item in self.model_calls],
            "inflight_model_call": (
                self.inflight_model_call.to_dict() if self.inflight_model_call else None
            ),
            "inflight_external_call": (
                self.inflight_external_call.to_dict()
                if self.inflight_external_call
                else None
            ),
            "failures": [
                item.to_dict(self.schema_version) for item in self.failures
            ],
            "wave_index": self.wave_index,
            "wave_id": self.wave_id,
            "active_gap_ids": list(self.active_gap_ids),
            "gain_history": [dict(item) for item in self.gain_history],
            "no_gain_batches_by_claim": dict(self.no_gain_batches_by_claim),
            "no_gain_batches_by_gap": dict(self.no_gain_batches_by_gap),
            "lead_read_ids": list(self.lead_read_ids),
            "lead_discoveries": [dict(item) for item in self.lead_discoveries],
            "evidence_lead_followups": [
                dict(item) for item in self.evidence_lead_followups
            ],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResearchRuntimeCursor":
        # B5 added the external pre-call marker to the existing v1 cursor.  A
        # pre-B5 cursor has no such call in flight; accept only that one absent
        # field so a durable checkpoint is not made unreadable by the upgrade.
        compatible = dict(raw)
        compatible.setdefault("inflight_external_call", None)
        # P1-C batch 2 added durable multi-wave fields. Pre-batch-2 cursors
        # have none of them; accept only those absent fields so a durable
        # checkpoint survives the upgrade.
        compatible.setdefault("wave_index", 0)
        compatible.setdefault("wave_id", "")
        compatible.setdefault("active_gap_ids", [])
        compatible.setdefault("gain_history", [])
        compatible.setdefault("no_gain_batches_by_claim", {})
        compatible.setdefault("no_gain_batches_by_gap", {})
        # Slice 1 added bounded lead discovery. Pre-Slice-1 cursors have no
        # lead state; accept only those absent fields so durable checkpoints
        # survive the upgrade.
        compatible.setdefault("lead_read_ids", [])
        compatible.setdefault("lead_discoveries", [])
        compatible.setdefault("evidence_lead_followups", [])
        data = _strict_mapping(
            compatible,
            {
                "schema_version",
                "round_index",
                "phase",
                "planned_queries",
                "query_outcomes",
                "candidates",
                "planned_read_ids",
                "read_outcomes",
                "model_calls",
                "inflight_model_call",
                "inflight_external_call",
                "failures",
                "wave_index",
                "wave_id",
                "active_gap_ids",
                "gain_history",
                "no_gain_batches_by_claim",
                "no_gain_batches_by_gap",
                "lead_read_ids",
                "lead_discoveries",
                "evidence_lead_followups",
            },
            "research runtime cursor",
        )
        if data.get("schema_version") not in SUPPORTED_RESEARCH_RUNTIME_SCHEMA_VERSIONS:
            raise ValueError("unsupported research runtime schema")
        phase = _required_text(data.get("phase"), 50, "runtime phase")
        if phase not in _PHASES:
            raise ValueError("invalid research runtime phase")
        planned_queries = _object_tuple(
            data.get("planned_queries"), RuntimePlannedQuery.from_dict, "planned_queries"
        )
        query_outcomes = _object_tuple(
            data.get("query_outcomes"), RuntimeQueryOutcome.from_dict, "query_outcomes"
        )
        candidates = _object_tuple(
            data.get("candidates"), RuntimeCandidate.from_dict, "candidates"
        )
        read_outcomes = _object_tuple(
            data.get("read_outcomes"), RuntimeReadOutcome.from_dict, "read_outcomes"
        )
        model_calls = _object_tuple(
            data.get("model_calls"), ResearchModelCallAudit.from_dict, "model_calls"
        )
        failures = _object_tuple(
            data.get("failures"),
            lambda item: RuntimeFailure.from_dict(
                item, schema_version=str(data.get("schema_version"))
            ),
            "failures",
        )
        inflight_raw = data.get("inflight_model_call")
        inflight = (
            None
            if inflight_raw is None
            else ResearchModelAttemptStart.from_dict(
                _as_mapping(inflight_raw, "inflight_model_call")
            )
        )
        external_raw = data.get("inflight_external_call")
        external_inflight = (
            None
            if external_raw is None
            else RuntimeExternalAttemptStart.from_dict(
                _as_mapping(external_raw, "inflight_external_call")
            )
        )
        cursor = cls(
            # Keep the durable schema version on load so a v2 cursor
            # reserializes as v2 and a v1 cursor stays v1 (no silent
            # migration, frozen 7A).
            schema_version=str(data.get("schema_version")),
            round_index=_bounded_int(data.get("round_index"), 0, 1000, "round_index"),
            phase=phase,  # type: ignore[arg-type]
            planned_queries=planned_queries,
            query_outcomes=query_outcomes,
            candidates=candidates,
            planned_read_ids=_text_tuple(
                data.get("planned_read_ids"), _MAX_CURSOR_ITEMS, 300
            ),
            read_outcomes=read_outcomes,
            model_calls=model_calls,
            inflight_model_call=inflight,
            inflight_external_call=external_inflight,
            failures=failures,
            wave_index=_bounded_int(data.get("wave_index"), 0, 1000, "wave_index"),
            wave_id=_optional_text(data.get("wave_id"), 300),
            active_gap_ids=_text_tuple(
                data.get("active_gap_ids"), _MAX_CURSOR_ITEMS, 300
            ),
            gain_history=tuple(
                # P1-C batch 2: each history entry is the frozen
                # EvidenceGainResult contract, strictly restored (R7/R10/R11
                # fail-closed semantics apply at the durable cursor layer too).
                EvidenceGainResult.from_dict(item).to_dict()
                for item in _object_list(data.get("gain_history"), "gain_history")[
                    -_MAX_GAIN_HISTORY_ENTRIES:
                ]
            ),
            no_gain_batches_by_claim=dict(
                SaturationState.from_dict(
                    {
                        "no_gain_batches_by_claim": data.get(
                            "no_gain_batches_by_claim", {}
                        ),
                        "no_gain_batches_by_gap": data.get(
                            "no_gain_batches_by_gap", {}
                        ),
                    }
                ).no_gain_batches_by_claim
            ),
            no_gain_batches_by_gap=dict(
                SaturationState.from_dict(
                    {
                        "no_gain_batches_by_claim": data.get(
                            "no_gain_batches_by_claim", {}
                        ),
                        "no_gain_batches_by_gap": data.get(
                            "no_gain_batches_by_gap", {}
                        ),
                    }
                ).no_gain_batches_by_gap
            ),
            lead_read_ids=_text_tuple(
                data.get("lead_read_ids"), _MAX_CURSOR_ITEMS, 300
            ),
            lead_discoveries=tuple(
                LeadDiscoveryPayload.from_dict(item).to_dict()
                for item in _object_list(
                    data.get("lead_discoveries"), "lead_discoveries"
                )[-_MAX_LEAD_DISCOVERIES:]
            ),
            evidence_lead_followups=tuple(
                _strict_mapping(
                    item,
                    {
                        "wave_index",
                        "evidence_id",
                        "source_candidate_id",
                        "method",
                        "added_candidate_ids",
                        "hint_domain",
                        "hint_terms",
                    },
                    "evidence lead follow-up",
                )
                for item in _object_list(
                    data.get("evidence_lead_followups"),
                    "evidence_lead_followups",
                )[-_MAX_EVIDENCE_LEAD_FOLLOWUPS:]
            ),
        )
        _validate_cursor_links(cursor)
        return cursor


@dataclass(frozen=True)
class RuntimeCursorLoadResult:
    status: RuntimeLoadStatus
    cursor: ResearchRuntimeCursor | None = None
    reason: str = ""

    @property
    def available(self) -> bool:
        return self.status == "available" and self.cursor is not None


def attach_runtime_cursor(
    research_context: Mapping[str, Any], cursor: ResearchRuntimeCursor
) -> dict[str, Any]:
    validated = ResearchRuntimeCursor.from_dict(cursor.to_dict())
    updated = dict(research_context)
    updated[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY] = validated.to_dict()
    return updated


def load_runtime_cursor(research_context: Mapping[str, Any]) -> RuntimeCursorLoadResult:
    if CLAIM_ENGINE_RUNTIME_CONTEXT_KEY not in research_context:
        return RuntimeCursorLoadResult(
            status="absent",
            reason="claim_engine_runtime_absent",
        )
    raw = research_context.get(CLAIM_ENGINE_RUNTIME_CONTEXT_KEY)
    if not isinstance(raw, Mapping):
        return RuntimeCursorLoadResult(
            status="unavailable",
            reason="invalid_claim_engine_runtime",
        )
    try:
        cursor = ResearchRuntimeCursor.from_dict(raw)
    except (TypeError, ValueError):
        return RuntimeCursorLoadResult(
            status="unavailable",
            reason="invalid_claim_engine_runtime",
        )
    return RuntimeCursorLoadResult(status="available", cursor=cursor)


def begin_model_attempt(
    cursor: ResearchRuntimeCursor,
    marker: ResearchModelAttemptStart,
) -> ResearchRuntimeCursor:
    if cursor.inflight_model_call is not None:
        raise ValueError("research runtime already has an inflight model call")
    return replace(cursor, inflight_model_call=marker)


def finish_model_attempt(
    cursor: ResearchRuntimeCursor,
    audit: ResearchModelCallAudit,
) -> ResearchRuntimeCursor:
    inflight = cursor.inflight_model_call
    if inflight is None or inflight.call_id != audit.call_id:
        raise ValueError("research model completion does not match inflight call")
    return replace(
        cursor,
        model_calls=(*cursor.model_calls, audit),
        inflight_model_call=None,
    )


def recover_interrupted_model_attempt(
    cursor: ResearchRuntimeCursor,
) -> ResearchRuntimeCursor:
    inflight = cursor.inflight_model_call
    if inflight is None:
        return cursor
    if cursor.schema_version == RESEARCH_RUNTIME_SCHEMA_VERSION_V1:
        # A v1 cursor can persist only (code, phase, item_id).  Preserve the
        # legacy interruption code so a recovery checkpoint followed by
        # another process death still advances the bounded attempt counter.
        failure = RuntimeFailure(
            code="interrupted_unknown",
            phase=cursor.phase,
            item_id=inflight.call_id,
        )
        return replace(
            cursor,
            inflight_model_call=None,
            failures=append_runtime_failure(cursor.failures, failure),
        )
    code: ResearchFailureCode
    if inflight.purpose == "research_claim_planning":
        code = "claim_planning_failed"
    elif inflight.purpose == "research_candidate_assessment":
        code = "assessment_failed"
    elif inflight.purpose == "research_evidence_extraction":
        code = "extraction_failed"
    else:
        code = "runtime_internal_failed"
    failure = build_runtime_failure(
        failure_id=runtime_failure_id(
            logical_call_id=inflight.call_id,
            code=code,
        ),
        code=code,
        phase=cursor.phase,
        item_id=inflight.call_id,
        detail="interrupted_unknown",
        attempt_id=inflight.call_id,
    )
    return replace(
        cursor,
        inflight_model_call=None,
        failures=append_runtime_failure(cursor.failures, failure),
    )


def begin_external_attempt(
    cursor: ResearchRuntimeCursor,
    marker: RuntimeExternalAttemptStart,
) -> ResearchRuntimeCursor:
    if cursor.inflight_external_call is not None:
        raise ValueError("research runtime already has an inflight external call")
    return replace(cursor, inflight_external_call=marker)


def finish_external_attempt(
    cursor: ResearchRuntimeCursor,
    *,
    call_id: str,
) -> ResearchRuntimeCursor:
    inflight = cursor.inflight_external_call
    if inflight is None or inflight.call_id != call_id:
        raise ValueError("research external completion does not match inflight call")
    return replace(cursor, inflight_external_call=None)


def recover_interrupted_external_attempt(
    cursor: ResearchRuntimeCursor,
) -> ResearchRuntimeCursor:
    inflight = cursor.inflight_external_call
    if inflight is None:
        return cursor
    if cursor.schema_version == RESEARCH_RUNTIME_SCHEMA_VERSION_V1:
        failure = RuntimeFailure(
            code="interrupted_unknown",
            phase=cursor.phase,
            item_id=inflight.call_id,
        )
        return replace(
            cursor,
            inflight_external_call=None,
            failures=append_runtime_failure(cursor.failures, failure),
        )
    code: ResearchFailureCode = (
        "search_failed" if inflight.purpose == "search" else "read_failed"
    )
    failure = build_runtime_failure(
        failure_id=runtime_failure_id(
            logical_call_id=inflight.call_id,
            code=code,
        ),
        code=code,
        phase=cursor.phase,
        item_id=inflight.call_id,
        detail="interrupted_unknown",
        attempt_id=inflight.call_id,
    )
    return replace(
        cursor,
        inflight_external_call=None,
        failures=append_runtime_failure(cursor.failures, failure),
    )


def _validate_cursor_links(cursor: ResearchRuntimeCursor) -> None:
    planned_query_ids = [item.id for item in cursor.planned_queries]
    if len(planned_query_ids) != len(set(planned_query_ids)):
        raise ValueError("runtime planned query ids must be unique")
    planned_query_set = set(planned_query_ids)
    if any(item.query_id not in planned_query_set for item in cursor.query_outcomes):
        raise ValueError("runtime query outcome references unknown query")
    if len(cursor.completed_query_ids) != len(cursor.query_outcomes):
        raise ValueError("runtime query outcomes must be unique per query")

    candidate_ids = [item.id for item in cursor.candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("runtime candidate ids must be unique")
    if any(
        query_id not in planned_query_set
        for item in cursor.candidates
        for query_id in item.query_ids
    ):
        raise ValueError("runtime candidate references unknown query")
    candidate_set = set(candidate_ids)
    if any(candidate_id not in candidate_set for candidate_id in cursor.planned_read_ids):
        raise ValueError("runtime read plan references unknown candidate")
    if any(item.candidate_id not in candidate_set for item in cursor.read_outcomes):
        raise ValueError("runtime read outcome references unknown candidate")
    if len(cursor.completed_read_ids) != len(cursor.read_outcomes):
        raise ValueError("runtime read outcomes must be unique per candidate")

    call_ids = [item.call_id for item in cursor.model_calls]
    if len(call_ids) != len(set(call_ids)):
        raise ValueError("runtime model audit call ids must be unique")
    if cursor.inflight_model_call and cursor.inflight_model_call.call_id in set(call_ids):
        raise ValueError("completed model call cannot remain inflight")
    if cursor.inflight_model_call and cursor.inflight_external_call:
        raise ValueError("model and external calls cannot both remain inflight")

    if len(cursor.gain_history) > cursor.wave_index:
        raise ValueError("runtime gain history cannot exceed wave index")
    if cursor.wave_index == 0 and (
        cursor.wave_id or cursor.active_gap_ids or cursor.gain_history
    ):
        raise ValueError("runtime pre-wave cursor cannot carry wave state")
    for item in cursor.gain_history:
        EvidenceGainResult.from_dict(item)


def _object_tuple(value: Any, parser: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, list) or len(value) > _MAX_CURSOR_ITEMS:
        raise ValueError(f"invalid {label}")
    return tuple(parser(_as_mapping(item, label)) for item in value)


def _object_list(value: Any, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or len(value) > _MAX_CURSOR_ITEMS:
        raise ValueError(f"invalid {label}")
    return [_as_mapping(item, label) for item in value]


def _counter_mapping(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or len(value) > _MAX_CURSOR_ITEMS:
        raise ValueError(f"invalid {label}")
    counters: dict[str, int] = {}
    for key, count in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"invalid {label} key")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"invalid {label} counter")
        counters[key] = count
    return counters


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} item must be an object")
    return value


def _strict_mapping(
    raw: Mapping[str, Any], allowed: set[str], label: str
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError(f"{label} must be an object")
    data = dict(raw)
    if set(data) != allowed:
        raise ValueError(f"{label} fields do not match schema")
    return data


def _required_text(value: Any, limit: int, label: str) -> str:
    text = _optional_text(value, limit)
    if not text:
        raise ValueError(f"{label} must be non-empty")
    return text


def _optional_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _bounded_int(value: Any, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{label} is out of range")
    return parsed


def _text_tuple(value: Any, max_items: int, item_limit: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > max_items:
        raise ValueError("invalid text sequence")
    values = tuple(_required_text(item, item_limit, "sequence item") for item in value)
    if len(values) != len(set(values)):
        raise ValueError("text sequence values must be unique")
    return values


__all__ = [
    "CLAIM_ENGINE_RUNTIME_CONTEXT_KEY",
    "LATEST_RESEARCH_RUNTIME_SCHEMA_VERSION",
    "RESEARCH_RUNTIME_SCHEMA_VERSION",
    "RESEARCH_RUNTIME_SCHEMA_VERSION_V1",
    "RESEARCH_RUNTIME_SCHEMA_VERSION_V2",
    "SUPPORTED_RESEARCH_RUNTIME_SCHEMA_VERSIONS",
    "ResearchRuntimeCursor",
    "RuntimeCandidate",
    "RuntimeCursorLoadResult",
    "RuntimeFailure",
    "RuntimeExternalAttemptStart",
    "RuntimePlannedQuery",
    "RuntimeQueryOutcome",
    "RuntimeReadOutcome",
    "append_runtime_failure",
    "attach_runtime_cursor",
    "begin_model_attempt",
    "begin_external_attempt",
    "build_runtime_failure",
    "finish_external_attempt",
    "finish_model_attempt",
    "load_runtime_cursor",
    "recover_interrupted_model_attempt",
    "recover_interrupted_external_attempt",
    "runtime_failure_id",
    "runtime_failure_id_unattached",
]
