"""AR-1C-1: the coordinator is pure, idempotent and equivalent to the old path.

The pairing tests are the point: the coordinator must reproduce exactly what the
runtime already does for an addition (stale) and a correction (supersede), so it
can later become the single writer without silently changing behaviour.
"""

import json

from src.web.research.answer_coordinator import SKIP_DUPLICATE_EVENT, coordinate
from src.web.research.motion_events import (
    CONDITION_ADDED,
    CONDITION_CORRECTED,
    EVIDENCE_CONFLICT,
    READ_FAILED,
    MotionEvent,
)
from src.web.research.steering_replies import (
    mark_additions_stale,
    supersede_affected,
)

NOW = "2026-10-20T00:00:00+00:00"


def _reply(reply_id="run1:research", **overrides):
    base = {
        "schema": "steering-reply-v1",
        "reply_id": reply_id,
        "scope": "research" if reply_id.endswith("research") else "steering",
        "steering_id": "" if reply_id.endswith("research") else "s1",
        "turn_id": "turn1",
        "lifecycle": "open",
        "stage": "analysis",
        "content_version": 2,
        "based_on_version": 1,
        "stale": False,
        "analysis_state": "ready",
        "text": "版本 A 更适合所有用户。",
        "focus": "自动编辑",
        "reason": "",
        "questions": [],
        "citations": [],
        "content_state": {"round": 1, "notes": 2, "revision": "rev-1"},
        "updated_at": NOW,
    }
    base.update(overrides)
    return base


def _event(kind, **overrides):
    values = {"kind": kind, "at": NOW, "round": 2, "notes": 3, "revision": "rev-2"}
    values.update(overrides)
    return MotionEvent(**values)


def _coordinate(replies, event, **kwargs):
    return coordinate(
        replies,
        event,
        now=NOW,
        run_id="run1",
        turn_id="turn1",
        **kwargs,
    )


# -- purity and idempotency -------------------------------------------------
def test_the_coordinator_is_pure():
    replies = [_reply(), _reply("run1:steer:s1", text="另一条判断。")]
    first = _coordinate(replies, _event(CONDITION_ADDED, detail={"keep_reply_id": "run1:steer:s2"}))
    second = _coordinate(replies, _event(CONDITION_ADDED, detail={"keep_reply_id": "run1:steer:s2"}))

    assert first.replies == second.replies
    assert first.audit == second.audit
    # The input list itself is untouched.
    assert replies[0]["stale"] is False


def test_a_consumed_event_is_skipped():
    event = _event(CONDITION_ADDED, detail={"keep_reply_id": "run1:steer:s2"})
    first = _coordinate([_reply()], event)
    second = _coordinate(
        list(first.replies), event, consumed_event_ids=[event.identity()]
    )

    assert first.audit["applied"]
    assert second.audit["skipped"] == SKIP_DUPLICATE_EVENT
    assert second.audit["applied"] == []
    assert second.replies == first.replies


def test_an_event_identity_is_stable_across_rebuilds():
    first = _event(CONDITION_ADDED, detail={"condition": "x"})
    second = _event(CONDITION_ADDED, detail={"condition": "x"})
    assert first.identity() == second.identity()

    other = _event(CONDITION_ADDED, detail={"condition": "y"})
    assert other.identity() != first.identity()


# -- pairing: addition ------------------------------------------------------
def test_the_addition_transition_matches_the_legacy_path_exactly():
    replies = [
        _reply("run1:research", content_state={"round": 1, "notes": 2, "revision": "rev-1"}),
        _reply("run1:steer:s1", text="旧判断。", content_state={"round": 1, "notes": 2, "revision": "rev-1"}),
        _reply("run1:steer:s2", text="新补充回执。", content_state={"round": 2, "notes": 3, "revision": "rev-2"}),
    ]
    legacy = mark_additions_stale(
        replies,
        keep_reply_id="run1:steer:s2",
        added_round=2,
        now=NOW,
    )
    coordinated = _coordinate(
        replies,
        _event(CONDITION_ADDED, detail={"keep_reply_id": "run1:steer:s2"}),
    ).replies

    for before, after in zip(legacy, coordinated):
        assert after["stale"] == before["stale"]
        assert after["content_version"] == before["content_version"]
        assert after["based_on_version"] == before["based_on_version"]
        assert after["text"] == before["text"]
    assert [item["stale"] for item in coordinated] == [True, True, False]


# -- pairing: correction ----------------------------------------------------
def test_the_correction_transition_matches_the_legacy_path_exactly():
    replies = [
        _reply("run1:steer:s1", text="自动编辑改变了比较标准。", focus="自动编辑"),
        _reply("run1:research", text="导出流程的一般判断。", focus="导出"),
    ]
    legacy = supersede_affected(replies, old_terms=["自动编辑"], now=NOW)
    result = _coordinate(
        replies,
        _event(CONDITION_CORRECTED, detail={"old_terms": ["自动编辑"]}),
    )

    for before, after in zip(legacy, result.replies):
        assert after["lifecycle"] == before["lifecycle"]
        assert after["content_version"] == before["content_version"]
        assert after["text"] == before["text"]
    assert result.replies[0]["lifecycle"] == "superseded"
    assert result.replies[1]["lifecycle"] == "open"
    assert result.audit["applied"]


# -- non-revising events ----------------------------------------------------
def test_a_failed_read_changes_nothing():
    result = _coordinate([_reply()], _event(READ_FAILED))

    assert result.replies[0]["stale"] is False
    assert result.audit["applied"] == []


def test_a_conflict_without_a_source_location_changes_nothing():
    result = _coordinate([_reply()], _event(EVIDENCE_CONFLICT, detail={}))

    assert result.replies[0]["lifecycle"] == "open"
    assert result.audit["applied"] == []


# -- audit ------------------------------------------------------------------
def test_the_audit_names_what_changed_and_the_versions():
    result = _coordinate(
        [_reply()],
        _event(CONDITION_ADDED, detail={"keep_reply_id": "run1:steer:s2", "condition": "只比较旧设备"}),
    )

    audit = result.audit
    assert audit["schema_version"] == "answer-coordination-v1"
    assert audit["applied"][0]["action"] == "stale"
    assert audit["before_version"] == 2
    assert audit["after_version"] == 3
    json.dumps(audit, ensure_ascii=False)  # serializable
