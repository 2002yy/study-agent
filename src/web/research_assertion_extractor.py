"""M4-C5: model proposals anchored to immutable text read in this run.

Extraction proposes claims only. This module does not certify semantic support or
grant publication authority. Source identity and offsets are recomputed by Python.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


MAX_SOURCES = 5
MAX_CLAIMS = 12


def source_snapshots(bodies: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Collect at most five actual cached reads, without fetching URLs again."""
    rows: list[dict[str, Any]] = []
    for cached in list(bodies.values())[-MAX_SOURCES:]:
        content = cached.text
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        identity = hashlib.sha256(
            (cached.final_url + "\n" + digest).encode("utf-8")
        ).hexdigest()[:20]
        rows.append({
            "source_id": identity, "url": cached.url, "final_url": cached.final_url,
            "content_hash": digest, "text": content,
        })
    return rows


def extraction_messages(question: str, goals: Mapping[str, Any],
                        sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The proposal model sees observed text, never an editable source registry."""
    payload = {
        "question": question, "goals": list(goals),
        "sources": [{"source_id": s["source_id"], "text": s["text"]} for s in sources],
        "output": {"claims": [{"goal": "exact goal label", "source_id": "exact source_id",
                               "claim": "one specific factual assertion",
                               "quote": "exact contiguous quotation from source"}]},
    }
    return [
        {"role": "system", "content": (
            "Extract up to 12 concrete, independently checkable assertions from the "
            "provided read-only source texts. A quotation must be EXACTLY copied, "
            "contiguous and sufficient to explain the claim. Do not invent source IDs, "
            "facts, citations, offsets or conclusions. Respond with JSON only. "
            "Empty claims is valid if the texts are inadequate."
        )},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def validate_proposals(raw: str, sources: list[dict[str, Any]],
                       goals: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Never adopt invented sources, misquoted spans or model-supplied offsets."""
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return [], ["extract_not_json"]
    proposed = decoded.get("claims") if isinstance(decoded, dict) else None
    if not isinstance(proposed, list):
        return [], ["extract_schema"]
    by_id = {str(row["source_id"]): row for row in sources}
    valid: list[dict[str, Any]] = []
    rejected: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for item in proposed[:MAX_CLAIMS]:
        if not isinstance(item, dict):
            rejected.append("not_object")
            continue
        goal = item.get("goal")
        source_id = item.get("source_id")
        claim = item.get("claim")
        quote = item.get("quote")
        if (not isinstance(goal, str) or goal not in goals
                or not isinstance(source_id, str) or source_id not in by_id
                or not isinstance(claim, str) or not 5 <= len(claim.strip()) <= 300
                or not isinstance(quote, str) or not 8 <= len(quote) <= 600):
            rejected.append("invalid_claim_or_source")
            continue
        source = by_id[source_id]
        # Recompute the hash over the text actually in the cache, not a re-fetched URL.
        content = str(source["text"])
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != source["content_hash"]:
            rejected.append("source_hash_mismatch")
            continue
        offset = content.find(quote)
        if offset < 0:
            rejected.append("quote_not_in_source")
            continue
        key = (goal, source_id, claim.strip())
        if key in seen:
            continue
        seen.add(key)
        valid.append({
            "claim_id": "c" + str(len(valid) + 1), "goal": goal,
            "claim": claim.strip(), "source_id": source_id,
            "final_url": source["final_url"], "content_hash": source["content_hash"],
            "span_start": offset, "span_end": offset + len(quote), "quote": quote,
        })
    return valid, rejected
