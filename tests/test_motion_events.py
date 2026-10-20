"""AR-1B: motion events may propose revisions, never write conclusions.

The controls check the boundary as much as the behaviour: a read that found
nothing must not rewrite anything, a conflict withdraws instead of inventing, and
a condition that predates the reply cannot be applied to it.
"""

import hashlib

import pytest

from src.web.research.answer_revision import (
    RETRACT,
    REPLACE,
    STALE,
    RevisionProposalError,
)
from src.web.research.motion_events import (
    CONDITION_ADDED,
    CONDITION_CORRECTED,
    EVIDENCE_CONFLICT,
    EVIDENCE_READ,
    MAX_RECORDED_EVENTS,
    MOTION_EVENTS,
    MotionEvent,
    READ_FAILED,
    TERMINAL,
    apply_event,
    proposals_for_event,
    record_event,
)
from src.web.research.answer_state import snapshot_from_replies

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


def _event(kind, **overrides):
    values = {"kind": kind, "at": NOW, "round": 2, "notes": 5, "revision": "rev-2", "cause": ""}
    values.update(overrides)
    return MotionEvent(**values)


READ_ID = "read-1"
READ_EXCERPT = "GIMP batch export uses the command line interface."


def _binding(url: str = "https://gimp.org/", quote: str = "batch export uses the command line"):
    return {
        "url": url,
        "quote": quote,
        "content_sha256": hashlib.sha256(quote.encode()).hexdigest(),
        "read_id": READ_ID,
        "read_excerpt_sha256": hashlib.sha256(READ_EXCERPT.encode()).hexdigest(),
    }


def _legacy_binding(url: str = "https://gimp.org/", quote: str = "batch export uses the command line"):
    """A pre-AR-1C binding: it names a URL and a quote, not the read."""

    return {"url": url, "quote": quote, "content_sha256": hashlib.sha256(quote.encode()).hexdigest()}


def _reads():
    from src.web.research.read_evidence import ReadEvidence

    return (
        ReadEvidence.build(
            url="https://gimp.org/",
            excerpt=READ_EXCERPT,
            read_id=READ_ID,
        ),
    )


def _snapshot(replies, **kwargs):
    return snapshot_from_replies(replies, run_id="run1", turn_id="turn1", **kwargs)


# -- the contract ------------------------------------------------------------
def test_the_event_vocabulary_is_closed():
    assert MOTION_EVENTS == {
        EVIDENCE_READ,
        EVIDENCE_CONFLICT,
        CONDITION_ADDED,
        CONDITION_CORRECTED,
        READ_FAILED,
        TERMINAL,
    }
    with pytest.raises(ValueError):
        MotionEvent(kind="rewrite", at=NOW)
    with pytest.raises(ValueError):
        MotionEvent(kind=CONDITION_ADDED, at="")


def test_an_event_is_bounded_and_serializable():
    event = _event(CONDITION_ADDED, cause="x" * 400, detail={"condition": "只比较旧硬件"})
    payload = event.to_dict()

    assert payload["kind"] == CONDITION_ADDED
    assert len(payload["cause"]) == 200
    assert payload["detail"]["condition"] == "只比较旧硬件"


# -- condition changes ------------------------------------------------------
def test_a_new_condition_asks_for_stale_not_retraction():
    snapshot = _snapshot([_reply(content_state={"round": 1, "notes": 2, "revision": "rev-1"})])
    proposals = proposals_for_event(
        _event(CONDITION_ADDED, detail={"condition": "只比较旧硬件环境"}), snapshot
    )

    assert [item.action for item in proposals] == [STALE]
    assert "只比较旧硬件环境" in proposals[0].reason
    # It is a proposal, not a publication: the reply is still current until applied.
    assert snapshot.statements[0].lifecycle == "current"


def test_a_correction_targets_the_same_kinds_of_statement():
    snapshot = _snapshot(
        [
            _reply(content_state={"round": 1, "notes": 2, "revision": "rev-1"}),
            _reply(reply_id="run1:steer:s1", scope="steering", steering_id="s1", lifecycle="retracted"),
        ]
    )
    proposals = proposals_for_event(
        _event(CONDITION_CORRECTED, detail={"condition": "改为仅旧设备"}), snapshot
    )

    # A withdrawn statement is not re-marked.
    assert [item.target_reply_id for item in proposals] == ["run1:research"]


# -- evidence ---------------------------------------------------------------
def test_a_conflict_withdraws_only_the_contested_statements():
    snapshot = _snapshot(
        [
            _reply(),
            _reply(
                reply_id="run1:steer:s1",
                scope="steering",
                steering_id="s1",
                citations=[{"url": "https://other.example/", "quote": "q"}],
            ),
        ]
    )
    proposals = proposals_for_event(
        _event(EVIDENCE_CONFLICT, detail=_verified(["https://gimp.org/"])), snapshot
    )

    assert [item.target_reply_id for item in proposals] == ["run1:research"]
    assert proposals[0].action == RETRACT
    assert proposals[0].replacement == ""


def _verified(urls):
    return {
        "conflicting_urls": list(urls),
        "target_reply_id": "run1:research",
        "verified": True,
    }


def test_an_unverified_conflict_proposes_nothing():
    """Only a checked claim earns a withdrawal right.

    A model that says "these disagree" has named no read and no version, so the
    event carries no `verified` and the shell must not act on it.
    """

    snapshot = _snapshot([_reply()])

    assert (
        proposals_for_event(
            _event(EVIDENCE_CONFLICT, detail={"conflicting_urls": ["https://gimp.org/"]}),
            snapshot,
        )
        == []
    )
    assert (
        proposals_for_event(
            _event(
                EVIDENCE_CONFLICT,
                detail={"conflicting_urls": ["https://gimp.org/"], "verified": True},
            ),
            snapshot,
        )
        == []
    )


def test_a_conflict_without_urls_retracts_nothing():
    """No locatable source means no revision - not "withdraw everything"."""

    snapshot = _snapshot([_reply()])
    proposals = proposals_for_event(_event(EVIDENCE_CONFLICT, detail={}), snapshot)
    assert proposals == []

    replies, decisions, _ = apply_event(
        [_reply()], _event(EVIDENCE_CONFLICT, detail={}), now=NOW, run_id="run1", turn_id="turn1"
    )
    assert decisions == []
    assert replies[0]["lifecycle"] == "open"


def test_a_read_without_bound_text_proposes_nothing():
    snapshot = _snapshot([_reply()])

    assert proposals_for_event(_event(EVIDENCE_READ), snapshot) == []
    assert proposals_for_event(
        _event(EVIDENCE_READ, detail={"replacement": "新结论", "source_refs": []}), snapshot
    ) == []
    assert proposals_for_event(
        _event(EVIDENCE_READ, detail={"replacement": "新结论", "source_refs": ["https://x/"]}),
        snapshot,
    ) == []


def test_a_read_bound_to_a_verified_quote_can_replace():
    snapshot = _snapshot([_reply()])
    proposals = proposals_for_event(
        _event(
            EVIDENCE_READ,
            detail={
                "target_reply_id": "run1:research",
                "replacement": "GIMP 的批量导出依赖命令行；已读材料支持这一点。",
                "source_bindings": [_binding()],
            },
        ),
        snapshot,
    )

    assert [item.action for item in proposals] == [REPLACE]
    assert proposals[0].source_bindings[0]["url"] == "https://gimp.org/"


def test_a_replacement_installs_its_own_citations():
    replies, decisions, _ = apply_event(
        [_reply(citations=[{"url": "https://old.example/", "quote": "old"}])],
        _event(
            EVIDENCE_READ,
            detail={
                "target_reply_id": "run1:research",
                "replacement": "GIMP 的批量导出依赖命令行。",
                "source_bindings": [_binding()],
            },
        ),
        now=NOW,
        run_id="run1",
        turn_id="turn1",
        read_evidence=_reads(),
    )

    assert decisions[0].applied == REPLACE
    urls = [citation["url"] for citation in replies[0]["citations"]]
    assert urls == ["https://gimp.org/"]
    assert "https://old.example/" not in urls


def test_a_binding_whose_quote_does_not_match_its_digest_is_rejected():
    with pytest.raises(RevisionProposalError):
        _event(
            EVIDENCE_READ,
            detail={
                "target_reply_id": "run1:research",
                "replacement": "GIMP 的批量导出依赖命令行。",
                "source_bindings": [
                    {"url": "https://gimp.org/", "quote": "x", "content_sha256": "0" * 64}
                ],
            },
        ).to_dict()
        from src.web.research.answer_revision import RevisionProposal

        RevisionProposal(
            target_reply_id="run1:research",
            target_content_version=3,
            action=REPLACE,
            reason="r",
            replacement="t",
            source_bindings=(
                {"url": "https://gimp.org/", "quote": "x", "content_sha256": "0" * 64},
            ),
        )


def test_a_failed_read_and_a_terminal_status_propose_nothing():
    snapshot = _snapshot([_reply()])

    assert proposals_for_event(_event(READ_FAILED), snapshot) == []
    assert proposals_for_event(_event(TERMINAL, cause="completed"), snapshot) == []


# -- applying an event ------------------------------------------------------
def test_applying_a_condition_event_marks_the_reply_stale_with_an_audit_trail():
    replies, decisions, _ = apply_event(
        [_reply(content_state={"round": 1, "notes": 2, "revision": "rev-1"})],
        _event(CONDITION_ADDED, detail={"condition": "只比较旧硬件环境"}),
        now=NOW,
        run_id="run1",
        turn_id="turn1",
        conditions=("只比较旧硬件环境",),
    )

    assert decisions[0].applied == STALE
    assert replies[0]["stale"] is True
    assert replies[0]["content_version"] == 4
    assert replies[0]["last_revision"]["action"] == STALE
    assert replies[0]["last_revision"]["research_revision"] == "rev-2"


def test_applying_a_conflict_event_retracts_the_statement():
    replies, decisions, _ = apply_event(
        [_reply()],
        _event(EVIDENCE_CONFLICT, detail=_verified(["https://gimp.org/"]), cause="新来源否定"),
        now=NOW,
        run_id="run1",
        turn_id="turn1",
    )

    assert decisions[0].applied == RETRACT
    assert replies[0]["lifecycle"] == "retracted"
    assert "已撤回" in replies[0]["text"]
    assert replies[0]["revision_history"]


def test_an_event_older_than_the_reply_affects_nothing():
    """A statement re-judged after the condition must not be marked again."""

    replies, decisions, _ = apply_event(
        [_reply(content_state={"round": 3, "notes": 9, "revision": "rev-3"})],
        _event(CONDITION_ADDED, round=2, notes=5),
        now=NOW,
        run_id="run1",
        turn_id="turn1",
    )

    assert decisions == []
    assert replies[0]["stale"] is False
    assert replies[0]["content_version"] == 3


def test_applying_the_same_event_twice_is_refused():
    replies, _, _ = apply_event(
        [_reply(content_state={"round": 1, "notes": 2, "revision": "rev-1"})], _event(CONDITION_ADDED), now=NOW, run_id="run1", turn_id="turn1"
    )
    _, decisions, _ = apply_event(
        replies, _event(CONDITION_ADDED), now=NOW, run_id="run1", turn_id="turn1"
    )

    # Idempotent: the second event finds the reply already marked and says so.
    assert decisions[0].accepted is False
    assert decisions[0].refusal == "already_stale"


def test_a_strict_run_refuses_an_unsourced_replacement():
    replies, decisions, _ = apply_event(
        [_reply()],
        _event(
            EVIDENCE_READ,
            detail={
                "target_reply_id": "run1:research",
                "replacement": "一般建议按任务类型选择。",
                "source_refs": [],
            },
            cause="重写",
        ),
        now=NOW,
        run_id="run1",
        turn_id="turn1",
    )

    assert decisions == [] or decisions[0].accepted is True
    # Without refs the event itself proposes nothing, so nothing is replaced.
    assert replies[0]["text"] == "GIMP 的批量导出依赖命令行。"


# -- the motion trace -------------------------------------------------------
def test_the_motion_trace_is_bounded():
    context: dict = {}
    for index in range(MAX_RECORDED_EVENTS + 5):
        record_event(context, _event(READ_FAILED, cause=str(index)))

    assert len(context["revision_events"]) == MAX_RECORDED_EVENTS
    assert context["revision_events"][-1]["cause"] == str(MAX_RECORDED_EVENTS + 4)

def test_the_service_records_the_condition_event_that_caused_the_change(tmp_path):
    """Wiring control: the trace is written where the state change happens."""

    from tests.test_reply_persistence_consistency import _started

    service, repository, run = _started(tmp_path)
    service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
    context = dict(repository.get(run.id).research_context)
    deep = dict(context["deep"])

    service._deep_update_steering_replies(
        context,
        deep,
        run.id,
        incorporated=[{"id": "s2", "kind": "addition", "round": 2}],
    )

    events = context.get("revision_events") or []
    assert [event["kind"] for event in events] == [CONDITION_ADDED]
    assert events[0]["round"] == 2
    assert events[0]["cause"]


def test_the_event_detail_is_bounded():
    event = _event(
        CONDITION_ADDED,
        detail={f"key{index}": "x" * 500 for index in range(20)},
    )
    detail = event.to_dict()["detail"]

    assert len(detail) <= 8
    assert all(len(str(value)) <= 200 for value in detail.values())
