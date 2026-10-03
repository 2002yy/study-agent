"""Strict model boundaries used by the active single-wave research runtime.

The model may classify candidate semantics and extract bounded claim links. It
cannot mint candidate, cluster, claim, or evidence identities, and it cannot
turn an unread page or a malformed response into eligible evidence.
"""

from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import dataclass
from datetime import date
import json
from math import isfinite
from os import getenv
from typing import Any, Mapping

from openai import OpenAI

from src.llm_client import (
    get_client,
    research_structured_output_capabilities,
)
from src.web.research.candidate_assessment import (
    CANDIDATE_ASSESSMENT_GAIN_SIGNAL_CODES,
    CANDIDATE_ASSESSMENT_RELEVANCE_CODES,
    CANDIDATE_ASSESSMENT_SOURCE_ROLE_CODES,
    CANDIDATE_ASSESSMENT_WIRE_SCHEMA_VERSION,
    build_candidate_assessment_request,
    parse_compact_candidate_assessment_response,
)
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.candidate_ranking import CandidateSemanticAssessment
from src.web.research.contracts import ResearchClaim
from src.web.research.model_gateway import (
    AttemptFinishedHook,
    AttemptStartedHook,
    ResearchModelCallAudit,
    ResearchModelGateway,
    merge_research_extra_body,
    with_json_object_contract,
)
from src.web.research.source_cluster import CandidateClusterAssignment

EVIDENCE_EXTRACTION_SCHEMA_VERSION = "research-evidence-extraction-v1"
CANDIDATE_ASSESSMENT_MAX_ATTEMPTS_PER_INVOCATION = 1
CANDIDATE_ASSESSMENT_TIMEOUT_SECONDS = 15.0
CANDIDATE_ASSESSMENT_BASE_MAX_TOKENS = 100
CANDIDATE_ASSESSMENT_MAX_TOKENS_PER_CANDIDATE = 100
CANDIDATE_ASSESSMENT_WINDOW_MAX_TOKENS = 220

_ASSESSMENT_SYSTEM_PROMPT = """You classify public web search candidates for one research claim.
Return strict compact JSON matching ca2. Return one row per input candidate, in input order;
i is its zero- or one-based array position; use one convention consistently for all rows.
Use integer codes: r relevance 0=answer_relevant 1=topic_only 2=off_target 3=unknown;
s source role 0=unknown 1=primary 2=authoritative_secondary 3=independent_secondary
4=community 5=aggregator; g gain signals 0=new_primary 1=new_independent_cluster
2=new_contradiction 3=new_provenance_lead 4=freshness_update 5=claim_status_improvement.
rc and sc are confidences from 0 to 1.
This is pre-read lead triage: judge whether opening the candidate page could produce evidence,
not whether the bounded search snippet already proves the claim. If title, snippet, or URL
plausibly points to a claim-bearing page but metadata is insufficient, use topic_only or unknown
and include new_provenance_lead. Use off_target only for a clear mismatch. Leave
expected_gain_signals empty only when reading has no plausible evidence or provenance gain.
Do not invent URLs, candidate indexes, publication dates, source clusters, or evidence."""

_EXTRACTION_SYSTEM_PROMPT = """You extract one bounded evidence link from a successfully read public page.
Return strict JSON matching research-evidence-extraction-v1. Use only the supplied page excerpt.
Echo candidate_id, claim_id, source_role, source_cluster_id, and published_at exactly.
The relation must be supports, contradicts, qualifies, background, or lead. The locator and
anchored_spans must be short verbatim anchors present in the supplied excerpt. If the excerpt
does not bear on the claim, use relation=lead with low strength; never invent evidence."""

_RELATIONS = {"supports", "contradicts", "qualifies", "background", "lead"}

_SOURCE_ROLES = {
    "primary",
    "authoritative_secondary",
    "independent_secondary",
    "community",
    "aggregator",
}
_CANDIDATE_ASSESSMENT_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "research_candidate_assessment_compact",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["v", "a"],
            "properties": {
                "v": {
                    "type": "string",
                    "enum": [CANDIDATE_ASSESSMENT_WIRE_SCHEMA_VERSION],
                },
                "a": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 100,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "i",
                            "r",
                            "rc",
                            "s",
                            "sc",
                            "g",
                        ],
                        "properties": {
                            "i": {"type": "integer", "minimum": 0, "maximum": 100},
                            "r": {
                                "type": "integer",
                                "enum": list(CANDIDATE_ASSESSMENT_RELEVANCE_CODES),
                            },
                            "rc": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "s": {
                                "type": "integer",
                                "enum": list(CANDIDATE_ASSESSMENT_SOURCE_ROLE_CODES),
                            },
                            "sc": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "g": {
                                "type": "array",
                                "maxItems": len(CANDIDATE_ASSESSMENT_GAIN_SIGNAL_CODES),
                                "uniqueItems": True,
                                "items": {
                                    "type": "integer",
                                    "enum": list(CANDIDATE_ASSESSMENT_GAIN_SIGNAL_CODES),
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}
_EXTRACTION_FIELDS = {
    "schema_version",
    "candidate_id",
    "claim_id",
    "source_role",
    "source_cluster_id",
    "relation",
    "strength",
    "locator",
    "anchored_spans",
    "caveats",
    "published_at",
}

# For providers without wire-level json_schema (e.g. DeepSeek), the extraction
# call runs on json_object transport, so the exact output contract must be
# carried in the prompt. Derived from the real field set/enums to avoid drift.
# The strict _parse_extraction keeps final authority in all transports.
_JSON_OBJECT_EXTRACTION_CONTRACT = (
    "\n\nOutput contract (STRICT, must match exactly):\n"
    "Return ONE JSON object with EXACTLY these top-level keys and no others:\n"
    + json.dumps(sorted(_EXTRACTION_FIELDS), ensure_ascii=False)
    + "\n"
    + f'- "schema_version" must be exactly "{EVIDENCE_EXTRACTION_SCHEMA_VERSION}".\n'
    + "- Echo candidate_id, claim_id, source_role, source_cluster_id, and "
    "published_at exactly as supplied.\n"
    + f'- "relation" must be one of {json.dumps(sorted(_RELATIONS))}.\n'
    + '- "strength" is a number between 0 and 1.\n'
    + '- "locator" and every entry of "anchored_spans" must be short verbatim '
    "substrings of the supplied page excerpt.\n"
    + '- "caveats" is an array of strings (use an empty array when there are none).\n'
    + "Never add keys from the input envelope (such as claim_text or page) and "
    "never omit any listed key."
)


@dataclass(frozen=True)
class CandidateAssessmentResult:
    status: str
    assessments: Mapping[str, CandidateSemanticAssessment]
    audits: tuple[ResearchModelCallAudit, ...]
    reason: str = ""


@dataclass(frozen=True)
class ExtractedEvidenceLink:
    candidate_id: str
    claim_id: str
    source_role: str
    source_cluster_id: str
    relation: str
    strength: float
    locator: str
    anchored_spans: tuple[str, ...]
    caveats: tuple[str, ...]
    published_at: str = ""


@dataclass(frozen=True)
class EvidenceExtractionResult:
    status: str
    extraction: ExtractedEvidenceLink | None
    audits: tuple[ResearchModelCallAudit, ...]
    reason: str = ""


class _CandidateAssessorCompletions:
    """Inject the assessment structured-output transport per provider capability.

    Wire-level ``json_schema`` providers keep the strict schema response_format.
    ``json_object``-only providers (e.g. DeepSeek) carry the same dynamic schema
    (rows pinned to the candidate count) as a system-prompt contract and disable
    provider-side thinking; ``parse_compact_candidate_assessment_response`` keeps
    final authority either way.
    """

    def __init__(self, inner: Any, *, provider_profile: str) -> None:
        self._inner = inner
        self._provider_profile = provider_profile
        mode, thinking_off = research_structured_output_capabilities(provider_profile)
        self._wire_json_schema = mode == "json_schema"
        self._thinking_off_extra_body = thinking_off

    def create(self, **kwargs: Any) -> Any:
        messages = kwargs.get("messages")
        if (
            not isinstance(messages, list)
            or not messages
            or not isinstance(messages[-1], Mapping)
        ):
            raise ValueError("candidate assessment request messages invalid")
        try:
            request_payload = json.loads(str(messages[-1]["content"]))
            candidate_count = len(request_payload["candidates"])
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("candidate assessment request envelope invalid") from exc
        if not 1 <= candidate_count <= 100:
            raise ValueError("candidate assessment request count invalid")
        if self._wire_json_schema:
            response_format = deepcopy(_CANDIDATE_ASSESSMENT_RESPONSE_FORMAT)
            rows_schema = response_format["json_schema"]["schema"]["properties"]["a"]
            rows_schema["minItems"] = candidate_count
            rows_schema["maxItems"] = candidate_count
            kwargs["response_format"] = response_format
            return self._inner.create(**kwargs)
        schema = deepcopy(_CANDIDATE_ASSESSMENT_RESPONSE_FORMAT["json_schema"]["schema"])
        rows_schema = schema["properties"]["a"]
        rows_schema["minItems"] = candidate_count
        rows_schema["maxItems"] = candidate_count
        kwargs["messages"] = with_json_object_contract(messages, schema)
        merged = merge_research_extra_body(
            kwargs.get("extra_body"), self._thinking_off_extra_body
        )
        if merged is not None:
            kwargs["extra_body"] = merged
        return self._inner.create(**kwargs)


class _CandidateAssessorChat:
    def __init__(self, inner: Any, *, provider_profile: str) -> None:
        self.completions = _CandidateAssessorCompletions(
            inner.completions, provider_profile=provider_profile
        )


class _CandidateAssessorClient:
    """Inject strict assessment JSON Schema while preserving lazy clients."""

    def __init__(self, inner: Any, *, provider_profile: str) -> None:
        self._inner = inner
        self._provider_profile = provider_profile

    @property
    def chat(self) -> _CandidateAssessorChat:
        return _CandidateAssessorChat(
            self._resolved_inner().chat, provider_profile=self._provider_profile
        )

    def with_options(self, **kwargs: Any) -> _CandidateAssessorClient:
        return _CandidateAssessorClient(
            self._resolved_inner().with_options(**kwargs),
            provider_profile=self._provider_profile,
        )

    def _resolved_inner(self) -> Any:
        if self._inner is not None:
            return self._inner
        return get_client(provider_profile=self._provider_profile)


class RuntimeCandidateAssessor:
    def __init__(
        self,
        model_gateway: ResearchModelGateway,
        *,
        timeout_cap_seconds: float = CANDIDATE_ASSESSMENT_TIMEOUT_SECONDS,
    ) -> None:
        if isinstance(timeout_cap_seconds, bool):
            raise ValueError("candidate assessment timeout cap must be positive")
        try:
            timeout_cap = float(timeout_cap_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "candidate assessment timeout cap must be positive"
            ) from exc
        if not isfinite(timeout_cap) or timeout_cap <= 0:
            raise ValueError("candidate assessment timeout cap must be positive")
        self._durable_max_attempts = model_gateway.max_attempts
        self.timeout_cap_seconds = timeout_cap
        self.model_gateway = _candidate_assessor_gateway(model_gateway)

    def assess(
        self,
        *,
        run_id: str,
        claim: ResearchClaim,
        candidates: tuple[CandidatePoolItem, ...],
        assignments: Mapping[str, CandidateClusterAssignment],
        reference_date: str,
        timeout_seconds: float | None = None,
        on_attempt_started: AttemptStartedHook | None = None,
        on_attempt_finished: AttemptFinishedHook | None = None,
        call_id_suffix: str = "",
        attempt_start: int = 1,
    ) -> CandidateAssessmentResult:
        if (
            isinstance(attempt_start, bool)
            or not isinstance(attempt_start, int)
            or attempt_start < 1
        ):
            raise ValueError("attempt_start must be a positive integer")
        if attempt_start > self._durable_max_attempts:
            return CandidateAssessmentResult(
                status="unavailable",
                assessments={},
                audits=(),
                reason="model_call_attempts_exhausted",
            )
        request = build_candidate_assessment_request(candidates, claim=claim)
        freshness = {
            item.id: _freshness_score(
                item.published_at,
                reference_date=reference_date,
                max_age_days=claim.evidence_requirement.max_age_days,
            )
            for item in candidates
        }
        payload = request.to_dict()
        # One invocation may spend only one physical request. Durable runtime
        # recovery can still resume the same logical call at attempt two, but
        # a slow assessment cannot consume both attempts and starve all reads
        # inside one 60-second run.
        call_gateway = copy(self.model_gateway)
        call_gateway.max_attempts = attempt_start
        assessment_timeout = self.timeout_cap_seconds
        if timeout_seconds is not None:
            assessment_timeout = min(assessment_timeout, float(timeout_seconds))
        result = call_gateway.complete_structured(
            logical_call_id=(
                f"research_candidate_assessment:{run_id}:{claim.id}:1{call_id_suffix}"
            ),
            purpose="research_candidate_assessment",
            messages=[
                {"role": "system", "content": _ASSESSMENT_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            audit_payload=payload,
            response_schema_version=CANDIDATE_ASSESSMENT_WIRE_SCHEMA_VERSION,
            parse=lambda raw: parse_compact_candidate_assessment_response(
                _mapping(raw, "candidate assessment response"),
                request=request,
                cluster_assignments=assignments,
                freshness_scores=freshness,
            ),
            data_categories=("public_research_claim", "public_candidate_metadata"),
            data_counts={
                "research_claim": 1,
                "candidate_metadata": len(candidates),
            },
            max_tokens=min(
                4000,
                CANDIDATE_ASSESSMENT_WINDOW_MAX_TOKENS,
                CANDIDATE_ASSESSMENT_BASE_MAX_TOKENS
                + len(candidates) * CANDIDATE_ASSESSMENT_MAX_TOKENS_PER_CANDIDATE,
            ),
            temperature=0.0,
            timeout_seconds=assessment_timeout,
            on_attempt_started=on_attempt_started,
            on_attempt_finished=on_attempt_finished,
            attempt_start=attempt_start,
        )
        if not result.completed or result.value is None:
            reason = result.reason
            if (
                reason == "model_call_attempts_exhausted"
                and attempt_start < self._durable_max_attempts
            ):
                reason = "candidate_assessment_attempt_failed"
            return CandidateAssessmentResult(
                status=result.status,
                assessments=result.value or {},
                audits=result.audits,
                reason=reason,
            )
        return CandidateAssessmentResult(
            status=result.status,
            assessments=result.value,
            audits=result.audits,
            reason=result.reason,
        )


def _candidate_assessor_gateway(
    shared: ResearchModelGateway,
) -> ResearchModelGateway:
    gateway = copy(shared)
    gateway.max_attempts = CANDIDATE_ASSESSMENT_MAX_ATTEMPTS_PER_INVOCATION

    base_url = (getenv("RESEARCH_CANDIDATE_ASSESSOR_BASE_URL") or "").strip()
    model_name = (getenv("RESEARCH_CANDIDATE_ASSESSOR_MODEL_NAME") or "").strip()
    api_key = (getenv("RESEARCH_CANDIDATE_ASSESSOR_API_KEY") or "").strip()
    dedicated = (base_url, model_name, api_key)
    if any(dedicated) and not all(dedicated):
        raise RuntimeError(
            "dedicated candidate assessor requires "
            "RESEARCH_CANDIDATE_ASSESSOR_BASE_URL, "
            "RESEARCH_CANDIDATE_ASSESSOR_MODEL_NAME, and "
            "RESEARCH_CANDIDATE_ASSESSOR_API_KEY"
        )
    if all(dedicated):
        client: Any = OpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=0,
        )
        gateway._model_name = model_name  # noqa: SLF001
    else:
        client = gateway._client  # noqa: SLF001
    gateway._client = _CandidateAssessorClient(  # noqa: SLF001
        client,
        provider_profile=gateway.provider_profile,
    )
    return gateway


class RuntimeEvidenceExtractor:
    def __init__(self, model_gateway: ResearchModelGateway) -> None:
        self.model_gateway = model_gateway

    def extract(
        self,
        *,
        run_id: str,
        claim: ResearchClaim,
        candidate: CandidatePoolItem,
        source_role: str,
        source_cluster_id: str,
        content: str,
        timeout_seconds: float | None = None,
        on_attempt_started: AttemptStartedHook | None = None,
        on_attempt_finished: AttemptFinishedHook | None = None,
        call_id_suffix: str = "",
        attempt_start: int = 1,
    ) -> EvidenceExtractionResult:
        role = _enum(source_role, _SOURCE_ROLES, "source_role")
        cluster_id = _required_text(source_cluster_id, 300, "source_cluster_id")
        excerpt = str(content or "")[:6000]
        if not excerpt.strip():
            return EvidenceExtractionResult(
                status="unavailable",
                extraction=None,
                audits=(),
                reason="empty_read_content",
            )
        request = {
            "schema_version": EVIDENCE_EXTRACTION_SCHEMA_VERSION,
            "candidate_id": candidate.id,
            "claim_id": claim.id,
            "claim_text": claim.text[:2000],
            "source_role": role,
            "source_cluster_id": cluster_id,
            "published_at": candidate.published_at,
            "page": {
                "title": candidate.title[:500],
                "url": candidate.canonical_url[:2000],
                "excerpt": excerpt,
            },
        }
        # Transport stays json_object for every provider; thinking-off is a
        # provider capability so reasoning cannot consume the bounded budget.
        extraction_mode, thinking_off_extra_body = research_structured_output_capabilities(
            self.model_gateway.provider_profile
        )
        extraction_system_prompt = _EXTRACTION_SYSTEM_PROMPT + (
            _JSON_OBJECT_EXTRACTION_CONTRACT if extraction_mode == "json_object" else ""
        )
        result = self.model_gateway.complete_structured(
            logical_call_id=(
                f"research_evidence_extract:{run_id}:{claim.id}:{candidate.id}:1"
                f"{call_id_suffix}"
            ),
            purpose="research_evidence_extraction",
            messages=[
                {"role": "system", "content": extraction_system_prompt},
                {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
            ],
            audit_payload=request,
            response_schema_version=EVIDENCE_EXTRACTION_SCHEMA_VERSION,
            parse=lambda raw: _parse_extraction(
                raw,
                candidate=candidate,
                claim=claim,
                source_role=role,
                source_cluster_id=cluster_id,
                excerpt=excerpt,
            ),
            data_categories=(
                "public_research_claim",
                "public_candidate_metadata",
                "bounded_public_page_excerpt",
            ),
            data_counts={
                "research_claim": 1,
                "candidate_metadata": 1,
                "page_excerpt_chars": len(excerpt),
            },
            max_tokens=900,
            temperature=0.0,
            timeout_seconds=timeout_seconds,
            on_attempt_started=on_attempt_started,
            on_attempt_finished=on_attempt_finished,
            attempt_start=attempt_start,
            extra_body=thinking_off_extra_body,
        )
        return EvidenceExtractionResult(
            status=result.status,
            extraction=result.value,
            audits=result.audits,
            reason=result.reason,
        )


def _parse_extraction(
    raw: Any,
    *,
    candidate: CandidatePoolItem,
    claim: ResearchClaim,
    source_role: str,
    source_cluster_id: str,
    excerpt: str,
) -> ExtractedEvidenceLink:
    data = _mapping(raw, "evidence extraction")
    if set(data) != _EXTRACTION_FIELDS:
        raise ValueError("evidence extraction has unknown or missing fields")
    if data.get("schema_version") != EVIDENCE_EXTRACTION_SCHEMA_VERSION:
        raise ValueError("evidence extraction schema version mismatch")
    if _required_text(data.get("candidate_id"), 300, "candidate_id") != candidate.id:
        raise ValueError("extractor changed server-owned candidate_id")
    if _required_text(data.get("claim_id"), 300, "claim_id") != claim.id:
        raise ValueError("extractor changed server-owned claim_id")
    if _enum(data.get("source_role"), _SOURCE_ROLES, "source_role") != source_role:
        raise ValueError("extractor changed server-owned source_role")
    if (
        _required_text(data.get("source_cluster_id"), 300, "source_cluster_id")
        != source_cluster_id
    ):
        raise ValueError("extractor changed server-owned source_cluster_id")
    published_at = _date_text(data.get("published_at"))
    if published_at != candidate.published_at:
        raise ValueError("extractor changed server-owned published_at")
    locator = _required_text(data.get("locator"), 500, "locator")
    spans = _text_tuple(data.get("anchored_spans"), 4, 500, "anchored_spans")
    if locator not in excerpt or any(span not in excerpt for span in spans):
        raise ValueError("extractor anchor is not present in read excerpt")
    return ExtractedEvidenceLink(
        candidate_id=candidate.id,
        claim_id=claim.id,
        source_role=source_role,
        source_cluster_id=source_cluster_id,
        relation=_enum(data.get("relation"), _RELATIONS, "relation"),
        strength=_unit_float(data.get("strength"), "strength"),
        locator=locator,
        anchored_spans=spans,
        caveats=_text_tuple(data.get("caveats"), 6, 500, "caveats"),
        published_at=published_at,
    )


def _freshness_score(value: str, *, reference_date: str, max_age_days: int | None) -> float:
    if not value or not reference_date:
        return 0.0
    try:
        age = (date.fromisoformat(reference_date) - date.fromisoformat(value)).days
    except ValueError:
        return 0.0
    if age < 0:
        return 0.0
    if max_age_days is None:
        return 1.0
    if max_age_days == 0:
        return 1.0 if age == 0 else 0.0
    return max(0.0, min(1.0, 1.0 - (age / max_age_days)))


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def _required_text(value: Any, limit: int, label: str) -> str:
    text = " ".join(str(value or "").split())[:limit]
    if not text:
        raise ValueError(f"{label} must be non-empty")
    return text


def _enum(value: Any, allowed: set[str], label: str) -> str:
    text = _required_text(value, 100, label).casefold()
    if text not in allowed:
        raise ValueError(f"invalid {label}")
    return text


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


def _text_tuple(value: Any, limit: int, item_limit: int, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{label} must be a bounded list")
    return tuple(dict.fromkeys(_required_text(item, item_limit, label) for item in value))


def _date_text(value: Any) -> str:
    text = " ".join(str(value or "").split())[:100]
    if not text:
        return ""
    return date.fromisoformat(text).isoformat()


__all__ = [
    "CANDIDATE_ASSESSMENT_MAX_ATTEMPTS_PER_INVOCATION",
    "CANDIDATE_ASSESSMENT_BASE_MAX_TOKENS",
    "CANDIDATE_ASSESSMENT_MAX_TOKENS_PER_CANDIDATE",
    "CANDIDATE_ASSESSMENT_WINDOW_MAX_TOKENS",
    "CANDIDATE_ASSESSMENT_TIMEOUT_SECONDS",
    "CandidateAssessmentResult",
    "EVIDENCE_EXTRACTION_SCHEMA_VERSION",
    "EvidenceExtractionResult",
    "ExtractedEvidenceLink",
    "RuntimeCandidateAssessor",
    "RuntimeEvidenceExtractor",
]
