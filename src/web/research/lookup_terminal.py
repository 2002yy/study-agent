"""Lookup terminal and pending handoff contract used by the chat save exit.

Relevance may come from the existing semantic session or from the recovery
pipeline's exact named-version identity proof. The handoff is research context,
never evidence-publication authority.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from src.web.research.official_publication import LABELS, publish_official_fields
from src.web.research_recovery import model_targets, recovery_summary, target_identity_pattern
from src.web.tool_evidence import trusted_tool_calls

SCHEMA = "lookup-standard-handoff-v1"
NORMAL_ENDS = {"read_backed", "partial", "candidate_exhausted", "budget_exhausted",
               "provider_exhausted", "evidence_saturation"}


def requested_lookup_fields(query: str) -> tuple[str, ...]:
    """Plan only explicitly consumed supported facets from the original query.

    Recognizing one supported facet must never erase an additional unknown
    request.  The planner therefore removes only spans that were actually
    mapped to a field, then rejects any remaining substantive text.
    """
    from src.web.research.official_resolver import official_plan

    plan = official_plan(query)
    if plan is None:
        return ()

    remainder = query
    fields: set[str] = set()

    def consume(pattern: str, field: str) -> bool:
        nonlocal remainder
        if not re.search(pattern, remainder, re.I):
            return False
        remainder = re.sub(pattern, " ", remainder, flags=re.I)
        fields.add(field)
        return True

    if plan.entity == "arxiv":
        consume(r"(?:首次|初次)\s*(?:提交|submission)(?:\s*(?:日期|时间|date|time))?|first\s+submission(?:\s+date)?",
                "first_submission")
        consume(r"作者|authors?", "authors")
        consume(r"标题|题目|title", "title")
        consume(r"引用\s*(?:日期|时间)|citation\s+date", "citation_date")
    else:
        # Consume field phrases, not generic words such as 时间/date.  In
        # particular, 更新时间/current time must not become a release date.
        consume(r"发布日期|发布\s*(?:日期|时间)|什么时候\s*发布|何时\s*发布|"
                r"release\s+date|released\s+date|when\s+(?:was|is)\s+[^,，。!?？]{0,80}\s+released",
                "release_date")
        if plan.entity == "fastapi":
            consume(r"(?:pypi\s*)?(?:上传|upload(?:ed)?)\s*(?:日期|时间|date|time)|"
                    r"distribution\s+upload(?:ed)?(?:\s+at)?",
                    "distribution_uploaded_at")
        consume(r"(?:当前|目前|最新|最近)?\s*版本(?:号)?|(?:current|latest)\s+version|\bversion\b",
                "version")
        if plan.entity == "sqlite":
            consume(r"变化|变更|更新内容|更新了什么|changes?|changelog", "changes")
        if plan.entity == "opus":
            consume(r"是什么|定位|简介|what\s+is|position(?:ing)?", "official_positioning")

    if not fields:
        return ()

    # Remove only the identity/source grammar already proven by official_plan.
    remainder = re.sub(r"attention\s+is\s+all\s+you\s+need", " ", remainder, flags=re.I)
    remainder = re.sub(r"https?://arxiv\.org/(?:abs|pdf)/\d{4}\.\d{4,5}(?:v\d+)?(?:\.pdf)?",
                       " ", remainder, flags=re.I)
    remainder = re.sub(r"(?<![A-Za-z])(?:python|fastapi|sqlite|opus|arxiv)(?![A-Za-z])",
                       " ", remainder, flags=re.I)
    if plan.entity == "fastapi":
        remainder = re.sub(r"(?<![A-Za-z])pypi(?![A-Za-z])", " ", remainder, flags=re.I)
    remainder = re.sub(r"\d+(?:\.\d+)+", " ", remainder)

    # Grammatical glue is not a requested facet.  Potentially meaningful terms
    # (更新时间, 下载, 安装, 性能, 作者 on non-arXiv, etc.) deliberately remain.
    remainder = re.sub(r"告诉我|查询|查看|记录|请|是多少|当前|目前|最新|最近|现在|的|及|和|与",
                       " ", remainder)
    remainder = re.sub(r"\b(?:please|tell|me|the|and|of|current|latest|what|is|was)\b",
                       " ", remainder, flags=re.I)
    if re.sub(r"[\s,，。.!！?？:：、/]+", "", remainder):
        return ()
    return tuple(sorted(fields))


@dataclass(frozen=True)
class LookupTerminal:
    state: str
    reason: str
    handoff: dict[str, Any] | None = None


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def _exact_target_pattern(query: str) -> re.Pattern[str] | None:
    targets = model_targets(query)
    if len(targets) != 1:
        return None
    return target_identity_pattern(targets[0])


def _native_identity_matches(query: str, result: dict) -> bool | None:
    """Adapt validated native fields; None retains the generic body contract.

    The native reader serializes project and version on separate lines. Reuse
    its existing exact identity proof instead of weakening text matching.
    This is relevance only, not support for a missing requested field.
    """
    from src.web.research.official_resolver import (
        official_plan, verified_opus_identity, verified_release_identity,
    )

    if result.get("method") != "official_metadata_http_v2":
        return None
    plan = official_plan(query)
    if plan is None or plan.entity not in {"fastapi", "opus"}:
        return None
    url = result.get("url")
    if (url not in plan.urls or result.get("ok") is not True
            or result.get("source_version") != plan.version
            or not re.fullmatch(r"[0-9a-f]{64}", str(result.get("transport_sha256") or ""))):
        return False
    body = result.get("content")
    fields = result.get("official_fields")
    if not isinstance(body, str) or not isinstance(fields, list):
        return False
    identity_fields: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            return False
        key = field.get("field")
        if key not in {"project", "version"}:
            continue
        value, start, end = field.get("value"), field.get("start"), field.get("end")
        if (key in identity_fields or not isinstance(value, str) or not value.strip()
                or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(body)
                or body[start:end] != f"{key}: {value}"):
            return False
        identity_fields.add(key)
    if identity_fields != {"project", "version"}:
        return False
    verifier = verified_opus_identity if plan.entity == "opus" else verified_release_identity
    return verifier(plan, url, result)


def _verified_relevance_sources(
    calls: list[dict], rq_ids: set[str], summary: dict, query: str
) -> list[dict]:
    """Return usable-but-unbound bodies with independently checked relevance.

    Semantic sessions bind bodies to RQ ids.  The deterministic official Lookup
    path intentionally skips that model call, so an exact single named-version
    match may also establish *relevance only*.  Neither path grants claim support
    or publication authority.
    """
    coverage = summary.get("question_coverage")
    semantic_related: set[str] | None = None
    deterministic_pattern: re.Pattern[str] | None = None

    if isinstance(coverage, dict) and coverage.get("kind") == "relevance_only":
        related = coverage.get("related")
        if not isinstance(related, list) or not all(isinstance(item, str) for item in related):
            return []
        semantic_related = set(related)
    elif coverage == "not_semantically_evaluated":
        target_coverage = summary.get("target_coverage")
        deterministic_pattern = _exact_target_pattern(query)
        if (deterministic_pattern is None or not isinstance(target_coverage, dict)
                or target_coverage.get("required") != 1
                or type(target_coverage.get("covered")) is not int
                or target_coverage.get("covered", 0) < 1):
            return []
    else:
        return []

    sources = []
    for call in trusted_tool_calls(calls):
        if call["name"] != "web_read":
            continue
        result = call["result"]
        body = result.get("content") or result.get("readme")
        if (result.get("answer_eligible") is False
                or not isinstance(body, str) or not body.strip()
                or hashlib.sha256(body.encode()).hexdigest() != result.get("content_sha256")):
            continue
        native_identity = _native_identity_matches(query, result)
        if native_identity is False:
            continue
        if semantic_related is not None:
            ids = result.get("related_rq_ids")
            if (result.get("adequacy_reason") != "related_to_rq_not_claim_support"
                    or not isinstance(ids, list) or not ids
                    or not all(isinstance(item, str) for item in ids)
                    or not set(ids) <= rq_ids or not set(ids) <= semantic_related):
                continue
        elif native_identity is not True and (
            deterministic_pattern is None or not deterministic_pattern.search(body)
        ):
            continue
        sources.append(deepcopy(call))
    return sources


def decide_lookup_terminal(query: str, calls: list[dict], *, requested_fields: tuple[str, ...],
                           requested_rq_ids: tuple[str, ...] = (), allow_standard: bool = False,
                           recovery: dict[str, Any] | None = None,
                           identity_conflict: bool = False, contradiction: bool = False,
                           cancelled: bool = False) -> LookupTerminal:
    """Consume a server-owned field plan and bounded Lookup trace.

    Callers must not infer requested fields from whichever fields were found.
    Persisted traces may carry recovery metadata separately from sanitized calls;
    when supplied, that server-owned summary remains the terminal budget authority.
    No mode switch occurs here; the production adapter must enforce policy,
    overall deadline, durable ownership and exactly-once resume separately.
    """
    fields = set(requested_fields)
    if not fields or not fields <= LABELS.keys():
        return LookupTerminal("SAFE_ABSTAIN", "requested_claim_plan_unavailable")
    if recovery is None:
        summary = recovery_summary(calls) or {}
    elif isinstance(recovery, dict):
        summary = deepcopy(recovery)
    else:
        return LookupTerminal("SAFE_ABSTAIN", "lookup_recovery_invalid")
    if cancelled or summary.get("status") == "cancelled":
        return LookupTerminal("SAFE_ABSTAIN", "cancelled")
    if identity_conflict or contradiction:
        return LookupTerminal("SAFE_ABSTAIN", "deterministic_conflict")
    if (summary.get("query") != query or summary.get("mode") != "lookup"
            or summary.get("status") not in NORMAL_ENDS):
        return LookupTerminal("SAFE_ABSTAIN", "lookup_not_normally_completed")
    reads, searches = summary.get("reads"), summary.get("searches")
    elapsed = summary.get("elapsed_seconds")
    if (type(reads) is not int or not 0 <= reads <= 3
            or type(searches) is not int or not 0 <= searches <= 2
            or not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool)
            or not 0 <= elapsed <= 30):
        return LookupTerminal("SAFE_ABSTAIN", "lookup_budget_unverified")
    _, audit = publish_official_fields(query, calls, "")
    supported = {ref["field"] for ref in audit["assertion_refs"]}
    missing = sorted(fields - supported)
    if not missing:
        return LookupTerminal("VERIFIED", "requested_claims_bound")
    if not allow_standard:
        return LookupTerminal("SAFE_ABSTAIN", "standard_not_enabled")
    rq_ids = set(requested_rq_ids)
    sources = _verified_relevance_sources(calls, rq_ids, summary, query)
    if not sources:
        return LookupTerminal("SAFE_ABSTAIN", "no_verified_relevant_source")
    payload = {"schema_version": SCHEMA, "reason": "claim_support_insufficient", "query": query,
               "requested_fields": sorted(fields), "requested_rq_ids": sorted(rq_ids),
               "known": deepcopy(audit["assertion_refs"]), "unresolved_fields": missing,
               "usable_sources": sources, "attempted": deepcopy(calls),
               "lookup_budget": deepcopy(summary), "publication_authority": False}
    payload["payload_sha256"] = _digest(payload)
    return LookupTerminal("ESCALATE_STANDARD", "claim_support_insufficient", payload)


def load_standard_handoff(payload: dict) -> dict:
    """Validate an exact snapshot before reuse; this does not spend any budget."""
    snapshot = deepcopy(payload)
    digest = snapshot.pop("payload_sha256", None)
    if snapshot.get("schema_version") != SCHEMA or _digest(snapshot) != digest:
        raise ValueError("handoff schema or digest mismatch")
    if snapshot.get("publication_authority") is not False:
        raise ValueError("handoff cannot grant publication authority")
    decision = decide_lookup_terminal(snapshot["query"], snapshot["attempted"],
                                      requested_fields=tuple(snapshot["requested_fields"]),
                                      requested_rq_ids=tuple(snapshot["requested_rq_ids"]),
                                      allow_standard=True,
                                      recovery=snapshot.get("lookup_budget"))
    if decision.handoff != payload:
        raise ValueError("handoff no longer matches verified source snapshot")
    return deepcopy(payload)
