"""AR-1C-2-E3: a conflict is a model's judgement that the shell can verify.

The controls are mostly refusals, because that is the contract: the shell must
not manufacture a conflict out of two numbers, must not accept a paraphrase as a
quote, and must not retract anything on a claim it could not check. Only the last
two tests let a conflict do work, and even then it withdraws rather than invents.
"""

import hashlib

import pytest

from src.web.research.answer_revision import RETRACT
from src.web.research.answer_state import snapshot_from_replies
from src.web.research.conflict_producer import (
    CONFLICT_UNEXPLAINED,
    QUOTES_IDENTICAL,
    READ_NOT_NEWER,
    SAME_SOURCE,
    TARGET_MISSING,
    TARGET_NOT_CURRENT,
    OLD_QUOTE_NOT_IN_REPLY,
    OLD_SOURCE_NOT_CITED,
    ConflictClaim,
    build_conflict_event,
)
from src.web.research.motion_events import (
    apply_event,
    proposals_for_event,
)
from src.web.research.read_evidence import ReadEvidence

NOW = "2026-10-21T00:00:00+00:00"
OLD_URL = "https://gimp.org/"
NEW_URL = "https://gimp.org/release-notes"
OLD_TEXT = "GIMP 3.0 的批量导出仍然需要命令行脚本。"
NEW_TEXT = "GIMP 3.0 的批量导出已在图形界面中提供，不再需要命令行脚本。"


def _replies(*, target_lifecycle: str = "current", target_round: int = 2):
    return [
        {
            "schema": "steering-reply-v1",
            "reply_id": "run1:research",
            "scope": "research",
            "steering_id": "",
            "turn_id": "turn1",
            "lifecycle": target_lifecycle,
            "stage": "evidence_update",
            "content_version": 3,
            "stale": False,
            "analysis_state": "ready",
            "text": OLD_TEXT,
            "citations": [{"url": OLD_URL, "quote": "命令行脚本"}],
            "content_state": {"round": target_round, "notes": 4, "revision": "rev-1"},
            "updated_at": NOW,
        },
        {
            "schema": "steering-reply-v1",
            "reply_id": "run1:steer:s1",
            "scope": "steering",
            "steering_id": "s1",
            "turn_id": "turn1",
            "lifecycle": "current",
            "stage": "evidence_update",
            "content_version": 1,
            "stale": False,
            "analysis_state": "ready",
            "text": "补充：只讨论桌面版。",
            "citations": [],
            "content_state": {"round": 2, "notes": 1, "revision": "rev-1"},
            "updated_at": NOW,
        },
    ]


def _read(*, url: str = NEW_URL, excerpt: str = NEW_TEXT, round_index: int = 3, read_id: str = "read-7"):
    return ReadEvidence.build(
        url=url, excerpt=excerpt, round_index=round_index, read_id=read_id
    )


def _binding(*, url: str = NEW_URL, quote: str = "不再需要命令行脚本", read_id: str = "read-7"):
    return {
        "url": url,
        "quote": quote,
        "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        "read_id": read_id,
    }


def _claim(**overrides) -> ConflictClaim:
    values = {
        "target_reply_id": "run1:research",
        "claim": "新发布说明称图形界面已提供批量导出，与当前答案相矛盾。",
        "old_quote": "批量导出仍然需要命令行脚本",
        "new_quote": "不再需要命令行脚本",
        "new_binding": _binding(),
        "old_source_url": OLD_URL,
        "condition": "仅桌面版",
    }
    values.update(overrides)
    return ConflictClaim(**values)


def _build(claim: ConflictClaim, *, replies=None, evidence=None, round_index: int = 3):
    return build_conflict_event(
        claim,
        replies=_replies() if replies is None else replies,
        evidence=(_read(),) if evidence is None else evidence,
        run_id="run1",
        at=NOW,
        round_index=round_index,
        notes=5,
        revision="rev-2",
    )


# -- the shortcut the shell must refuse --------------------------------------
def test_two_pages_with_different_numbers_are_not_a_conflict():
    """No claim, no event - even when both sides are genuinely quoted."""

    event, refusal = _build(_claim(claim=""))

    assert event is None
    assert refusal == CONFLICT_UNEXPLAINED


def test_a_quote_the_page_does_not_contain_is_not_evidence():
    event, refusal = _build(_claim(), evidence=(_read(excerpt="页面只介绍了安装步骤。"),))

    assert event is None
    assert refusal == "quote_not_in_read"


def test_a_page_that_was_never_read_cannot_contradict_anything():
    event, refusal = _build(_claim(), evidence=())

    assert event is None
    assert refusal == "source_not_read"


def test_a_paraphrase_of_the_old_answer_is_refused():
    """The old side must be the answer's own text, not the model's summary."""

    event, refusal = _build(_claim(old_quote="以前说必须用脚本"))

    assert event is None
    assert refusal == OLD_QUOTE_NOT_IN_REPLY


def test_an_answer_cannot_contradict_itself_from_the_same_page():
    event, refusal = _build(
        _claim(old_source_url=NEW_URL),
        evidence=(_read(),),
        replies=_replies_with_citation(NEW_URL),
    )

    assert event is None
    assert refusal == SAME_SOURCE


def test_the_old_side_must_be_a_source_the_answer_cites():
    event, refusal = _build(_claim(old_source_url="https://elsewhere.example/a"))

    assert event is None
    assert refusal == OLD_SOURCE_NOT_CITED


def test_identical_quotes_are_not_a_disagreement():
    """The same sentence on both sides is not a contradiction, whatever the model says."""

    event, refusal = _build(
        _claim(old_quote=NEW_TEXT, new_quote=NEW_TEXT, new_binding=_binding(quote=NEW_TEXT)),
        evidence=(_read(),),
        replies=_replies_with_text(NEW_TEXT),
    )

    assert event is None
    assert refusal == QUOTES_IDENTICAL


def test_an_older_read_cannot_overturn_a_newer_conclusion():
    event, refusal = _build(_claim(), replies=_replies(target_round=5))

    assert event is None
    assert refusal == READ_NOT_NEWER


def test_a_retracted_answer_is_not_a_target():
    event, refusal = _build(_claim(), replies=_replies(target_lifecycle="retracted"))

    assert event is None
    assert refusal == TARGET_NOT_CURRENT


def test_a_conflict_must_name_the_statement_it_contests():
    event, refusal = _build(_claim(target_reply_id=""))

    assert event is None
    assert refusal == TARGET_MISSING


# -- the one case that earns a withdrawal ------------------------------------
def test_a_verified_claim_names_both_sides_and_retracts_only_its_target():
    event, refusal = _build(_claim())

    assert refusal == ""
    assert event is not None
    detail = event.detail
    assert detail["verified"] is True
    assert detail["target_reply_id"] == "run1:research"
    assert detail["conflicting_urls"] == [OLD_URL, NEW_URL]
    assert detail["condition"] == "仅桌面版"
    assert detail["source_bindings"][0]["read_id"] == "read-7"

    snapshot = snapshot_from_replies(_replies(), run_id="run1", turn_id="turn1")
    proposals = proposals_for_event(event, snapshot)

    assert [item.target_reply_id for item in proposals] == ["run1:research"]
    assert proposals[0].action == RETRACT
    assert proposals[0].replacement == ""  # a conflict withdraws, never rewrites


def test_the_conflict_withdraws_the_statement_and_leaves_the_other_alone():
    event, _ = _build(_claim())
    replies, decisions, _ = apply_event(
        _replies(), event, now=NOW, run_id="run1", turn_id="turn1"
    )

    assert [item.proposal.target_reply_id for item in decisions] == ["run1:research"]
    assert decisions[0].applied == RETRACT
    assert replies[0]["lifecycle"] == "retracted"
    assert replies[1]["lifecycle"] == "current"
    assert replies[1]["text"] == "补充：只讨论桌面版。"


def test_the_same_claim_twice_is_one_event_identity():
    first, _ = _build(_claim())
    second, _ = _build(_claim())

    assert first is not None and second is not None
    assert first.identity() == second.identity()


def _replies_with_citation(url: str):
    replies = _replies()
    replies[0]["citations"] = [{"url": url, "quote": "命令行脚本"}]
    return replies


def _replies_with_text(text: str):
    replies = _replies()
    replies[0]["text"] = text
    return replies


@pytest.mark.parametrize("refusal_expected", [SAME_SOURCE])
def test_refusal_codes_stay_greppable(refusal_expected: str):
    """A refusal is a named fact, not a bool - callers log it verbatim."""

    assert refusal_expected.startswith("same_")
