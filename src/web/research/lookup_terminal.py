"""Lookup terminal and pending handoff contract used by the chat save exit.

Semantic relevance is inherited only from the existing server session. The
handoff is research context, never evidence-publication authority.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from src.web.research.official_publication import LABELS, publish_official_fields
from src.web.research_recovery import recovery_summary
from src.web.tool_evidence import trusted_tool_calls

SCHEMA = "lookup-standard-handoff-v1"
NORMAL_ENDS = {"read_backed", "partial", "candidate_exhausted", "budget_exhausted",
               "provider_exhausted", "evidence_saturation"}


def requested_lookup_fields(query: str) -> tuple[str, ...]:
    """Plan supported explicit facets from intent, never from returned fields.

    Ambiguous or unsupported facets stay unplanned and therefore cannot be
    called VERIFIED. A model planner may extend this contract separately.
    """
    from src.web.research.official_resolver import official_plan

    plan = official_plan(query)
    if plan is None:
        return ()
    fields: set[str] = set()
    date = bool(re.search(r"日期|时间|什么时候|何时|date|when", query, re.I))
    if plan.entity == "arxiv":
        if re.search(r"作者|author", query, re.I):
            fields.add("authors")
        if re.search(r"首次|提交|first|submit", query, re.I):
            fields.add("first_submission")
        elif date:
            fields.add("citation_date")
        if re.search(r"标题|题目|title", query, re.I):
            fields.add("title")
    else:
        if re.search(r"版本|version|最新|latest", query, re.I):
            fields.add("version")
        if date:
            fields.add("distribution_uploaded_at" if plan.entity == "fastapi"
                       and re.search(r"上传|upload", query, re.I) else "release_date")
        if plan.entity == "sqlite" and re.search(r"变化|变更|更新|changes|changelog", query, re.I):
            fields.add("changes")
        if plan.entity == "opus" and re.search(r"是什么|定位|简介|what is|position", query, re.I):
            fields.add("official_positioning")
    # Unknown facts must not disappear behind a recognized date/version facet.
    if re.search(r"价格|性能|跑分|参数|price|benchmark|performance", query, re.I):
        return ()
    if plan.entity != "arxiv" and re.search(r"作者|author|标题|title", query, re.I):
        return ()
    if plan.entity != "sqlite" and re.search(r"变化|变更|changes|changelog", query, re.I):
        return ()
    # Every requested facet must belong to this bounded grammar. Recognizing
    # a date cannot erase an additional unknown request (e.g. download URL).
    remainder = re.sub(r"attention\s+is\s+all\s+you\s+need", "", query, flags=re.I)
    remainder = re.sub(r"https?://arxiv\.org/(?:abs|pdf)/\d{4}\.\d{4,5}(?:v\d+)?(?:\.pdf)?",
                       "", remainder, flags=re.I)
    remainder = re.sub(r"(?<![A-Za-z])(?:python|fastapi|sqlite|opus|arxiv|pypi)(?![A-Za-z])",
                       "", remainder, flags=re.I)
    remainder = re.sub(r"\d+(?:\.\d+)+", "", remainder)
    chinese = ("什么时候", "告诉我", "是多少", "是什么", "何时", "当前", "目前", "现在", "最新",
               "最近", "首次", "提交", "日期", "时间", "发布", "版本", "变化", "变更", "更新",
               "作者", "标题", "题目", "简介", "定位", "上传", "查询", "查看", "记录", "请", "的", "及", "和", "与")
    remainder = re.sub("|".join(chinese), "", remainder)
    remainder = re.sub(r"\b(?:what|is|the|when|was|release|released|date|version|latest|current|and|of|"
                       r"authors?|title|first|submission|submitted|changes|changelog|positioning|"
                       r"upload|uploaded|time)\b", "", remainder, flags=re.I)
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


def _verified_relevance_sources(calls: list[dict], rq_ids: set[str], summary: dict) -> list[dict]:
    coverage = summary.get("question_coverage")
    if not isinstance(coverage, dict) or coverage.get("kind") != "relevance_only":
        return []
    related = coverage.get("related")
    if not isinstance(related, list) or not all(isinstance(item, str) for item in related):
        return []
    sources = []
    for call in trusted_tool_calls(calls):
        if call["name"] != "web_read":
            continue
        result = call["result"]
        ids = result.get("related_rq_ids")
        body = result.get("content") or result.get("readme")
        if (result.get("answer_eligible") is False
                or result.get("adequacy_reason") != "related_to_rq_not_claim_support"
                or not isinstance(ids, list) or not ids
                or not all(isinstance(item, str) for item in ids)
                or not set(ids) <= rq_ids or not set(ids) <= set(related)
                or not isinstance(body, str) or not body.strip()
                or hashlib.sha256(body.encode()).hexdigest() != result.get("content_sha256")):
            continue
        sources.append(deepcopy(call))
    return sources


def decide_lookup_terminal(query: str, calls: list[dict], *, requested_fields: tuple[str, ...],
                           requested_rq_ids: tuple[str, ...] = (), allow_standard: bool = False,
                           recovery: dict[str, Any] | None = None,
                           identity_conflict: bool = False, contradiction: bool = False,
                           cancelled: bool = False) -> LookupTerminal:
    """Consume a server-owned field plan and semantic-session trace.

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
    sources = _verified_relevance_sources(calls, rq_ids, summary)
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
