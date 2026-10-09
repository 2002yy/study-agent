"""Observation cannot declare requirements or confer field/stop authority."""

from copy import deepcopy
from dataclasses import replace
import json
import sqlite3

import pytest

from src.web.research.contracts import EvidenceCluster, ResearchQuestion
from src.web.research.evidence_units import EvidenceUnit, RequiredUnit
from src.web.research.lookup_terminal import (
    decide_lookup_terminal,
    requested_lookup_fields,
)
from tests.test_claim_evidence_assessment import (
    _evidence,
    _requirement,
    _state,
    _support,
)
from tests.test_lookup_terminal import native_trace
from tools.trace_research_field_coverage import main, project_field_trace, trace_turn


@pytest.fixture
def inputs(monkeypatch):
    query, calls = native_trace(monkeypatch, "fastapi")
    handoff = decide_lookup_terminal(
        query,
        calls,
        requested_fields=requested_lookup_fields(query),
        allow_standard=True,
    ).handoff
    assert handoff is not None
    result = {
        "publication_authority": False,
        "handoff_sha256": handoff["payload_sha256"],
        "plan": {"query": query},
        "gap_states": {"release_date": {"support_status": "NOT_EVALUATED"}},
        "unresolved_gaps": ["release_date"],
    }
    state = _state(
        requirement=_requirement(),
        evidence=(_evidence("ev1"), _evidence("ev2")),
        links=(
            _support("ev1", cluster="c1", role="primary"),
            _support("ev2", cluster="c2"),
        ),
        clusters=(EvidenceCluster("c1", ("ev1",)), EvidenceCluster("c2", ("ev2",))),
    )
    return (
        handoff,
        result,
        replace(state, questions=(ResearchQuestion("q1", query, "critical"),)),
    )


def test_structural_pass_never_becomes_field_semantic_completion(inputs):
    report = project_field_trace(*inputs)
    assert report["structural_gate"]["status"] == "pass"
    assert report["claim_assessments"][0]["semantic_adequacy"] == "not_evaluated"
    assert report["undeclared_required_unit_claim_ids"] == ["claim1"]
    assert report["evidence_unit_count"] == 0
    assert report["legacy_advisory_coverage_stop"]["recommendation"] == "stop_candidate"
    assert report["field_semantic_completion_observed"] is False
    assert report["publication_authority"] is False


def test_known_version_and_unanswered_date_remain_separate(inputs):
    report = project_field_trace(*inputs)
    rows = {row["field"]: row for row in report["fields"]}
    assert rows["version"]["lookup_status"] == "BOUND"
    assert rows["version"]["lookup_refs"]
    assert rows["release_date"]["lookup_status"] == "UNRESOLVED"
    assert rows["release_date"]["standard_unresolved"] is True
    assert rows["release_date"]["deep_field_binding_status"] == "NOT_EVALUATED"
    assert "distribution_uploaded_at" not in rows


def test_trace_does_not_mutate_request_result_state_or_evidence(inputs):
    handoff, result, state = inputs
    before = deepcopy((handoff, result, state.to_dict()))
    project_field_trace(handoff, result, state)
    assert before == (handoff, result, state.to_dict())


@pytest.mark.parametrize(
    "mutation",
    [
        "digest",
        "question",
        "handoff_authority",
        "standard_authority",
        "standard_hash",
        "standard_query",
        "extra_gap",
        "extra_unresolved",
    ],
)
def test_wrong_identity_scope_hash_or_authority_fail_closed(inputs, mutation):
    handoff, result, state = inputs
    if mutation == "digest":
        handoff["payload_sha256"] = "0" * 64
    elif mutation == "question":
        state = replace(
            state, questions=(ResearchQuestion("q1", "FastAPI 0.136.2 release date"),)
        )
    elif mutation == "handoff_authority":
        handoff["publication_authority"] = True
    elif mutation == "standard_authority":
        result["publication_authority"] = True
    elif mutation == "standard_hash":
        result["handoff_sha256"] = "0" * 64
    elif mutation == "standard_query":
        result["plan"]["query"] = "other project"
    elif mutation == "extra_gap":
        result["gap_states"]["invented_field"] = {"support_status": "SUPPORT"}
    else:
        result["unresolved_gaps"].append("invented_field")
    with pytest.raises(ValueError):
        project_field_trace(handoff, result, state)


def test_reported_standard_support_is_not_recertified(inputs):
    handoff, result, state = inputs
    result["gap_states"]["release_date"]["support_status"] = "SUPPORT"
    result["unresolved_gaps"] = []
    row = next(
        row
        for row in project_field_trace(handoff, result, state)["fields"]
        if row["field"] == "release_date"
    )
    assert row["standard_recorded_status"] == "SUPPORT"
    assert row["deep_field_binding_status"] == "NOT_EVALUATED"


@pytest.mark.parametrize("covered", [False, True])
def test_generic_unit_coverage_does_not_invent_a_field_mapping(inputs, covered):
    handoff, result, state = inputs
    requirement = _requirement(
        required_units=(RequiredUnit("u-date", "release date", "text"),)
    )
    unit = EvidenceUnit("u-date", "text", content="a declared unit", confidence=0.9)
    updated = _state(
        requirement=requirement,
        evidence=(_evidence("ev1", units=(unit,) if covered else ()), _evidence("ev2")),
        links=state.evidence_links,
        clusters=state.source_clusters,
    )
    updated = replace(updated, questions=state.questions)
    report = project_field_trace(handoff, result, updated)
    assert report["claim_assessments"][0]["semantic_adequacy"] == (
        "adequate" if covered else "insufficient"
    )
    assert all(
        row["deep_field_binding_status"] == "NOT_EVALUATED" for row in report["fields"]
    )
    assert report["field_semantic_completion_observed"] is False


def test_field_ids_are_stable_and_do_not_derive_from_evidence(inputs):
    first = project_field_trace(*inputs)
    handoff, result, state = inputs
    state = replace(state, evidence=(), evidence_links=(), source_clusters=())
    second = project_field_trace(handoff, result, state)
    assert [(r["field"], r["field_trace_id"]) for r in first["fields"]] == [
        (r["field"], r["field_trace_id"]) for r in second["fields"]
    ]
    assert len({row["field_trace_id"] for row in first["fields"]}) == len(
        first["fields"]
    )
    json.dumps(first)


def test_missing_turn_is_read_only_and_sql_parameters_are_not_interpolated(tmp_path):
    path = tmp_path / "runtime.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE chat_turns (id TEXT, rag_snapshot TEXT)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="turn not found"):
        trace_turn(path, "'; DROP TABLE chat_turns; --")
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM chat_turns").fetchone()[0] == 0


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_cli_cannot_overwrite_source_database_or_sidecars(
    monkeypatch, tmp_path, suffix
):
    path = tmp_path / "runtime.db"
    path.write_bytes(b"original source")
    monkeypatch.setattr(
        "sys.argv",
        [
            "trace",
            "--db",
            str(path),
            "--turn-id",
            "unused",
            "--out",
            str(path) + suffix,
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert path.read_bytes() == b"original source"
