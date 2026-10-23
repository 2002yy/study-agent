"""AR-1A: the revision contract is deterministic and auditable.

Each test names the behaviour a reader depends on: a statement is kept, marked
uncertain, withdrawn, or replaced only with evidence - and a late writer cannot
undo any of it.
"""

import json

import pytest

from src.web.research.answer_revision import (
    RETRACT,
    REPLACE,
    RevisionProposal,
    RevisionProposalError,
    STALE,
    apply_proposals,
)
from src.web.research.steering_replies import (
    LIFECYCLE_OPEN,
    LIFECYCLE_RETRACTED,
    merge_steering_replies,
)

NOW = "2026-10-20T00:00:00+00:00"


def _reply(**overrides):
    base = {
        "schema": "steering-reply-v1",
        "reply_id": "run1:steer:s1",
        "scope": "steering",
        "steering_id": "s1",
        "turn_id": "turn1",
        "lifecycle": LIFECYCLE_OPEN,
        "stage": "analysis",
        "content_version": 3,
        "based_on_version": 2,
        "stale": False,
        "analysis_state": "ready",
        "text": "版本 A 更适合所有用户。",
        "citations": [],
        "content_state": {"round": 2, "notes": 4, "revision": "rev-1"},
        "updated_at": NOW,
    }
    base.update(overrides)
    return base


def _proposal(**overrides):
    values = {
        "target_reply_id": "run1:steer:s1",
        "target_content_version": 3,
        "action": STALE,
        "reason": "用户新增条件：只比较旧硬件环境",
        "research_round": 2,
        "research_notes": 5,
    }
    values.update(overrides)
    return RevisionProposal(**values)


# -- the four actions stay distinct ------------------------------------------
def test_stale_marks_the_reply_without_changing_its_lifecycle():
    replies, decisions = apply_proposals([_reply()], [_proposal()], now=NOW)

    assert decisions[0].accepted and decisions[0].applied == STALE
    assert replies[0]["stale"] is True
    assert replies[0]["lifecycle"] == LIFECYCLE_OPEN
    assert replies[0]["content_version"] == 4
    assert replies[0]["last_revision"]["reason"].startswith("用户新增条件")


def test_retract_withdraws_the_conclusion_and_keeps_the_record():
    replies, decisions = apply_proposals(
        [_reply()],
        [_proposal(action=RETRACT, reason="新来源否定该结论")],
        now=NOW,
    )

    assert decisions[0].applied == RETRACT
    reply = replies[0]
    assert reply["lifecycle"] == LIFECYCLE_RETRACTED
    assert reply["stale"] is True
    assert "已撤回" in reply["text"]
    assert reply["content_version"] == 4
    assert reply["revision_history"][0]["action"] == RETRACT
    assert reply["revision_history"][0]["from_version"] == 3


def test_replace_publishes_new_text_and_keeps_the_previous_body():
    replacement = "只比较旧硬件环境时，此前的通用推荐不再适用。"
    replies, decisions = apply_proposals(
        [_reply()],
        [_proposal(action=REPLACE, reason="条件改变，需要重写", replacement=replacement)],
        now=NOW,
    )

    assert decisions[0].applied == REPLACE
    reply = replies[0]
    assert reply["text"] == replacement
    assert reply["lifecycle"] == LIFECYCLE_OPEN
    assert reply["content_version"] == 4
    history = reply["revision_history"]
    assert {"text": "版本 A 更适合所有用户。", "content_version": 3, "stage": "analysis"} in history


def test_keep_changes_nothing_at_all():
    original = _reply()
    replies, decisions = apply_proposals(
        [original], [_proposal(action="keep", reason="无关")], now=NOW
    )

    assert decisions[0].applied == "keep"
    assert replies[0] == original


# -- guards ------------------------------------------------------------------
def test_a_proposal_for_an_older_content_version_is_refused():
    replies, decisions = apply_proposals(
        [_reply(content_version=4)], [_proposal(target_content_version=3)], now=NOW
    )

    assert decisions[0].accepted is False
    assert decisions[0].refusal == "stale_target_version"
    assert replies[0]["stale"] is False


def test_a_proposal_from_older_research_is_refused():
    replies, decisions = apply_proposals(
        [_reply(content_state={"round": 3, "notes": 9, "revision": "rev-2"})],
        [_proposal(research_round=2, research_notes=5)],
        now=NOW,
    )

    assert decisions[0].refusal == "older_research_state"
    assert replies[0]["stale"] is False


def test_a_withdrawn_reply_is_terminal_for_late_writers():
    withdrawn = _reply(lifecycle=LIFECYCLE_RETRACTED, text="x（这条判断已撤回，不再作为当前结论）")
    replies, decisions = apply_proposals([withdrawn], [_proposal()], now=NOW)

    assert decisions[0].refusal == "terminal_lifecycle"
    assert replies[0]["lifecycle"] == LIFECYCLE_RETRACTED


def test_replacing_with_an_unbacked_claim_is_refused():
    replies, decisions = apply_proposals(
        [_reply()],
        [
            _proposal(
                action=REPLACE,
                reason="重写",
                replacement="新版本性能提升 35%，官方已经确认。",
            )
        ],
        now=NOW,
    )

    assert decisions[0].refusal == "replacement_unbacked_claim"
    assert replies[0]["text"] == "版本 A 更适合所有用户。"


def test_strict_mode_refuses_a_replacement_without_sources():
    replies, decisions = apply_proposals(
        [_reply()],
        [_proposal(action=REPLACE, reason="重写", replacement="一般建议按任务类型选择。", strict=True)],
        now=NOW,
    )

    assert decisions[0].refusal == "strict_requires_evidence"


def test_replacing_with_a_sourced_claim_is_allowed():
    replies, decisions = apply_proposals(
        [_reply()],
        [
            _proposal(
                action=REPLACE,
                reason="新来源支持",
                replacement="GIMP 的批量导出依赖命令行，已读材料支持这一点。",
                source_refs=("https://gimp.org/",),
            )
        ],
        now=NOW,
    )

    assert decisions[0].applied == REPLACE
    assert replies[0]["text"].startswith("GIMP 的批量导出")


def test_applying_the_same_proposal_twice_is_refused():
    replies, _ = apply_proposals([_reply()], [_proposal()], now=NOW)
    _, decisions = apply_proposals(replies, [_proposal()], now=NOW)

    assert decisions[0].refusal == "stale_target_version"


def test_an_unknown_target_is_refused():
    _, decisions = apply_proposals([_reply()], [_proposal(target_reply_id="run1:other")], now=NOW)

    assert decisions[0].refusal == "unknown_reply"


def test_a_malformed_proposal_is_rejected_before_anything_runs():
    with pytest.raises(RevisionProposalError):
        _proposal(action="rewrite")
    with pytest.raises(RevisionProposalError):
        _proposal(reason="")
    with pytest.raises(RevisionProposalError):
        _proposal(action=REPLACE)  # no replacement


# -- a retraction survives the persistence merge ----------------------------
def test_a_late_open_snapshot_cannot_restore_a_retracted_reply():
    withdrawn = _reply(
        lifecycle=LIFECYCLE_RETRACTED,
        stale=True,
        text="x（这条判断已撤回，不再作为当前结论）",
    )
    late_open = _reply(content_version=9, text="复活")

    merged = merge_steering_replies(
        {"steering_replies": [late_open]}, {"steering_replies": [withdrawn]}
    )
    final = merged["steering_replies"][0]
    assert final["lifecycle"] == LIFECYCLE_RETRACTED
    assert final["text"].endswith("不再作为当前结论）")
    assert (final.get("last_conflict") or {}).get("reason") == "retracted_reopen"


def test_the_revision_audit_round_trips():
    replies, decisions = apply_proposals(
        [_reply()], [_proposal(action=RETRACT, reason="证据推翻")], now=NOW
    )
    payload = json.dumps(
        {"reply": replies[0], "decisions": [d.to_dict() for d in decisions]},
        ensure_ascii=False,
    )
    restored = json.loads(payload)

    assert restored["decisions"][0]["applied"] == RETRACT
    assert restored["reply"]["last_revision"]["action"] == RETRACT
    assert restored["reply"]["lifecycle"] == LIFECYCLE_RETRACTED
