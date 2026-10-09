"""Summarize a model-driven research funnel from existing trace artifacts.

Reads ``{case}-trace.json`` (calls, candidate/read counts, provider errors,
planning proposal mapping) and ``{case}-episode.json`` (admitted questions) and
prints the six bounded stages plus the B-Search-1 saturation analysis (24-cap,
exact duplicates, query sharing). Read-only: never runs search, reads or models.

Usage:
  python tools/summarize_research_funnel.py --dir <evidence-dir> [--out funnel.json]
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any


def _calls(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in (trace.get("calls") or trace.get("tool_calls") or []) if isinstance(c, dict)]


def _planning(trace: dict[str, Any]) -> dict[str, Any]:
    semantics = trace.get("semantics") or {}
    event = next(
        (e for e in semantics.get("events") or [] if e.get("purpose") == "research_task_planning"),
        {},
    )
    return event.get("planning") or {}


def saturation(plan: dict[str, Any]) -> dict[str, Any]:
    mapping = plan.get("proposal_mapping") or []
    proposed = plan.get("proposed_queries") or []
    deferred_ids = plan.get("deferred_rq_ids") or []
    raw = len(mapping)
    targets = [m.get("rq_id") for m in mapping if m.get("rq_id")]
    unique_targets = len(set(targets))
    query_texts = [q.get("query") for q in proposed if q.get("query")]
    per_query = Counter(query_texts)
    targets_with_query = unique_targets - len(deferred_ids)
    return {
        "raw_proposals": raw,
        "unique_targets": unique_targets,
        "exact_duplicates": sum(1 for m in mapping if m.get("exact_duplicate")),
        "cap_24_hit": raw >= 24,
        "proposed_queries": len(proposed),
        "unique_query_texts": len(per_query),
        "queries_serving_multiple_targets": sum(1 for c in per_query.values() if c > 1),
        "deferred_queries_budget": len(plan.get("deferred_queries") or []),
        "deferred_targets_no_query": len(deferred_ids),
        "targets_with_query": targets_with_query,
        "query_reuse_rate": (
            round(1.0 - len(per_query) / unique_targets, 3) if unique_targets else 0.0
        ),
    }


def summarize_case(case: str, trace: dict[str, Any], episode: dict[str, Any] | None) -> dict[str, Any]:
    calls = _calls(trace)
    semantics = trace.get("semantics") or {}
    planning_event = next(
        (e for e in semantics.get("events") or [] if e.get("purpose") == "research_task_planning"),
        {},
    )
    plan = planning_event.get("planning") or {}
    searches = [c for c in calls if c.get("name") == "web_search"]
    reads = [c for c in calls if c.get("name") == "web_read"]
    search_results = 0
    targets_with_search: set[str] = set()
    for call in searches:
        result = call.get("result")
        if isinstance(result, dict) and isinstance(result.get("results"), list):
            search_results += len(result["results"])
        args = call.get("arguments")
        if isinstance(args, dict):
            targets_with_search.update(args.get("rq_ids") or [])
    read_ok = sum(
        1 for c in reads if isinstance(c.get("result"), dict) and c["result"].get("ok") is True
    )
    return {
        "case": case,
        "planning": {
            "questions": len(episode.get("questions") or []) if episode else 0,
            "admitted": semantics.get("decision_admitted"),
            "validation": planning_event.get("validation"),
            "validation_error": planning_event.get("validation_error"),
        },
        "query": {
            "proposed": len(plan.get("proposed_queries") or []),
            "deferred_budget": len(plan.get("deferred_queries") or []),
            "issued_searches": len(searches),
        },
        "candidate": {
            "returned": search_results,
            "passed_to_evidence": trace.get("candidate_count"),
        },
        "read": {
            "attempted": len(reads),
            "ok": read_ok,
            "failed": len(reads) - read_ok,
            "accepted": trace.get("read_count"),
        },
        "evidence": {
            "status": trace.get("evidence_status"),
            "used_sources": len(trace.get("used_sources") or []),
            "targets_with_search": sorted(targets_with_search),
        },
        "terminal": {
            "question_coverage": semantics.get("question_coverage"),
            "coverage_kind": semantics.get("coverage_kind"),
            "error": trace.get("error"),
        },
        "saturation": saturation(plan),
        "provider_errors": trace.get("provider_errors") or [],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    directory = Path(args.dir)
    report = []
    for trace_path in sorted(directory.glob("*-trace.json")):
        case = trace_path.name[: -len("-trace.json")]
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        episode_path = directory / f"{case}-episode.json"
        episode = (
            json.loads(episode_path.read_text(encoding="utf-8")) if episode_path.exists() else None
        )
        report.append(summarize_case(case, trace, episode))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
