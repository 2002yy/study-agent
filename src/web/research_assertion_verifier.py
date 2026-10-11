"""M4-C5: independent, fail-closed semantic verification of anchored assertions.

A verifier may assess semantic entailment but cannot choose a source, URL,
content hash or span. Exact source binding is checked before its vote is used.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


VERDICTS = frozenset({"supported", "insufficient", "conflict", "abstain"})


def verification_messages(question: str, candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    payload = {
        "question": question,
        "assertions": [
            {"claim_id": c["claim_id"], "goal": c["goal"],
             "claim": c["claim"], "verbatim_evidence": c["quote"]}
            for c in candidates
        ],
        "output": {"verdicts": [{"claim_id": "c1",
                                "status": "supported|insufficient|conflict|abstain",
                                "reason": "brief entailment explanation"}]},
    }
    return [
        {"role": "system", "content": (
            "You are an INDEPENDENT evidence verifier, not the extractor. "
            "Judge whether each assertion is logically supported by its cited "
            "quotation, including the complete relationship and any qualifications. "
            "Keyword overlap or a nearby causal word is NEVER sufficient. "
            "Use supported ONLY when the quoted text entails the entire claim; "
            "conflict when it contradicts it; insufficient for partial or off-topic "
            "evidence; abstain if uncertain. Do not infer from outside knowledge. "
            "Return JSON only, with one status per claim_id."
        )},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def bind_and_verify(raw: str, claims: list[dict[str, Any]],
                    sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anchor first, then apply independent semantic verdict; missing vote abstains."""
    try:
        data = json.loads(raw)
        rows = data.get("verdicts") if isinstance(data, dict) else None
    except (TypeError, ValueError):
        rows = None
    votes: dict[str, dict[str, str]] = {}
    if isinstance(rows, list):
        for row in rows:
            if (isinstance(row, dict) and isinstance(row.get("claim_id"), str)
                    and row["claim_id"] not in votes
                    and row.get("status") in VERDICTS):
                votes[row["claim_id"]] = {
                    "status": row["status"], "reason": str(row.get("reason") or "")[:240],
                }
    by_id = {s["source_id"]: s for s in sources}
    results: list[dict[str, Any]] = []
    for claim in claims:
        source = by_id.get(claim["source_id"])
        status, reason = "unavailable", "source_not_cached"
        if source is not None:
            text = str(source["text"])
            start, end = claim["span_start"], claim["span_end"]
            hash_ok = (hashlib.sha256(text.encode("utf-8")).hexdigest()
                       == claim["content_hash"] == source["content_hash"])
            anchor_ok = (isinstance(start, int) and isinstance(end, int)
                         and 0 <= start < end <= len(text)
                         and text[start:end] == claim["quote"])
            url_ok = claim["final_url"] == source["final_url"]
            if hash_ok and anchor_ok and url_ok:
                vote = votes.get(claim["claim_id"], {})
                status = vote.get("status", "abstain")
                reason = vote.get("reason", "verifier_no_valid_vote")
            else:
                reason = "source_binding_mismatch"
        results.append({**claim, "status": status, "reason": reason,
                        "verified_by": ("independent_semantic" if status in VERDICTS
                                        else "source_binding_failed")})
    return results
