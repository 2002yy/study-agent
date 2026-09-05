"""Production claim bootstrap for the Claim Engine runtime.

The model proposes only semantic claim shape. Code owns identifiers, policy,
evidence requirements, initial gaps, trace events, and the resulting
``ResearchState``. This module imports no evaluation helpers and performs no
search/read/persistence work.
"""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from os import getenv
from typing import Any, Mapping

from openai import OpenAI

from src.llm_client import get_client
from src.web.research.contracts import (
    EvidenceGap,
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    ResearchMode,
    ResearchQuestion,
    ResearchState,
    ResearchTraceEvent,
    build_research_state,
)
from src.web.research.model_gateway import (
    AttemptFinishedHook,
    AttemptStartedHook,
    ResearchModelCallAudit,
    ResearchModelGateway,
)
from src.web.research.policy import evidence_policy_for_claim

RUNTIME_CLAIM_PLAN_SCHEMA_VERSION = "research-runtime-claim-plan-v1"
MAX_RUNTIME_CLAIMS = 6
CLAIM_PLANNER_MAX_TOKENS = 320
CLAIM_PLANNER_MAX_ATTEMPTS_PER_INVOCATION = 1

_CLAIM_KINDS = {"research_question", "hypothesis", "factual", "analytical"}
_CLAIM_PRIORITIES = {"critical", "major", "context"}
_POLICY_PROFILES_BY_KIND: dict[str, tuple[str, ...]] = {
    "factual": (
        "official_statement",
        "current_fact",
        "quantitative_claim",
        "community_sentiment",
    ),
    "analytical": (
        "quantitative_claim",
        "causal_analysis",
        "community_sentiment",
    ),
    "research_question": ("exploratory_hypothesis",),
    "hypothesis": ("exploratory_hypothesis",),
}
_POLICY_PROFILES = {
    profile
    for profiles in _POLICY_PROFILES_BY_KIND.values()
    for profile in profiles
}

_CLAIM_SYSTEM_PROMPT = """You are a research claim planner.
Return one JSON object and no prose. For every claim, question_anchor MUST be
copied verbatim as one contiguous substring of the supplied question. Never
write an answer, inferred value, new entity, or paraphrase into question_anchor.
Choose an evidence-bearing span that includes the subject and requested
attribute, not an isolated word. critical_claim is the single indispensable
verification target. supporting_claims are optional and may be empty. Add a
supporting claim ONLY when the question itself contains a distinct contiguous
evidence-bearing span different from the critical anchor. If no distinct span
exists, supporting_claims MUST be empty, even for a comparison. Never reuse an
anchor. Do not invent evidence, sources, URLs, identifiers, freshness rules, or
evidence thresholds. Choose exactly one compatible kind/policy_profile pair for
each claim.
Compatibility rules:
- factual: official_statement, current_fact, quantitative_claim, or community_sentiment
- analytical: quantitative_claim, causal_analysis, or community_sentiment
- research_question or hypothesis: exploratory_hypothesis only
The response is constrained by a JSON Schema; satisfy its semantic rules too."""


def _claim_item_schema(*, kind: str, profiles: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "question_anchor",
            "kind",
            "policy_profile",
        ],
        "properties": {
            "question_anchor": {
                "type": "string",
                "minLength": 1,
                "maxLength": 160,
            },
            "kind": {
                "type": "string",
                "enum": [kind],
            },
            "policy_profile": {
                "type": "string",
                "enum": list(profiles),
            },
        },
    }


_CLAIM_ITEM_UNION_SCHEMA: dict[str, Any] = {
    "anyOf": [
        _claim_item_schema(kind=kind, profiles=profiles)
        for kind, profiles in _POLICY_PROFILES_BY_KIND.items()
    ]
}

_CLAIM_PLAN_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "research_runtime_claim_plan",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "critical_claim",
                "supporting_claims",
            ],
            "properties": {
                "schema_version": {
                    "type": "string",
                    "enum": [RUNTIME_CLAIM_PLAN_SCHEMA_VERSION],
                },
                "critical_claim": _CLAIM_ITEM_UNION_SCHEMA,
                "supporting_claims": {
                    "type": "array",
                    "minItems": 0,
                    "maxItems": MAX_RUNTIME_CLAIMS - 1,
                    "items": _CLAIM_ITEM_UNION_SCHEMA,
                },
            },
        },
    },
}


@dataclass(frozen=True)
class ProposedClaim:
    surface: str
    kind: str
    priority: str
    policy_profile: str


@dataclass(frozen=True)
class ClaimBootstrapResult:
    status: str
    state: ResearchState | None
    audits: tuple[ResearchModelCallAudit, ...]
    reason: str = ""

    @property
    def completed(self) -> bool:
        return self.status == "completed" and self.state is not None


class _ClaimPlannerCompletions:
    """Inject planner-only JSON Schema without changing the shared gateway API."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def create(self, **kwargs: Any) -> Any:
        kwargs["response_format"] = _CLAIM_PLAN_RESPONSE_FORMAT
        return self._inner.create(**kwargs)


class _ClaimPlannerChat:
    def __init__(self, inner: Any) -> None:
        self.completions = _ClaimPlannerCompletions(inner.completions)


class _ClaimPlannerClient:
    """Planner response-format adapter that preserves the gateway's lazy client."""

    def __init__(self, inner: Any, *, provider_profile: str) -> None:
        self._inner = inner
        self._provider_profile = provider_profile

    @property
    def chat(self) -> _ClaimPlannerChat:
        return _ClaimPlannerChat(self._resolved_inner().chat)

    def with_options(self, **kwargs: Any) -> _ClaimPlannerClient:
        return _ClaimPlannerClient(
            self._resolved_inner().with_options(**kwargs),
            provider_profile=self._provider_profile,
        )

    def _resolved_inner(self) -> Any:
        if self._inner is not None:
            return self._inner
        return get_client(provider_profile=self._provider_profile)


class RuntimeClaimPlanner:
    def __init__(self, model_gateway: ResearchModelGateway) -> None:
        # Preserve the shared gateway's durable operation budget, but constrain
        # each planner invocation to one physical model request. A timeout or
        # parse failure therefore cannot immediately burn attempt two. If the
        # process crashes after a successful call but before semantic persist,
        # the durable runtime may later resume at attempt two and spend exactly
        # that one recovery request.
        self._durable_max_attempts = model_gateway.max_attempts
        self.model_gateway = _claim_planner_gateway(model_gateway)

    def plan(
        self,
        *,
        run_id: str,
        question: str,
        reference_date: str,
        budget: ResearchBudget,
        freshness_requested: bool = False,
        freshness_days: int | None = None,
        timestamp: str | None = None,
        mode: ResearchMode = "shadow",
        timeout_seconds: float | None = None,
        on_attempt_started: AttemptStartedHook | None = None,
        on_attempt_finished: AttemptFinishedHook | None = None,
        attempt_start: int = 1,
    ) -> ClaimBootstrapResult:
        normalized_run_id = _required_text(run_id, 300, "run_id")
        if mode not in {"shadow", "active"}:
            raise ValueError("unsupported research mode")
        if isinstance(attempt_start, bool) or not isinstance(attempt_start, int) or attempt_start < 1:
            raise ValueError("attempt_start must be a positive integer")
        if attempt_start > self._durable_max_attempts:
            return ClaimBootstrapResult(
                status="unavailable",
                state=None,
                audits=(),
                reason="claim_plan_attempts_exhausted",
            )

        normalized_question = _required_text(question, 4000, "question")
        normalized_reference_date = date.fromisoformat(reference_date).isoformat()
        normalized_freshness = _freshness_days(
            freshness_requested=freshness_requested,
            freshness_days=freshness_days,
        )
        audit_payload = {
            "question": normalized_question,
            "reference_date": normalized_reference_date,
            "freshness_requested": bool(freshness_requested),
            "freshness_days": normalized_freshness,
        }

        # ResearchModelGateway interprets max_attempts as the terminal attempt
        # number. Setting it to attempt_start on an invocation-local clone makes
        # range(attempt_start, max_attempts + 1) contain exactly one request.
        call_gateway = copy(self.model_gateway)
        call_gateway.max_attempts = attempt_start
        result = call_gateway.complete_structured(
            logical_call_id=f"research_claim_plan:{normalized_run_id}:1",
            purpose="research_claim_planning",
            messages=[
                {"role": "system", "content": _CLAIM_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _claim_user_payload(audit_payload),
                },
            ],
            audit_payload=audit_payload,
            response_schema_version=RUNTIME_CLAIM_PLAN_SCHEMA_VERSION,
            parse=lambda raw: _parse_claim_plan(raw, question=normalized_question),
            data_categories=("user_question", "research_time_context"),
            data_counts={
                "user_question": 1,
                "question_chars": len(normalized_question),
            },
            max_tokens=CLAIM_PLANNER_MAX_TOKENS,
            temperature=0.0,
            timeout_seconds=timeout_seconds,
            on_attempt_started=on_attempt_started,
            on_attempt_finished=on_attempt_finished,
            attempt_start=attempt_start,
        )
        if not result.completed or result.value is None:
            return ClaimBootstrapResult(
                status="unavailable",
                state=None,
                audits=result.audits,
                reason=result.reason or "claim_plan_unavailable",
            )

        state = _build_initial_state(
            run_id=normalized_run_id,
            question=normalized_question,
            reference_date=normalized_reference_date,
            proposals=result.value,
            budget=budget,
            freshness_days=normalized_freshness,
            timestamp=timestamp or _utc_now(),
            mode=mode,
        )
        return ClaimBootstrapResult(
            status="completed",
            state=state,
            audits=result.audits,
        )


def _claim_planner_gateway(shared: ResearchModelGateway) -> ResearchModelGateway:
    gateway = copy(shared)
    gateway.max_attempts = CLAIM_PLANNER_MAX_ATTEMPTS_PER_INVOCATION

    base_url = (getenv("RESEARCH_CLAIM_PLANNER_BASE_URL") or "").strip()
    model_name = (getenv("RESEARCH_CLAIM_PLANNER_MODEL_NAME") or "").strip()
    api_key = (getenv("RESEARCH_CLAIM_PLANNER_API_KEY") or "").strip()
    dedicated = (base_url, model_name, api_key)
    if any(dedicated) and not all(dedicated):
        raise RuntimeError(
            "dedicated claim planner requires RESEARCH_CLAIM_PLANNER_BASE_URL, "
            "RESEARCH_CLAIM_PLANNER_MODEL_NAME, and RESEARCH_CLAIM_PLANNER_API_KEY"
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

    gateway._client = _ClaimPlannerClient(  # noqa: SLF001
        client,
        provider_profile=gateway.provider_profile,
    )
    return gateway


def _parse_claim_plan(raw: Any, *, question: str) -> tuple[ProposedClaim, ...]:
    data = _strict_mapping(
        raw,
        {"schema_version", "critical_claim", "supporting_claims"},
        "runtime claim plan",
    )
    if data.get("schema_version") != RUNTIME_CLAIM_PLAN_SCHEMA_VERSION:
        raise ValueError("unsupported runtime claim plan schema")

    supporting_raw = data.get("supporting_claims")
    if not isinstance(supporting_raw, list) or len(supporting_raw) > MAX_RUNTIME_CLAIMS - 1:
        raise ValueError("runtime claim plan must contain zero to five supporting claims")

    proposals: list[ProposedClaim] = []
    seen: set[str] = set()

    # The critical claim is indispensable and remains fully fail-closed. A bad
    # critical anchor, schema, kind, or policy profile invalidates the plan.
    critical = _parse_claim_candidate(
        data.get("critical_claim"),
        priority="critical",
        question=question,
    )
    critical_key = " ".join(critical.surface.casefold().split())
    seen.add(critical_key)
    proposals.append(critical)

    # Supporting claims are explicitly optional. If the model violates the
    # prompt's anchor-only rules for one optional supporting claim (non-verbatim
    # or duplicate anchor), excluding that claim enforces the contract rather
    # than letting optional noise invalidate an otherwise sound critical plan.
    # Schema/kind/profile/policy validation remains strict for every supporting
    # claim that has a usable, distinct anchor and could enter ResearchState.
    for raw_claim in supporting_raw:
        claim = _strict_mapping(
            raw_claim,
            {"question_anchor", "kind", "policy_profile"},
            "runtime claim",
        )
        try:
            surface = _canonical_question_anchor(
                claim.get("question_anchor"),
                question=question,
            )
        except ValueError:
            continue
        dedupe_key = " ".join(surface.casefold().split())
        if dedupe_key in seen:
            continue
        candidate = _parse_claim_candidate(
            claim,
            priority="major",
            question=question,
            prevalidated_surface=surface,
        )
        seen.add(dedupe_key)
        proposals.append(candidate)
    return tuple(proposals)


def _parse_claim_candidate(
    raw_claim: Any,
    *,
    priority: str,
    question: str,
    prevalidated_surface: str | None = None,
) -> ProposedClaim:
    claim = _strict_mapping(
        raw_claim,
        {"question_anchor", "kind", "policy_profile"},
        "runtime claim",
    )
    surface = prevalidated_surface or _canonical_question_anchor(
        claim.get("question_anchor"),
        question=question,
    )
    kind = _enum(claim.get("kind"), _CLAIM_KINDS, "claim kind")
    profile = _enum(
        claim.get("policy_profile"), _POLICY_PROFILES, "evidence policy profile"
    )
    # Semantic compatibility remains a hard code-owned validation even when
    # the provider honors JSON Schema. A provider that only guarantees JSON
    # syntax therefore cannot silently weaken evidence policy.
    evidence_policy_for_claim(
        kind=kind,  # type: ignore[arg-type]
        priority=priority,  # type: ignore[arg-type]
        profile=profile,  # type: ignore[arg-type]
    )
    return ProposedClaim(
        surface=surface,
        kind=kind,
        priority=priority,
        policy_profile=profile,
    )


def _canonical_question_anchor(value: Any, *, question: str) -> str:
    anchor = " ".join(str(value or "").split())
    if not anchor:
        raise ValueError("question anchor must be non-empty")
    if len(anchor) > 160:
        raise ValueError("question anchor exceeds 160 characters")
    if anchor not in question:
        raise ValueError("question anchor must be copied from user question")
    return anchor


def _build_initial_state(
    *,
    run_id: str,
    question: str,
    reference_date: str,
    proposals: tuple[ProposedClaim, ...],
    budget: ResearchBudget,
    freshness_days: int | None,
    timestamp: str,
    mode: ResearchMode,
) -> ResearchState:
    question_id = _stable_id("question", run_id, question)
    research_question = ResearchQuestion(
        id=question_id,
        question_surface=question,
        priority="major",
        state="unresolved",
    )
    claims: list[ResearchClaim] = []
    gaps: list[EvidenceGap] = []
    trace: list[ResearchTraceEvent] = []
    sequence = 0

    for ordinal, proposal in enumerate(proposals, start=1):
        policy = evidence_policy_for_claim(
            kind=proposal.kind,  # type: ignore[arg-type]
            priority=proposal.priority,  # type: ignore[arg-type]
            profile=proposal.policy_profile,  # type: ignore[arg-type]
        )
        requirement = _with_runtime_freshness(
            policy.requirement,
            profile=proposal.policy_profile,
            freshness_days=freshness_days,
        )
        claim_id = _stable_id(
            "claim",
            question_id,
            str(ordinal),
            proposal.surface,
        )
        claim = ResearchClaim(
            id=claim_id,
            question_id=question_id,
            text=proposal.surface,
            kind=proposal.kind,  # type: ignore[arg-type]
            priority=proposal.priority,  # type: ignore[arg-type]
            state="pending",
            evidence_requirement=requirement,
            created_by="runtime_claim_planner",
            created_reason=f"policy_profile:{proposal.policy_profile}",
        )
        gap_id = _stable_id("gap", claim_id, _initial_gap_type(requirement))
        gap = EvidenceGap(
            id=gap_id,
            claim_id=claim_id,
            gap_type=_initial_gap_type(requirement),
            desired_source_role=(requirement.source_roles[0] if requirement.source_roles else ""),
            priority=proposal.priority,  # type: ignore[arg-type]
            attempt_count=0,
            state="open",
        )
        claims.append(claim)
        gaps.append(gap)
        trace.append(
            ResearchTraceEvent(
                sequence=sequence,
                timestamp=timestamp,
                run_id=run_id,
                event_type="claim_created",
                reason="runtime_claim_plan_validated",
                claim_id=claim_id,
            )
        )
        sequence += 1
        trace.append(
            ResearchTraceEvent(
                sequence=sequence,
                timestamp=timestamp,
                run_id=run_id,
                event_type="gap_created",
                reason=f"initial_gap:{gap.gap_type}",
                claim_id=claim_id,
                gap_id=gap_id,
            )
        )
        sequence += 1

    return build_research_state(
        mode=mode,
        questions=(research_question,),
        claims=claims,
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=gaps,
        conflict_gaps=(),
        budget=budget,
        trace=trace,
        brief=None,
        reference_date=reference_date,
        known_evidence_ids=(),
    )


def _with_runtime_freshness(
    requirement: EvidenceRequirement,
    *,
    profile: str,
    freshness_days: int | None,
) -> EvidenceRequirement:
    if freshness_days is None or profile == "exploratory_hypothesis":
        return requirement
    return EvidenceRequirement(
        source_roles=requirement.source_roles,
        min_independent_sources=requirement.min_independent_sources,
        requires_primary_source=requirement.requires_primary_source,
        requires_successful_read=requirement.requires_successful_read,
        max_age_days=freshness_days,
        requires_dated_evidence=True,
    )


def _freshness_days(
    *, freshness_requested: bool, freshness_days: int | None
) -> int | None:
    if not freshness_requested:
        return None
    if freshness_days is None:
        return 30
    if isinstance(freshness_days, bool):
        raise ValueError("freshness_days must be an integer")
    value = int(freshness_days)
    if value < 1 or value > 3650:
        raise ValueError("freshness_days is out of range")
    return value


def _initial_gap_type(requirement: EvidenceRequirement) -> str:
    if requirement.requires_primary_source:
        return "primary_required"
    if requirement.min_independent_sources > 1:
        return "independent_support_required"
    return "support_required"


def _claim_user_payload(payload: Mapping[str, Any]) -> str:
    # Deliberately structured and bounded: no history, memory, local RAG, or page
    # content enters claim bootstrap.
    import json

    return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True)


def _stable_id(prefix: str, *parts: str) -> str:
    material = "\u0000".join(parts)
    return f"{prefix}_{sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strict_mapping(raw: Any, allowed: set[str], label: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError(f"{label} must be an object")
    data = dict(raw)
    if set(data) != allowed:
        raise ValueError(f"{label} fields do not match schema")
    return data


def _required_text(value: Any, limit: int, label: str) -> str:
    text = " ".join(str(value or "").split())[:limit]
    if not text:
        raise ValueError(f"{label} must be non-empty")
    return text


def _enum(value: Any, allowed: set[str], label: str) -> str:
    normalized = _required_text(value, 100, label)
    if normalized not in allowed:
        raise ValueError(f"invalid {label}")
    return normalized


__all__ = [
    "CLAIM_PLANNER_MAX_ATTEMPTS_PER_INVOCATION",
    "CLAIM_PLANNER_MAX_TOKENS",
    "ClaimBootstrapResult",
    "MAX_RUNTIME_CLAIMS",
    "ProposedClaim",
    "RUNTIME_CLAIM_PLAN_SCHEMA_VERSION",
    "RuntimeClaimPlanner",
]
