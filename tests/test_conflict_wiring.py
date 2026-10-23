"""AR-1C-3: the producer is reachable from the run, and only through checks.

The service method under test is the seam between "the planner says these two
texts disagree" and "a statement was withdrawn". It is deliberately callable on
its own: the deep loop is expensive to stage, and what matters is that the same
gate runs there as in the unit controls.
"""

import hashlib
from typing import Any

from src.application.web_lookup_service import WebLookupService

NOW = "2026-10-21T00:00:00+00:00"
OLD_URL = "https://gimp.org/"
NEW_URL = "https://gimp.org/release-notes"
OLD_TEXT = "GIMP 3.0 的批量导出仍然需要命令行脚本。"
NEW_EXCERPT = "GIMP 3.0 的批量导出已在图形界面中提供，不再需要命令行脚本。"
NEW_QUOTE = "不再需要命令行脚本"
READ_ID = "read-9"


def _reply(**overrides) -> dict[str, Any]:
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
        "text": OLD_TEXT,
        "citations": [{"url": OLD_URL, "quote": "命令行脚本"}],
        "content_state": {"round": 2, "notes": 4, "revision": "rev-1"},
        "updated_at": NOW,
    }
    base.update(overrides)
    return base


def _record(*, url: str = NEW_URL, excerpt: str = NEW_EXCERPT, read_id: str = READ_ID) -> dict[str, Any]:
    return {
        "item": {"title": "Release notes", "url": url},
        "assessment": {"url": url},
        "read": {
            "ok": True,
            "status": "read",
            "content": excerpt,
            "read_id": read_id,
            "round": 3,
        },
    }


def _binding() -> dict[str, Any]:
    return {
        "url": NEW_URL,
        "quote": NEW_QUOTE,
        "quote_sha256": hashlib.sha256(NEW_QUOTE.encode("utf-8")).hexdigest(),
        "read_id": READ_ID,
        "read_excerpt_sha256": hashlib.sha256(NEW_EXCERPT.encode("utf-8")).hexdigest(),
    }


def _claim(**overrides) -> dict[str, Any]:
    values = {
        "target_reply_id": "run1:research",
        "claim": "新发布说明称图形界面已提供批量导出，与当前答案相矛盾。",
        "old_quote": "批量导出仍然需要命令行脚本",
        "new_quote": NEW_QUOTE,
        "source_binding": _binding(),
        "old_source_url": OLD_URL,
        "condition": "仅桌面版",
    }
    values.update(overrides)
    return values


def _context(*, replies=None) -> dict[str, Any]:
    return {
        "steering_replies": [_reply()] if replies is None else replies,
        "run_round": 3,
        "interim_state": {"revision": "rev-2"},
        "owner": {"turn_id": "turn1"},
    }


def _apply(context, claims, records, *, deep=None, verdict=None):
    service = WebLookupService.__new__(WebLookupService)
    service._apply_motion_conflicts(
        context,
        deep if deep is not None else {"notes": [{"note": "x"}]},
        verdict if verdict is not None else {"conflict_claims": claims},
        "run1",
        records,
    )
    return context


# -- a backed claim does the one thing a conflict may do ----------------------
def test_a_verified_claim_withdraws_the_named_statement():
    context = _apply(_context(), [_claim()], [_record()])

    assert len(context["revision_events"]) == 1
    event = context["revision_events"][0]
    assert event["kind"] == "evidence_conflict"
    assert event["detail"]["verified"] is True
    assert event["detail"]["target_reply_id"] == "run1:research"

    reply = context["steering_replies"][0]
    assert reply["lifecycle"] == "retracted"
    assert context["motion_refusals"] == []
    # A conflict withdraws; it never writes a new conclusion.
    assert reply["text"] == OLD_TEXT or "已撤回" in reply["text"]


def test_the_withdrawal_advances_the_version_so_a_late_writer_cannot_revive_it():
    context = _apply(_context(), [_claim()], [_record()])

    assert context["steering_replies"][0]["content_version"] == 4
    assert context["steering_replies"][0]["last_revision"]["action"] == "retract"


# -- and everything else is refused without touching the answer ---------------
def test_a_paraphrased_old_side_is_refused_and_changes_nothing():
    context = _apply(_context(), [_claim(old_quote="以前说必须用脚本")], [_record()])

    assert "revision_events" not in context or context["revision_events"] == []
    assert context["steering_replies"][0]["lifecycle"] == "open"
    assert context["motion_refusals"] == [
        {"target": "run1:research", "refusal": "old_quote_not_in_reply"}
    ]


def test_a_conflict_against_a_page_that_was_not_read_is_refused():
    context = _apply(_context(), [_claim()], [])

    assert context["steering_replies"][0]["lifecycle"] == "open"
    assert context["motion_refusals"][0]["refusal"] == "source_not_read"


def test_a_claim_without_an_interpretation_is_refused():
    context = _apply(_context(), [_claim(claim="")], [_record()])

    assert context["steering_replies"][0]["lifecycle"] == "open"
    assert context["motion_refusals"][0]["refusal"] == "conflict_unexplained"


def test_a_run_without_a_planner_claim_does_no_work():
    context = _apply(_context(), [], [_record()])

    assert context["steering_replies"][0]["lifecycle"] == "open"
    assert context.get("revision_events") is None
    assert context.get("motion_refusals") is None


def test_only_the_backed_claim_acts_when_several_are_reported():
    context = _apply(
        _context(),
        [_claim(old_quote="以前说必须用脚本"), _claim()],
        [_record()],
    )

    assert context["steering_replies"][0]["lifecycle"] == "retracted"
    assert [item["refusal"] for item in context["motion_refusals"]] == [
        "old_quote_not_in_reply"
    ]
    assert len(context["revision_events"]) == 1


def test_the_refusal_trace_is_bounded():
    claims = [_claim(old_quote=f"伪造的旧句子{i}号") for i in range(30)]
    context = _apply(_context(), claims, [_record()])

    assert len(context["motion_refusals"]) == 20
