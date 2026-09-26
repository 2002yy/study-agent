"""Strict production-side contract for batched candidate semantic assessment.

This boundary is intentionally independent from evaluation projectors.  The
classifier may label relevance and source role, but server-owned cluster IDs,
freshness and read-cost metadata are attached only after strict parsing.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.candidate_ranking import CandidateSemanticAssessment
from src.web.research.contracts import ResearchClaim
from src.web.research.source_cluster import CandidateClusterAssignment

CANDIDATE_ASSESSMENT_SCHEMA_VERSION = "candidate-assessment-v1"
CANDIDATE_ASSESSMENT_WIRE_SCHEMA_VERSION = "ca2"

CANDIDATE_ASSESSMENT_RELEVANCE_CODES = {
    0: "answer_relevant",
    1: "topic_only",
    2: "off_target",
    3: "unknown",
}
CANDIDATE_ASSESSMENT_SOURCE_ROLE_CODES = {
    0: "unknown",
    1: "primary",
    2: "authoritative_secondary",
    3: "independent_secondary",
    4: "community",
    5: "aggregator",
}
CANDIDATE_ASSESSMENT_GAIN_SIGNAL_CODES = {
    0: "new_primary",
    1: "new_independent_cluster",
    2: "new_contradiction",
    3: "new_provenance_lead",
    4: "freshness_update",
    5: "claim_status_improvement",
}

_RELEVANCE = {"answer_relevant", "topic_only", "off_target", "unknown"}
_SOURCE_ROLES = {
    "unknown",
    "primary",
    "authoritative_secondary",
    "independent_secondary",
    "community",
    "aggregator",
}
_GAIN_SIGNALS = {
    "new_primary",
    "new_independent_cluster",
    "new_contradiction",
    "new_provenance_lead",
    "freshness_update",
    "claim_status_improvement",
}
_ASSESSMENT_KEYS = {
    "candidate_id",
    "relevance",
    "relevance_confidence",
    "source_role",
    "source_role_confidence",
    "expected_gain_signals",
}
_COMPACT_ASSESSMENT_KEYS = {"i", "r", "rc", "s", "sc", "g"}


class CompactAssessmentEnvelopeError(ValueError):
    """Compact response envelope or version is invalid."""


class CompactAssessmentCoverageError(ValueError):
    """Compact response does not cover the requested candidate count."""


class CompactAssessmentRowError(ValueError):
    """Compact response row shape is invalid."""


class CompactAssessmentOrderError(ValueError):
    """Compact response indexes are not one consistent ordered sequence."""


class CompactAssessmentDomainError(ValueError):
    """Expanded response failed the stable semantic domain contract."""


class CompactAssessmentCodeError(ValueError):
    """Compact response contains an unknown or malformed enum code."""


class CompactAssessmentRelevanceCodeError(CompactAssessmentCodeError):
    """Compact relevance code is unknown or malformed."""


class CompactAssessmentSourceRoleCodeError(CompactAssessmentCodeError):
    """Compact source-role code is unknown or malformed."""


class CompactAssessmentGainSignalCodeError(CompactAssessmentCodeError):
    """Compact gain-signal code is unknown or malformed."""


class CompactAssessmentGainSignalDuplicateError(CompactAssessmentCodeError):
    """Legacy subtype retained for compatibility with older diagnostics."""


@dataclass(frozen=True)
class CandidateAssessmentRequest:
    schema_version: str
    claim_id: str
    claim_text: str
    required_source_roles: tuple[str, ...]
    requires_primary_source: bool
    requires_dated_evidence: bool
    candidates: tuple[dict[str, Any], ...]

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(str(item["candidate_id"]) for item in self.candidates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "claim": {
                "id": self.claim_id,
                "text": self.claim_text,
                "required_source_roles": list(self.required_source_roles),
                "requires_primary_source": self.requires_primary_source,
                "requires_dated_evidence": self.requires_dated_evidence,
            },
            "candidates": [dict(item) for item in self.candidates],
        }


def build_candidate_assessment_request(
    candidates: tuple[CandidatePoolItem, ...],
    *,
    claim: ResearchClaim,
) -> CandidateAssessmentRequest:
    """Build a bounded classifier request without raw page bodies."""

    if not candidates:
        raise ValueError("candidate assessment request cannot be empty")
    if len(candidates) > 100:
        raise ValueError("candidate assessment request exceeds 100 candidates")
    return CandidateAssessmentRequest(
        schema_version=CANDIDATE_ASSESSMENT_SCHEMA_VERSION,
        claim_id=claim.id,
        claim_text=_bounded_text(claim.text, 2000, required=True),
        required_source_roles=claim.evidence_requirement.source_roles,
        requires_primary_source=claim.evidence_requirement.requires_primary_source,
        requires_dated_evidence=claim.evidence_requirement.requires_dated_evidence,
        candidates=tuple(
            {
                "candidate_id": item.id,
                "title": _bounded_text(item.title, 500, required=True),
                "snippet": _bounded_text(item.snippet, 1200),
                "canonical_url": _bounded_text(item.canonical_url, 2000, required=True),
                "published_at": _bounded_text(item.published_at, 100),
                "query_intents": [intent.value for intent in item.intents],
            }
            for item in candidates
        ),
    )


def parse_candidate_assessment_response(
    payload: Mapping[str, Any],
    *,
    request: CandidateAssessmentRequest,
    cluster_assignments: Mapping[str, CandidateClusterAssignment],
    freshness_scores: Mapping[str, float] | None = None,
    read_costs: Mapping[str, float] | None = None,
) -> dict[str, CandidateSemanticAssessment]:
    """Strictly parse labels and attach server-owned scheduling metadata."""

    if set(payload) != {"schema_version", "assessments"}:
        raise ValueError("candidate assessment response has unknown or missing fields")
    if payload.get("schema_version") != CANDIDATE_ASSESSMENT_SCHEMA_VERSION:
        raise ValueError("candidate assessment schema version mismatch")
    raw_items = payload.get("assessments")
    if not isinstance(raw_items, list):
        raise ValueError("candidate assessments must be a list")
    expected = set(request.candidate_ids)
    if set(cluster_assignments) != expected:
        raise ValueError("server-owned cluster assignment coverage mismatch")
    parsed: dict[str, CandidateSemanticAssessment] = {}
    fresh = dict(freshness_scores or {})
    costs = dict(read_costs or {})
    if set(fresh) - expected or set(costs) - expected:
        raise ValueError("server-owned metadata references unknown candidates")
    for raw in raw_items:
        if not isinstance(raw, Mapping) or set(raw) != _ASSESSMENT_KEYS:
            raise ValueError("candidate assessment item has unknown or missing fields")
        candidate_id = _bounded_text(raw.get("candidate_id"), 200, required=True)
        if candidate_id not in expected or candidate_id in parsed:
            raise ValueError("candidate assessment contains unknown or duplicate candidate")
        relevance = _enum(raw.get("relevance"), _RELEVANCE, "relevance")
        source_role = _enum(raw.get("source_role"), _SOURCE_ROLES, "source_role")
        signals = _enum_tuple(
            raw.get("expected_gain_signals"),
            _GAIN_SIGNALS,
            "expected_gain_signals",
        )
        assignment = cluster_assignments[candidate_id]
        if assignment.candidate_id != candidate_id:
            raise ValueError("cluster assignment candidate_id mismatch")
        freshness = _unit_float(fresh.get(candidate_id, 0.0), "freshness_score")
        read_cost = _positive_float(costs.get(candidate_id, 1.0), "estimated_read_cost")
        parsed[candidate_id] = CandidateSemanticAssessment(
            candidate_id=candidate_id,
            relevance=relevance,  # type: ignore[arg-type]
            relevance_confidence=_unit_float(
                raw.get("relevance_confidence"),
                "relevance_confidence",
            ),
            source_role=source_role,
            source_role_confidence=_unit_float(
                raw.get("source_role_confidence"),
                "source_role_confidence",
            ),
            cluster_id=assignment.cluster_id,
            expected_gain_signals=signals,
            freshness_score=freshness,
            estimated_read_cost=read_cost,
        )
    if set(parsed) != expected:
        raise ValueError("candidate semantic assessment coverage mismatch")
    return parsed


def parse_compact_candidate_assessment_response(
    payload: Mapping[str, Any],
    *,
    request: CandidateAssessmentRequest,
    cluster_assignments: Mapping[str, CandidateClusterAssignment],
    freshness_scores: Mapping[str, float] | None = None,
    read_costs: Mapping[str, float] | None = None,
) -> dict[str, CandidateSemanticAssessment]:
    """Expand the compact model wire into the stable domain contract.

    Candidate identity never crosses the response boundary. Each row must use
    a consistent zero- or one-based request position, in order and with
    complete coverage; the server restores authoritative IDs before applying
    the existing strict semantic parser.
    """

    if set(payload) != {"v", "a"}:
        raise CompactAssessmentEnvelopeError("compact assessment envelope invalid")
    if payload.get("v") != CANDIDATE_ASSESSMENT_WIRE_SCHEMA_VERSION:
        raise CompactAssessmentEnvelopeError("compact assessment version invalid")
    rows = payload.get("a")
    if not isinstance(rows, list) or len(rows) != len(request.candidate_ids):
        raise CompactAssessmentCoverageError("compact assessment coverage invalid")
    indexes: list[int] = []
    for raw in rows:
        if not isinstance(raw, Mapping) or set(raw) != _COMPACT_ASSESSMENT_KEYS:
            raise CompactAssessmentRowError("compact assessment row invalid")
        index = raw.get("i")
        if isinstance(index, bool) or not isinstance(index, int):
            raise CompactAssessmentOrderError("compact assessment index invalid")
        indexes.append(index)
    zero_based = list(range(len(rows)))
    one_based = list(range(1, len(rows) + 1))
    if indexes == zero_based:
        index_base = 0
    elif indexes == one_based:
        index_base = 1
    else:
        raise CompactAssessmentOrderError("compact assessment order invalid")
    assessments: list[dict[str, Any]] = []
    for raw, index in zip(rows, indexes, strict=True):
        assessments.append(
            {
                "candidate_id": request.candidate_ids[index - index_base],
                "relevance": _compact_code(
                    raw.get("r"),
                    CANDIDATE_ASSESSMENT_RELEVANCE_CODES,
                    "relevance",
                    CompactAssessmentRelevanceCodeError,
                ),
                "relevance_confidence": raw.get("rc"),
                "source_role": _compact_code(
                    raw.get("s"),
                    CANDIDATE_ASSESSMENT_SOURCE_ROLE_CODES,
                    "source role",
                    CompactAssessmentSourceRoleCodeError,
                ),
                "source_role_confidence": raw.get("sc"),
                "expected_gain_signals": _compact_codes(
                    raw.get("g"), CANDIDATE_ASSESSMENT_GAIN_SIGNAL_CODES
                ),
            }
        )
    try:
        return parse_candidate_assessment_response(
            {
                "schema_version": CANDIDATE_ASSESSMENT_SCHEMA_VERSION,
                "assessments": assessments,
            },
            request=request,
            cluster_assignments=cluster_assignments,
            freshness_scores=freshness_scores,
            read_costs=read_costs,
        )
    except ValueError as exc:
        raise CompactAssessmentDomainError(
            "compact assessment domain validation failed"
        ) from exc


def _compact_code(
    value: Any,
    codes: Mapping[int, str],
    label: str,
    error_type: type[CompactAssessmentCodeError] = CompactAssessmentCodeError,
) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value not in codes:
        raise error_type(f"compact {label} code invalid")
    return codes[value]


def _compact_codes(value: Any, codes: Mapping[int, str]) -> list[str]:
    if not isinstance(value, list) or len(value) > len(codes):
        raise CompactAssessmentGainSignalCodeError("compact gain signal codes invalid")
    result: list[str] = []
    for item in value:
        decoded = _compact_code(
            item,
            codes,
            "gain signal",
            CompactAssessmentGainSignalCodeError,
        )
        if decoded not in result:
            result.append(decoded)
    return result


def _bounded_text(value: Any, limit: int, *, required: bool = False) -> str:
    text = " ".join(str(value or "").split())[:limit]
    if required and not text:
        raise ValueError("required assessment text is empty")
    return text


def _enum(value: Any, allowed: set[str], label: str) -> str:
    text = _bounded_text(value, 100, required=True).casefold()
    if text not in allowed:
        raise ValueError(f"invalid {label}: {text}")
    return text


def _enum_tuple(value: Any, allowed: set[str], label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > len(allowed):
        raise ValueError(f"{label} must be a bounded list")
    result = tuple(dict.fromkeys(_enum(item, allowed, label) for item in value))
    return result


def _unit_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{label} must be between 0 and 1")
    return number


def _positive_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be positive")
    return number


__all__ = [
    "CANDIDATE_ASSESSMENT_SCHEMA_VERSION",
    "CANDIDATE_ASSESSMENT_WIRE_SCHEMA_VERSION",
    "CANDIDATE_ASSESSMENT_GAIN_SIGNAL_CODES",
    "CANDIDATE_ASSESSMENT_RELEVANCE_CODES",
    "CANDIDATE_ASSESSMENT_SOURCE_ROLE_CODES",
    "CompactAssessmentCoverageError",
    "CompactAssessmentCodeError",
    "CompactAssessmentDomainError",
    "CompactAssessmentGainSignalCodeError",
    "CompactAssessmentGainSignalDuplicateError",
    "CompactAssessmentRelevanceCodeError",
    "CompactAssessmentSourceRoleCodeError",
    "CompactAssessmentEnvelopeError",
    "CompactAssessmentOrderError",
    "CompactAssessmentRowError",
    "CandidateAssessmentRequest",
    "build_candidate_assessment_request",
    "parse_compact_candidate_assessment_response",
    "parse_candidate_assessment_response",
]
