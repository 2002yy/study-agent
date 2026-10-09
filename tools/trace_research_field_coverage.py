"""Read-only RP-1 diagnostic: field coverage is distinct from structural stop.

No runtime consumer imports this tool. It never declares required units, adds
evidence, calls a provider, changes a stop decision or grants publication.
"""

from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.application.research_web_lookup_dispatch import claim_engine_load
from src.domain.runtime_entities import WebLookupRun
from src.repositories.deep_continuation_repository import validate_recorded_terminal
from src.repositories.deep_publication_repository import (
    source_run_digest,
    validate_recorded_publication,
)
from src.web.research.claim_evidence_assessment import assess_claim_evidence
from src.web.research.contracts import ResearchState
from src.web.research.coverage_stop_assessment import assess_coverage_stop
from src.web.research.evidence_gate import evaluate_evidence_gate
from src.web.research.lookup_terminal import load_standard_handoff


def project_field_trace(
    handoff: dict[str, Any], standard_result: dict[str, Any], state: ResearchState
) -> dict[str, Any]:
    """Project validated request obligations; evidence cannot invent requirements.

    Standard status is a recorded observation, not re-certified field support.
    Generic required-unit coverage is reported separately: no frozen field-to-
    unit mapping exists in this protocol, so it cannot bind a requested field.
    """
    frozen = load_standard_handoff(handoff)
    query = frozen["query"]
    if len(state.questions) != 1 or state.questions[0].question_surface != query:
        raise ValueError("field trace question identity mismatch")
    requested = set(frozen["requested_fields"])
    gaps = standard_result.get("gap_states") or {}
    unresolved = standard_result.get("unresolved_gaps") or []
    if (
        standard_result.get("publication_authority") is not False
        or standard_result.get("handoff_sha256") != frozen["payload_sha256"]
        or (standard_result.get("plan") or {}).get("query") != query
        or not set(gaps).issubset(requested)
        or not set(unresolved).issubset(requested)
    ):
        raise ValueError("field trace Standard identity or scope mismatch")
    query_hash = hashlib.sha256(query.encode()).hexdigest()
    rows = []
    for field in sorted(requested):
        known = [ref for ref in frozen["known"] if ref["field"] == field]
        rows.append(
            {
                "field": field,
                "field_trace_id": hashlib.sha256(
                    f"{query_hash}:{field}".encode()
                ).hexdigest(),
                "lookup_status": "BOUND" if known else "UNRESOLVED",
                "lookup_refs": known,
                "standard_recorded_status": (gaps.get(field) or {}).get(
                    "support_status", "NOT_RECORDED"
                ),
                "standard_unresolved": field in unresolved,
                "deep_field_binding_status": "NOT_EVALUATED",
                "reason": "field_unit_mapping_not_declared",
            }
        )
    assessments = [
        assess_claim_evidence(state, claim).to_dict() for claim in state.claims
    ]
    undeclared = [
        claim.id
        for claim in state.claims
        if not claim.evidence_requirement.required_units
    ]
    return {
        "schema_version": "research-field-coverage-trace-v1",
        "query": query,
        "question_sha256": query_hash,
        "handoff_sha256": frozen["payload_sha256"],
        "fields": rows,
        "claim_assessments": assessments,
        "undeclared_required_unit_claim_ids": undeclared,
        "evidence_unit_count": sum(len(evidence.units) for evidence in state.evidence),
        "structural_gate": evaluate_evidence_gate(state).to_dict(),
        "legacy_advisory_coverage_stop": assess_coverage_stop(state).to_dict(),
        "field_semantic_completion_observed": False,
        "publication_authority": False,
        "runtime_state_modified": False,
    }


def _fingerprint(path: Path) -> dict[str, str]:
    # Include WAL if present: the main file alone may omit recent durable rows.
    return {
        str(source): hashlib.sha256(source.read_bytes()).hexdigest()
        for source in (path, Path(str(path) + "-wal"))
        if source.exists()
    }


def trace_turn(db_path: Path, turn_id: str) -> dict[str, Any]:
    path = db_path.resolve(strict=True)
    before = _fingerprint(path)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        turn = db.execute("SELECT * FROM chat_turns WHERE id=?", (turn_id,)).fetchone()
        if turn is None:
            raise ValueError("field trace turn not found")
        rag = json.loads(turn["rag_snapshot"])
        terminal, publication = rag["deep_terminal"], rag["deep_publication"]
        for validator, record in (
            (validate_recorded_terminal, terminal),
            (validate_recorded_publication, publication),
        ):
            valid, reason = validator(
                record, parent_turn_id=turn_id, thread_id=turn["thread_id"]
            )
            if not valid:
                raise ValueError(f"field trace recorded terminal rejected: {reason}")
        parent_id = rag["standard_continuation"]["child_run_id"]
        parent = db.execute(
            "SELECT * FROM web_lookup_runs WHERE id=?", (parent_id,)
        ).fetchone()
        child = db.execute(
            "SELECT * FROM web_lookup_runs WHERE id=?", (terminal["child_run_id"],)
        ).fetchone()
        if parent is None or child is None:
            raise ValueError("field trace lineage missing")
        if (
            child["parent_run_id"] != parent["id"]
            or child["owner_thread_id"] != turn["thread_id"]
            or parent["owner_thread_id"] != turn["thread_id"]
            or publication["source"]["source_run_sha256"] != source_run_digest(child)
        ):
            raise ValueError("field trace lineage or audit hash mismatch")
        values = {
            key: value
            for key, value in dict(child).items()
            if key in {field.name for field in fields(WebLookupRun)}
        }
        for key in (
            "research_context",
            "items",
            "warnings",
            "query_attempts",
            "selected_sources",
            "rejected_sources",
        ):
            values[key] = json.loads(values[key])
        loaded = claim_engine_load(WebLookupRun(**values))
        if not loaded.available or loaded.state is None:
            raise ValueError("field trace validated state unavailable")
        state_before = loaded.state.to_dict()
        result = rag["standard_continuation"]["result"]
        if (
            result["run_parent_turn_id"] != turn_id
            or rag["standard_continuation"]["child_run_id"] != parent["id"]
            or result["source_run_id"] != rag["lookup_terminal"]["owner"]["run_id"]
            or terminal["owner"]["run_id"] != result["source_run_id"]
            or rag["lookup_terminal"]["handoff"]["query"] != turn["user_message"]
        ):
            raise ValueError("field trace request lineage mismatch")
        report = project_field_trace(
            rag["lookup_terminal"]["handoff"], result, loaded.state
        )
        if state_before != loaded.state.to_dict():
            raise ValueError("field trace unexpectedly mutated state")
        report["lineage"] = {
            "thread_id": turn["thread_id"],
            "turn_id": turn_id,
            "run_id": child["id"],
            "parent_run_id": parent["id"],
            "version": child["version"],
            "status": child["status"],
            "stop_reason": child["stop_reason"],
        }
        report["recorded_publication"] = publication
    if before != _fingerprint(path):
        raise ValueError("field trace source changed during read")
    report["source_fingerprints"] = before
    report["source_unchanged"] = True
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--turn-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    sources = [
        args.db.resolve(),
        *(
            Path(str(args.db.resolve()) + suffix)
            for suffix in ("-wal", "-shm", "-journal")
        ),
    ]
    if any(
        args.out.resolve() == source
        or (args.out.exists() and source.exists() and args.out.samefile(source))
        for source in sources
    ):
        parser.error("output cannot overwrite the source database")
    report = trace_turn(args.db, args.turn_id)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "run_id": report["lineage"]["run_id"],
                "fields": len(report["fields"]),
                "source_unchanged": report["source_unchanged"],
                "publication_authority": False,
            }
        )
    )


if __name__ == "__main__":
    main()
