"""AR-1A: the static snapshot keeps three questions apart.

* what a statement *is* (content kind),
* how far it has been *checked* (verification),
* whether it may still be read as the current answer (lifecycle).

The controls below are the ones a reader depends on: a finished run is not a
verified conclusion, "verifying" does not empty the answer, and a withdrawn
statement never returns to being current.
"""

import json

from src.web.research.answer_state import (
    CONFLICT,
    CONTENT_KINDS,
    CURRENT,
    GAP_MISSING_EVIDENCE,
    GAP_UNREAD_ATTACHMENT,
    INSUFFICIENT,
    LIFECYCLE_VIEWS,
    MOTION_STATES,
    PENDING_VERIFICATION,
    SUPPORTED,
    SUPERSEDED,
    VERIFICATION_STATES,
    WITHHELD,
    snapshot_from_replies,
    statement_kind,
    statement_lifecycle,
    statement_verification,
)

NOW = "2026-10-20T00:00:00+00:00"


def _reply(**overrides):
    base = {
        "schema": "steering-reply-v1",
        "reply_id": "run1:research",
        "scope": "research",
        "steering_id": "",
        "turn_id": "turn1",
        "lifecycle": "open",
        "stage": "evidence_update",
        "content_version": 3,
        "stale": False,
        "analysis_state": "ready",
        "text": "GIMP 的批量导出依赖命令行。",
        "citations": [{"url": "https://gimp.org/", "quote": "batch"}],
        "content_state": {"round": 2, "notes": 4, "revision": "rev-1"},
        "updated_at": NOW,
    }
    base.update(overrides)
    return base


def _snapshot(replies, **kwargs):
    return snapshot_from_replies(
        replies, run_id="run1", turn_id="turn1", **kwargs
    )


# -- the vocabularies are separate -------------------------------------------
def test_the_three_vocabularies_do_not_overlap():
    assert CONTENT_KINDS == {"knowledge", "evidence", "conditional", "unverified"}
    assert VERIFICATION_STATES == {
        SUPPORTED,
        CONFLICT,
        INSUFFICIENT,
        PENDING_VERIFICATION,
        WITHHELD,
    }
    assert LIFECYCLE_VIEWS == {CURRENT, SUPERSEDED, "retracted", "closed"}
    # A content kind is never a verification verdict, and never a lifecycle.
    assert not (CONTENT_KINDS & VERIFICATION_STATES)
    assert not (CONTENT_KINDS & LIFECYCLE_VIEWS)
    assert "verifying" in MOTION_STATES and "verifying" not in VERIFICATION_STATES


def test_a_kind_does_not_imply_a_verdict():
    knowledge = _reply(stage="knowledge", citations=[])
    evidence = _reply(stage="evidence_update")

    assert statement_kind(knowledge) == "knowledge"
    assert statement_kind(evidence) == "evidence"
    # Both are checked independently of their kind.
    assert statement_verification(knowledge) == PENDING_VERIFICATION
    assert statement_verification(evidence) == SUPPORTED


# -- a finished run is not a verified conclusion ------------------------------
def test_a_completed_run_without_sources_is_not_supported():
    snapshot = _snapshot(
        [_reply(stage="analysis", citations=[], analysis_state="ready")],
        research_state={"status": "completed", "round": 2, "notes": 4},
    )

    statement = snapshot.statements[0]
    assert statement.verification == PENDING_VERIFICATION
    assert statement.verification != SUPPORTED
    assert snapshot.research_state["status"] == "completed"


def test_a_sourced_judgment_without_citations_is_insufficient():
    snapshot = _snapshot([_reply(citations=[])])

    assert snapshot.statements[0].verification == INSUFFICIENT
    assert snapshot.statements[0].text  # it stays readable, just unsupported


# -- motion state does not decide what is answerable -------------------------
def test_verifying_does_not_empty_the_current_answer():
    supported = _reply()
    pending = _reply(
        reply_id="run1:steer:s1",
        scope="steering",
        steering_id="s1",
        stage="analysis",
        citations=[],
        text="需要复核：只比较旧硬件环境。",
    )
    snapshot = _snapshot(
        [supported, pending],
        research_state={"status": "running", "motion": "verifying"},
    )

    current = snapshot.current_statements()
    # Both are shown; only the sourced one is verified.
    assert [item.reply_id for item in current] == ["run1:research", "run1:steer:s1"]
    verified = snapshot.verified_statements()
    assert [item.reply_id for item in verified] == ["run1:research"]


def test_a_pending_statement_is_current_but_not_verified():
    snapshot = _snapshot([_reply(stale=True)])
    statement = snapshot.statements[0]

    assert statement.verification == PENDING_VERIFICATION
    assert statement.text
    assert snapshot.current_statements() == (statement,)
    assert snapshot.verified_statements() == ()


def test_a_statement_the_run_excluded_is_withheld():
    snapshot = _snapshot([_reply(result_state="not_included")])
    statement = snapshot.statements[0]

    assert statement.verification == WITHHELD
    assert statement.text
    assert snapshot.current_statements() == ()


# -- withdrawn and superseded are never current ------------------------------
def test_retracted_and_superseded_are_not_current():
    snapshot = _snapshot(
        [_reply(lifecycle="retracted"), _reply(reply_id="run1:steer:s1", lifecycle="superseded")]
    )

    assert snapshot.current_statements() == ()
    assert {item.lifecycle for item in snapshot.statements} == {"retracted", SUPERSEDED}


def test_lifecycle_mapping_is_explicit():
    assert statement_lifecycle(_reply()) == CURRENT
    assert statement_lifecycle(_reply(lifecycle="retracted")) == "retracted"
    assert statement_lifecycle(_reply(lifecycle="superseded")) == SUPERSEDED
    assert statement_lifecycle(_reply(lifecycle="closed")) == "closed"


# -- bidirectional feedback: the snapshot states its gaps -------------------
def test_a_pending_statement_becomes_a_motion_directive():
    snapshot = _snapshot([_reply(citations=[], stage="analysis", text="推荐需要按新条件重算。")])

    gaps = snapshot.gaps
    assert gaps and gaps[0].kind == GAP_MISSING_EVIDENCE
    assert gaps[0].reply_id == "run1:research"
    assert "重算" in gaps[0].text


def test_an_unread_attachment_is_its_own_directive():
    snapshot = _snapshot([_reply()], attachment_present=True)

    assert any(gap.kind == GAP_UNREAD_ATTACHMENT for gap in snapshot.gaps)


def test_a_fully_supported_snapshot_has_no_gaps():
    snapshot = _snapshot([_reply()])

    assert snapshot.gaps == ()
    assert snapshot.current_statements()[0].verification == SUPPORTED


# -- audit ------------------------------------------------------------------
def test_the_snapshot_round_trips_through_json():
    snapshot = _snapshot(
        [_reply(), _reply(reply_id="run1:steer:s1", lifecycle="retracted")],
        conditions=("只比较旧硬件环境",),
        research_state={"status": "partial", "round": 2, "notes": 4, "revision": "rev-1"},
    )
    restored = json.loads(json.dumps(snapshot.to_dict(), ensure_ascii=False))

    assert restored["schema_version"] == "static-answer-v1"
    # Sorted by reply_id: the research reply first, then the supplement.
    assert [item["lifecycle"] for item in restored["statements"]] == ["current", "retracted"]
    assert restored["conditions"] == ["只比较旧硬件环境"]
    assert restored["research_state"]["status"] == "partial"
