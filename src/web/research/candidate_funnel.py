"""Observe the actual tool-loop owner, independently of the staged reader loop.

These are read-body references used by answer context, not formal Support/Gate
labels. Missing decisions remain explicit gate failures; they are never guessed.
"""

from __future__ import annotations

import hashlib
from typing import Any

from src.web.discovery import url_identity
from src.web.tool_evidence import _public_url, evidence_tool_calls


def candidate_funnel(calls: list[dict[str, Any]], dispositions: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = {url_identity(str(row.get("candidate_id", ""))): row for row in dispositions}
    candidates: dict[str, dict[str, Any]] = {}
    for call in calls:
        if call.get("name") != "web_search":
            continue
        result = call.get("result") or {}
        for rank, item in enumerate(result.get("results") or [], 1):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("link") or "")
            key = url_identity(url)
            providers = item.get("providers") or [item.get("source") or "unreported"]
            row = candidates.setdefault(key, {
                "candidate_id": key, "url": url, "provider": str(providers[0]),
                "provider_rank": rank, "provider_ranks": [], "lifecycle_state": "discovered",
                "skip_reason": "", "attempted_backends": [], "read_outcome": [],
                "assessment_outcome": "not_observed", "evidence_refs": [],
                "scheduled_count": 0, "read_attempt_count": 0,
            })
            row["provider_ranks"].extend({"provider": str(provider), "rank": rank} for provider in providers)
    adopted = {(str(call.get("arguments", {}).get("url")),
                hashlib.sha256(str(call["result"].get("content") or call["result"].get("readme") or "").encode("utf-8")).hexdigest())
               for call in evidence_tool_calls(calls) if call.get("name") == "web_read"}
    failures = []
    for index, call in enumerate(calls):
        if call.get("name") != "web_read":
            continue
        url = str(call.get("arguments", {}).get("url") or "")
        read_candidate = candidates.get(url_identity(url))
        if read_candidate is None:
            continue
        row = read_candidate
        result = call.get("result") or {}
        content = result.get("content") or result.get("readme") or ""
        content = content if isinstance(content, str) else ""
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        backend = str(result.get("method") or result.get("kind") or "general_web_gateway")
        row["attempted_backends"].append(backend)
        row["scheduled_count"] += 1
        row["read_attempt_count"] += 1
        row["lifecycle_state"] = "read_usable" if result.get("ok") is True and content.strip() else "read_attempted"
        row["read_outcome"].append({"call_index": index, "ok": result.get("ok") is True,
                                    "final_url": str(result.get("url") or url),
                                    "content_sha256": digest, "char_count": len(content),
                                    "error": str(result.get("error_code") or result.get("error") or "")[:200]})
        row["assessment_outcome"] = str(result.get("adequacy_reason") or "not_observed")
        if result.get("content_sha256") and result["content_sha256"] != digest:
            failures.append({"candidate_id": row["candidate_id"], "gate": "G0-4", "reason": "read_digest_mismatch"})
        elif (url, digest) in adopted and result.get("answer_eligible") is not False:
            row["lifecycle_state"] = "evidence_adopted"
            row["evidence_refs"].append({"read_call_index": index, "requested_url": url,
                                         "final_url": str(result.get("url") or url),
                                         "content_sha256": digest, "source_span": [0, len(content)],
                                         "kind": "answer_context_read_body"})
    for key, row in candidates.items():
        decision = decisions.get(key, {})
        row["decision_state"] = str(decision.get("state") or "not_observed")
        if not row["read_attempt_count"]:
            row["skip_reason"] = str(decision.get("reason") or "")
            if not _public_url(row["url"]):
                row.update(lifecycle_state="skipped", skip_reason="unsupported_url")
            elif row["skip_reason"] and row["decision_state"] not in {"not_observed", "eligible"}:
                row["lifecycle_state"] = "skipped"
            else:
                failures.append({"candidate_id": key, "gate": "G0-1", "reason": "decision_not_recorded"})
        if row["read_attempt_count"] > 1:
            failures.append({"candidate_id": key, "gate": "G0-2", "reason": "multiple_read_dispatches"})
    rows = list(candidates.values())
    return {"schema_version": "candidate-funnel-v1", "owner": "chat_tool_loop",
            "candidate_count": len(rows), "attempted_reads": sum(row["read_attempt_count"] for row in rows),
            "read_usable": sum(any(read["ok"] and read["char_count"] for read in row["read_outcome"]) for row in rows),
            "evidence_adopted": sum(bool(row["evidence_refs"]) for row in rows),
            "cited": None, "formal_support_assessed": False,
            "backend_scope": "reported_reader_method_or_actual_gateway_executor",
            "gate_failures": failures, "candidates": rows}
