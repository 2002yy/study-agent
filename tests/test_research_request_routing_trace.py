"""Subject-independent diagnostics; advice/reads/complexity never become support."""

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys

import pytest

from src.web.semantic_recovery import ResearchDecision
from tools.trace_research_request_routing import (
    main,
    project_request_routing,
    trace_request,
)


SUBJECTS = [
    "流萤跨版本配队、机制与投入条件",
    "研究另一款游戏角色的历史机制与攻略冲突",
    "比较两款处理器在不同工作负载下的实测与假设",
    "研究陶瓷烧制温度、釉料变化与失败原因",
    "Compare archival accounts of a historical event; retain disagreements.",
    "教我围棋的气与提子，用棋盘验证练习",
    "推导勾股定理，再验证一个几何例子",
    "解释排序算法，并让我运行练习",
]


def snapshot(query, *, rejected=True):
    return {
        "query_plan": {"raw_user_input": query, "knowledge_kind": "empirical"},
        "web_tools": {
            "semantics": {
                "decision_admitted": not rejected,
                "intent": "FALLBACK" if rejected else "NEW_RESEARCH",
                "events": [
                    {
                        "purpose": "research_turn_interpretation",
                        "validation": "rejected",
                        "validation_error": "question_id",
                    }
                ]
                if rejected
                else [],
                "question_coverage": ["rq-existing"],
            },
            "recovery": {"reads": 0, "searches": 2, "status": "candidate_exhausted"},
        },
        "lookup_terminal": {
            "state": "SAFE_ABSTAIN",
            "reason": "requested_claim_plan_unavailable",
        },
    }


@pytest.mark.parametrize("query", SUBJECTS)
def test_domains_preserve_original_and_two_distinct_blockers(query):
    rag = snapshot(query)
    original = deepcopy(rag)
    report = project_request_routing(query, rag)
    assert report["original_question"] == query
    assert report["first_observed_blocker"] == {
        "stage": "semantic_request_planning",
        "reason": "question_id",
    }
    assert (
        report["observed_blockers"][-1]["reason"] == "requested_claim_plan_unavailable"
    )
    assert report["semantic_planning"]["errors"] == [report["first_observed_blocker"]]
    assert report["official_field_scope"]["fields"] == []
    assert report["publication_authority"] is False
    assert report["semantic_adequacy"] == "NOT_EVALUATED"
    assert rag == original


@pytest.mark.parametrize("query", SUBJECTS)
def test_existing_generic_rq_protocol_accepts_domains_without_official_field_adapters(
    query,
):
    raw = {
        "task_id": "owned-task",
        "intent": "NEW_RESEARCH",
        "subject": query,
        "constraints_delta": {},
        "unresolved_questions": [{"id": "rq-preserve-all", "question": query}],
        "suggested_next_action": "plan",
        "proposed_queries": [{"rq_id": "rq-preserve-all", "query": query}],
    }
    parsed = ResearchDecision.parse(raw, task_id="owned-task")
    assert parsed.unresolved_questions[0]["question"] == query
    report = project_request_routing(query, snapshot(query, rejected=False))
    assert report["semantic_planning"]["decision_admitted"] is True
    assert report["first_observed_blocker"]["stage"] == "lookup_terminal"
    assert report["official_field_scope"]["general_plan_authority"] is False
    assert report["recorded_route"]["deep_child_id"] is None


def test_valid_plan_relevance_and_read_count_do_not_certify_support_or_deep():
    query = SUBJECTS[2]
    rag = snapshot(query, rejected=False)
    rag["web_tools"]["recovery"]["reads"] = 5
    report = project_request_routing(query, rag)
    assert report["source_acquisition"]["recorded_reads"] == 5
    assert report["source_acquisition"]["read_backed_source_count"] == 0
    assert report["semantic_planning"]["relevance_is_support"] is False
    assert report["recorded_route"]["deep_child_id"] is None
    assert report["publication_authority"] is False


def test_missing_observations_stay_unknown_not_verified_or_zero_budget():
    report = project_request_routing(SUBJECTS[5], {})
    assert report["recorded_route"]["lookup_state"] == "NOT_RECORDED"
    assert report["source_acquisition"]["recorded_reads"] == "NOT_RECORDED"
    assert report["semantic_planning"]["decision_admitted"] == "NOT_RECORDED"
    assert report["first_observed_blocker"] is None
    assert (
        report["semantic_planning"]["raw_model_response"]
        == "NOT_RECORDED_IN_THIS_SNAPSHOT"
    )


def test_query_substitution_refused():
    with pytest.raises(ValueError, match="original query mismatch"):
        project_request_routing("target 4.2", snapshot("target 4.1"))


def test_failure_before_terminal_is_preserved_for_teaching():
    rag = snapshot(SUBJECTS[5])
    del rag["lookup_terminal"]
    report = project_request_routing(SUBJECTS[5], rag)
    assert len(report["observed_blockers"]) == 1
    assert report["recorded_route"]["lookup_state"] == "NOT_RECORDED"


def make_db(path: Path):
    query = SUBJECTS[0]
    rag = snapshot(query)
    rag["lookup_terminal"]["owner"] = {
        "thread_id": "thread",
        "turn_id": "turn",
        "run_id": "run",
    }
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE chat_turns(id TEXT, thread_id TEXT, user_message TEXT, rag_snapshot TEXT)"
        )
        db.execute(
            "CREATE TABLE web_lookup_runs(id TEXT, owner_thread_id TEXT, query TEXT)"
        )
        db.execute(
            "INSERT INTO chat_turns VALUES (?,?,?,?)",
            ("turn", "thread", query, json.dumps(rag)),
        )
        db.execute(
            "INSERT INTO web_lookup_runs VALUES (?,?,?)", ("run", "thread", query)
        )
    return rag


def test_actual_sqlite_read_only_fingerprint_and_parameterized_identity(tmp_path):
    path = tmp_path / "runtime.db"
    make_db(path)
    before = path.read_bytes()
    report = trace_request(path, "turn")
    assert report["source_unchanged"] is True
    assert report["lineage"] == {
        "thread_id": "thread",
        "turn_id": "turn",
        "run_id": "run",
    }
    with pytest.raises(ValueError, match="turn not found"):
        trace_request(path, "turn' OR 1=1 --")
    assert path.read_bytes() == before


@pytest.mark.parametrize("corruption", ["thread", "turn", "run_owner", "run_query"])
def test_wrong_owner_or_request_lineage_rejected(tmp_path, corruption):
    path = tmp_path / "runtime.db"
    rag = make_db(path)
    with sqlite3.connect(path) as db:
        if corruption in {"thread", "turn"}:
            rag["lookup_terminal"]["owner"][corruption + "_id"] = "wrong"
            db.execute("UPDATE chat_turns SET rag_snapshot=?", (json.dumps(rag),))
        elif corruption == "run_owner":
            db.execute("UPDATE web_lookup_runs SET owner_thread_id='wrong'")
        else:
            db.execute("UPDATE web_lookup_runs SET query='different version'")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="owner mismatch|lineage mismatch"):
        trace_request(path, "turn")
    assert path.read_bytes() == before


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm"])
def test_cli_cannot_overwrite_database_or_sidecars(tmp_path, monkeypatch, suffix):
    path = tmp_path / "runtime.db"
    make_db(path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["trace", "--db", str(path), "--turn-id", "turn", "--out", str(path) + suffix],
    )
    before = path.read_bytes()
    with pytest.raises(ValueError, match="overwrite source"):
        main()
    assert path.read_bytes() == before


def test_cli_json_report_does_not_mutate_source(tmp_path, monkeypatch):
    path = tmp_path / "runtime.db"
    make_db(path)
    out = tmp_path / "trace.json"
    before = path.read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        ["trace", "--db", str(path), "--turn-id", "turn", "--out", str(out)],
    )
    main()
    assert json.loads(out.read_text(encoding="utf-8"))["publication_authority"] is False
    assert path.read_bytes() == before
