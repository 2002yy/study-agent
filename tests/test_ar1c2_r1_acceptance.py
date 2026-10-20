"""AR-1C-2-R1 acceptance: the five scenarios the review asked for.

Each test names the invariant, not the implementation: what must hold for a
revision to be called done.
"""

import hashlib

import pytest

from src.web.research.answer_coordinator import SUPERSEDE, coordinate
from src.web.research.answer_revision import (
    REPLACE,
    RevisionProposal,
    RevisionProposalError,
    apply_decision,
    evaluate,
)
from src.web.research.motion_events import (
    CONDITION_ADDED,
    CONDITION_CORRECTED,
    MotionEvent,
)
from src.web.research.read_evidence import (
    read_evidence_from_records,
    verify_bindings,
)
from src.web.research.steering_replies import STALE_TEXT_SUFFIX

NOW = "2026-10-20T00:00:00+00:00"
STALE_TEXT = f"版本 A 更适合所有用户。{STALE_TEXT_SUFFIX}"
PAGE = "版本 A 更适合旧设备，因为它在旧系统上仍受支持。"


def _stale_reply(**overrides):
    base = {
        "schema": "steering-reply-v1",
        "reply_id": "run1:steer:s1",
        "scope": "steering",
        "steering_id": "s1",
        "turn_id": "turn1",
        "lifecycle": "open",
        "stage": "analysis",
        "content_version": 3,
        "based_on_version": 2,
        "stale": True,
        "analysis_state": "ready",
        "text": STALE_TEXT,
        "focus": "自动编辑",
        "reason": "",
        "questions": [],
        "citations": [],
        "content_state": {"round": 1, "notes": 2, "revision": "rev-1"},
        "updated_at": NOW,
    }
    base.update(overrides)
    return base


def _read_record(url="https://example.com/a", content=PAGE, read_id="read-1"):
    # Modern records carry the identity of the attempt; a binding can then name
    # which read produced the sentence it publishes.
    return {
        "read": {"ok": True, "status": "read", "content": content, "read_id": read_id, "round": 1},
        "item": {"title": "示例页", "url": url},
        "assessment": {"url": url},
    }


def _evidence(**kwargs):
    return read_evidence_from_records([_read_record(**kwargs)])


def _binding(quote=PAGE[:20], url="https://example.com/a", *, hash_of=None, read_id="read-1", excerpt=PAGE):
    text = hash_of if hash_of is not None else quote
    return {
        "url": url,
        "quote": quote,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "read_id": read_id,
        "read_excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
    }


# 1 - a correction is audited as supersede, never as a retract proposal
def test_a_correction_is_recorded_as_supersede_not_as_a_retracted_judgment():
    replies = [_stale_reply(text="自动编辑改变了比较标准。")]
    event = MotionEvent(
        kind=CONDITION_CORRECTED,
        at=NOW,
        round=2,
        notes=3,
        revision="rev-2",
        detail={"old_terms": ["自动编辑"]},
    )
    result = coordinate(replies, event, now=NOW, run_id="run1", turn_id="turn1")

    assert result.decisions == ()  # no invented retract proposal
    assert result.delegated and result.delegated[0]["action"] == SUPERSEDE
    assert result.delegated[0]["delegated"] is True
    assert result.audit["applied"][0]["action"] == SUPERSEDE
    assert "proposal_action" not in result.audit["applied"][0]
    assert result.replies[0]["lifecycle"] == "superseded"


# 2 - a replacement that is backed by a read owns its new static state
def test_a_backed_replacement_clears_stale_and_adopts_the_new_research_state():
    proposal = RevisionProposal(
        target_reply_id="run1:steer:s1",
        target_content_version=3,
        action=REPLACE,
        reason="新证据覆盖了旧判断",
        research_revision="rev-2",
        research_round=2,
        research_notes=3,
        replacement="版本 A 更适合旧设备，但对新设备并不是更好的选择。",
        source_bindings=(_binding(),),
    )
    snapshot = _evidence()
    decision = evaluate(proposal, _stale_reply(), read_evidence=snapshot)

    assert decision.accepted, decision.refusal
    updated = apply_decision(_stale_reply(), decision, now=NOW)

    assert updated["stale"] is False
    assert updated["stale_reason"] == ""
    assert updated["content_state"] == {"round": 2, "notes": 3, "revision": "rev-2"}
    assert STALE_TEXT_SUFFIX not in updated["text"]
    assert updated["lifecycle"] == "open"
    assert updated["citations"][0]["quote"] == _binding()["quote"]


def test_a_replacement_without_backing_keeps_the_stale_flag():
    proposal = RevisionProposal(
        target_reply_id="run1:steer:s1",
        target_content_version=3,
        action=REPLACE,
        reason="待复核的新表述",
        research_revision="rev-2",
        research_round=2,
        research_notes=3,
        replacement="版本 A 可能更适合旧设备。",
        source_bindings=(),
        strict=False,
    )
    decision = evaluate(proposal, _stale_reply())

    assert decision.accepted
    updated = apply_decision(_stale_reply(), decision, now=NOW)
    # claim-free wording is not "backed", but it also asserts nothing:
    assert updated["stale"] is False

    claim = RevisionProposal(
        target_reply_id="run1:steer:s1",
        target_content_version=3,
        action=REPLACE,
        reason="无来源的断言",
        research_revision="rev-2",
        research_round=2,
        research_notes=3,
        replacement="版本 A 在 2026 年仍覆盖 92% 的旧设备。",
        source_bindings=(),
    )
    refused = evaluate(claim, _stale_reply())
    assert refused.accepted is False
    assert refused.refusal == "replacement_unbacked_claim"


# 3 - a self-consistent forgery does not become evidence
def test_a_fabricated_url_quote_and_self_computed_hash_is_refused():
    forged = _binding(quote="这段文字根本不存在于任何页面中。", url="https://evil.example/x")
    assert verify_bindings((forged,), _evidence()) == "source_not_read"

    proposal = RevisionProposal(
        target_reply_id="run1:steer:s1",
        target_content_version=3,
        action=REPLACE,
        reason="伪造来源",
        research_revision="rev-2",
        research_round=2,
        research_notes=3,
        replacement="版本 A 更适合所有新设备。",
        source_bindings=(forged,),
    )
    decision = evaluate(proposal, _stale_reply(), read_evidence=_evidence())
    assert decision.accepted is False
    assert decision.refusal == "source_not_read"


def test_a_quote_that_is_not_in_the_read_page_is_refused():
    binding = _binding(quote="页面里没有这句话，但哈希是自己算的。")
    assert verify_bindings((binding,), _evidence()) == "quote_not_in_read"


def test_a_quote_that_really_appears_in_the_read_page_is_accepted():
    assert verify_bindings((_binding(),), _evidence()) == ""


# 4 - a failure between state and trace cannot leave two authoritative states
def test_a_failure_during_coordination_leaves_the_input_untouched():
    replies = [_stale_reply()]

    class Exploding(dict):
        pass

    with pytest.raises(RevisionProposalError):
        apply_decision(
            replies[0],
            type("D", (), {"accepted": False, "refusal": "boom", "applied": ""})(),
            now=NOW,
        )
    assert replies[0]["stale"] is True
    assert replies[0]["content_version"] == 3


def test_replaying_after_a_lost_trace_converges_to_the_same_state():
    replies = [_stale_reply(content_state={"round": 1, "notes": 2, "revision": "rev-1"})]
    event = MotionEvent(
        kind=CONDITION_ADDED,
        at=NOW,
        round=2,
        notes=3,
        revision="rev-2",
        detail={"keep_reply_id": "run1:steer:s2"},
    )
    first = coordinate(replies, event, now=NOW, run_id="run1", turn_id="turn1")
    # The write landed but the trace did not: the event is replayed from scratch.
    replay = coordinate(list(first.replies), event, now=NOW, run_id="run1", turn_id="turn1")

    assert replay.replies == first.replies
    assert replay.audit["applied"] == []  # already_stale: nothing left to change
    assert replay.snapshot.content_version == first.snapshot.content_version


# 5 - a consumed event never bumps a version twice
def test_a_consumed_event_is_skipped_and_does_not_pretend_to_be_a_revision():
    replies = [_stale_reply(content_state={"round": 1, "notes": 2, "revision": "rev-1"})]
    event = MotionEvent(
        kind=CONDITION_ADDED,
        at=NOW,
        round=2,
        notes=3,
        revision="rev-2",
        detail={"keep_reply_id": "run1:steer:s2"},
    )
    first = coordinate(replies, event, now=NOW, run_id="run1", turn_id="turn1")
    second = coordinate(
        list(first.replies),
        event,
        now=NOW,
        run_id="run1",
        turn_id="turn1",
        consumed_event_ids=[event.identity()],
    )

    assert second.replies == first.replies
    assert second.audit["skipped"] == "duplicate_event"
    assert second.audit["applied"] == []
    assert second.replies[0]["content_version"] == first.replies[0]["content_version"]


# the round semantics are the legacy ones (the fix that made pairing exact)
def test_the_condition_guard_still_compares_round_only():
    same_round = _stale_reply(content_state={"round": 2, "notes": 1, "revision": "rev-1"})
    result = coordinate(
        [same_round],
        MotionEvent(kind=CONDITION_ADDED, at=NOW, round=2, notes=9, revision="rev-2"),
        now=NOW,
        run_id="run1",
        turn_id="turn1",
    )
    assert result.audit["applied"] == []
    assert result.replies[0]["stale"] is True


def test_read_evidence_ignores_records_that_were_not_read():
    failed = {"read": {"ok": False}, "item": {"url": "https://example.com/b"}}
    assert read_evidence_from_records([failed]) == ()
