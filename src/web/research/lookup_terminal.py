"""Lookup terminal contract. Production routing does not yet invoke this module.

Semantic relevance is inherited only from the existing server session. The
handoff is research context, never evidence-publication authority.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from src.web.research.official_publication import LABELS, publish_official_fields
from src.web.research_recovery import recovery_summary
from src.web.tool_evidence import trusted_tool_calls

SCHEMA = "lookup-standard-handoff-v1"
NORMAL_ENDS = {"read_backed", "partial", "candidate_exhausted", "budget_exhausted",
               "provider_exhausted", "evidence_saturation"}


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
                           identity_conflict: bool = False, contradiction: bool = False,
                           cancelled: bool = False) -> LookupTerminal:
    """Consume a server-owned field plan and semantic-session trace.

    Callers must not infer requested fields from whichever fields were found.
    No mode switch occurs here; the production adapter must enforce policy,
    overall deadline, durable ownership and exactly-once resume separately.
    """
    fields = set(requested_fields)
    if not fields or not fields <= LABELS.keys():
        return LookupTerminal("SAFE_ABSTAIN", "requested_claim_plan_unavailable")
    summary = recovery_summary(calls) or {}
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
                                      allow_standard=True)
    if decision.handoff != payload:
        raise ValueError("handoff no longer matches verified source snapshot")
    return deepcopy(payload)
