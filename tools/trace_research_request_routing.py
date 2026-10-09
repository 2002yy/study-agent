"""Read-only planning/route diagnosis across subjects; never admits a task.

Existing semantic advice, narrow official-field authority and verified support
are different contracts. Do not infer an accepted plan from candidate sources.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.web.research.lookup_terminal import (
    load_standard_handoff,
    requested_lookup_fields,
)
from src.web.tool_evidence import trusted_tool_calls
from tools.trace_research_field_coverage import _fingerprint, trace_turn


def project_request_routing(query: str, rag: dict[str, Any]) -> dict[str, Any]:
    """Report persisted observations, not an inferred route or semantic verdict."""
    plan = rag.get("query_plan") or {}
    if plan.get("raw_user_input", query) != query:
        raise ValueError("request routing original query mismatch")
    tools = rag.get("web_tools") or {}
    semantics = tools.get("semantics") or {}
    errors = [
        {
            "stage": "semantic_request_planning",
            "reason": event.get("validation_error", "unspecified_validation_error"),
        }
        for event in semantics.get("events", [])
        if event.get("purpose") == "research_turn_interpretation"
        and event.get("validation") == "rejected"
    ]
    terminal = rag.get("lookup_terminal") or {}
    semantic_errors = list(errors)
    fields = requested_lookup_fields(query)
    if terminal.get("handoff"):
        handoff = load_standard_handoff(terminal["handoff"])
        if handoff["query"] != query or set(handoff["requested_fields"]) != set(fields):
            raise ValueError("request routing handoff scope mismatch")
    if terminal.get("state") == "SAFE_ABSTAIN":
        errors.append({"stage": "lookup_terminal", "reason": terminal.get("reason")})
    calls = tools.get("calls") or []
    reads = [call for call in trusted_tool_calls(calls) if call["name"] == "web_read"]
    recovery = tools.get("recovery") or {}
    return {
        "schema_version": "research-request-routing-trace-v1",
        "original_question": query,
        "original_sha256": hashlib.sha256(query.encode()).hexdigest(),
        "query_plan": {
            "recorded": bool(plan),
            "knowledge_kind": plan.get("knowledge_kind", "NOT_RECORDED"),
            "force_retrieval": plan.get("force_retrieval", "NOT_RECORDED"),
        },
        "semantic_planning": {
            "recorded": bool(semantics),
            "decision_admitted": semantics.get("decision_admitted", "NOT_RECORDED"),
            "intent": semantics.get("intent", "NOT_RECORDED"),
            "errors": semantic_errors,
            "rq_relevance_observation": semantics.get("question_coverage", []),
            "relevance_is_support": False,
            "raw_model_response": "NOT_RECORDED_IN_THIS_SNAPSHOT",
        },
        "official_field_scope": {
            "status": "DECLARED" if fields else "UNSUPPORTED_BY_STRICT_FIELD_PLANNER",
            "fields": list(fields),
            "general_plan_authority": False,
        },
        "source_acquisition": {
            "read_backed_source_count": len(reads),
            "recorded_reads": recovery.get("reads", "NOT_RECORDED"),
            "recorded_searches": recovery.get("searches", "NOT_RECORDED"),
            "recorded_end": recovery.get("status", "NOT_RECORDED"),
            "limits": recovery.get("limits", {}),
            "support_qualification": "NOT_INFERRED_FROM_READ_COUNT",
        },
        "recorded_route": {
            "lookup_state": terminal.get("state", "NOT_RECORDED"),
            "lookup_reason": terminal.get("reason", "NOT_RECORDED"),
            "standard_child_id": (rag.get("standard_continuation") or {}).get(
                "child_run_id"
            ),
            "deep_child_id": (rag.get("deep_terminal") or {}).get("child_run_id"),
        },
        "observed_blockers": errors,
        "first_observed_blocker": errors[0] if errors else None,
        "semantic_adequacy": "NOT_EVALUATED",
        "publication_authority": False,
        "runtime_state_modified": False,
    }


def trace_request(db_path: Path, turn_id: str) -> dict[str, Any]:
    path = db_path.resolve(strict=True)
    before = _fingerprint(path)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        turn = db.execute("SELECT * FROM chat_turns WHERE id=?", (turn_id,)).fetchone()
        if turn is None:
            raise ValueError("request routing turn not found")
        rag = json.loads(turn["rag_snapshot"])
        terminal = rag.get("lookup_terminal") or {}
        if terminal:
            owner = terminal.get("owner") or {}
            if (
                owner.get("thread_id") != turn["thread_id"]
                or owner.get("turn_id") != turn_id
            ):
                raise ValueError("request routing owner mismatch")
        run_id = (terminal.get("owner") or {}).get("run_id") or (
            rag.get("web_tools") or {}
        ).get("run_id")
        if run_id:
            run = db.execute(
                "SELECT * FROM web_lookup_runs WHERE id=?", (run_id,)
            ).fetchone()
            if (
                run is None
                or run["owner_thread_id"] != turn["thread_id"]
                or run["query"] != turn["user_message"]
            ):
                raise ValueError("request routing run lineage mismatch")
        report = project_request_routing(turn["user_message"], rag)
        report["lineage"] = {
            "thread_id": turn["thread_id"],
            "turn_id": turn_id,
            "run_id": run_id,
        }
    if rag.get("deep_terminal"):
        # Reuse original terminal/publication/hash/state validation, not a new authority.
        deep = trace_turn(path, turn_id)
        report["deep_structure_observation"] = {
            "lineage": deep["lineage"],
            "structural_gate": deep["structural_gate"],
            "undeclared_generic_unit_claim_ids": deep[
                "undeclared_required_unit_claim_ids"
            ],
        }
    if before != _fingerprint(path):
        raise ValueError("request routing source changed during read")
    report["source_fingerprints"] = before
    report["source_unchanged"] = True
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--turn-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    source = args.db.resolve(strict=True)
    if args.out.resolve() in {
        source,
        Path(str(source) + "-wal"),
        Path(str(source) + "-shm"),
    }:
        raise ValueError("request routing output cannot overwrite source")
    report = trace_request(source, args.turn_id)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
