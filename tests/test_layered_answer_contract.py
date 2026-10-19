"""Layered answer contract: each statement is published at its own strength.

The defect these control: when retrieval was incomplete, the whole answer was
replaced by an abstention. The risk that replaces it: relabelling an unverified
specific fact as "general knowledge" to get past the gate. Both are tested here.
"""

import json

import pytest

from src.web.research.answer_layers import (
    KNOWLEDGE,
    UNVERIFIED,
    claims_need_evidence,
    classify_draft,
    strict_publication_requested,
)
from src.web.research.official_publication import ABSTENTION, publish_official_fields

DRAFT = (
    "Photoshop、GIMP 和 Krita 都能进行分层编辑，也都能导出带透明通道的 PNG。"
    "如果主要做游戏素材合成与 PSD 协作，Photoshop 通常更合适；Krita 更偏向手绘与笔刷。"
)
SPECIFIC = "Photoshop 2026 最新版本比 GIMP 快 35%，官方已经确认。"


def _failed_call(reason: str = "http_403") -> dict:
    return {
        "name": "web_read",
        "arguments": {"url": "https://example.com/page"},
        "result": {"status": "failed", "error": reason},
    }


# -- N1: partial failure still answers ---------------------------------------
def test_a_partial_read_failure_still_publishes_the_general_part():
    text, audit = publish_official_fields(
        "对比 Photoshop 与 GIMP", [_failed_call("http_403")], DRAFT
    )

    assert audit["status"] == "layered_without_evidence"
    assert audit["model_prose_published"] is True
    assert "未使用本次检索结果核实" in text
    assert "本次未能核实" in text
    assert "未能成功读取" in text
    assert text != ABSTENTION


# -- N2: nothing safe to say still abstains ----------------------------------
def test_a_draft_of_only_specific_claims_abstains():
    text, audit = publish_official_fields("对比版本速度", [_failed_call()], SPECIFIC)

    assert audit["status"] == "abstained"
    assert text == ABSTENTION
    assert audit["layered"]["withheld"][0]["reason"] == "specific_number"


# -- N3: strict mode keeps the old semantics ---------------------------------
def test_strict_mode_keeps_the_abstention():
    text, audit = publish_official_fields(
        "对比 Photoshop 与 GIMP", [], DRAFT, strict=True
    )

    assert audit["status"] == "abstained"
    assert text == ABSTENTION
    assert audit["layered"] is None


def test_strict_mode_is_recognised_from_the_request():
    assert strict_publication_requested("只要已证实的信息，不要推测")
    assert strict_publication_requested("必须有官方来源")
    assert not strict_publication_requested("讲讲这个软件的功能，最好参考最新版本")


# -- N4: an unread screenshot is never described -----------------------------
def test_an_unread_screenshot_is_never_claimed():
    draft = "图中显示的角色面板共有四个标签页。这类面板一般用于切换角色。"
    text, audit = publish_official_fields(
        "分析这张截图", [], draft, attachment_present=True, screenshot_read=False
    )

    published = " ".join(segment["text"] for segment in audit["layered"]["segments"])
    withheld = [segment for segment in audit["layered"]["withheld"]]
    assert "图中" not in published and "截图显示" not in published
    assert any(segment["reason"] == "attachment_not_read" for segment in withheld)
    assert "尚未读到图中信息" in text


# -- N6 / control A: specific facts are withheld, not relabelled -------------
@pytest.mark.parametrize(
    "sentence",
    [
        SPECIFIC,
        "官方售价为 888 元。",
        "该版本发布于 2026 年 3 月。",
        "新版本的反应速度比旧版快 1.5 倍。",
        "截图中的数值是 12.5。",
    ],
)
def test_a_specific_claim_can_never_become_knowledge(sentence):
    assert claims_need_evidence(sentence) != ""

    published, withheld = classify_draft(sentence)
    assert published == []
    assert withheld[0].kind == UNVERIFIED


def test_an_explicit_gap_statement_is_not_treated_as_a_claim():
    assert claims_need_evidence("最新版本的兼容性尚未核实。") == ""
    published, withheld = classify_draft("最新版本的兼容性尚未核实。")
    assert published and not withheld


def test_general_statements_stay_knowledge():
    published, withheld = classify_draft(DRAFT)
    assert not withheld
    assert all(segment.kind in {KNOWLEDGE, "conditional"} for segment in published)


# -- audit contract ----------------------------------------------------------
def test_the_layered_audit_round_trips_through_json():
    _, audit = publish_official_fields("对比 Photoshop 与 GIMP", [], DRAFT + SPECIFIC)
    restored = json.loads(json.dumps(audit, ensure_ascii=False))

    assert restored == audit
    assert restored["status"] == "layered_without_evidence"
    assert restored["layered"]["schema_version"] == "layered-answer-v1"
    assert [item["decision"] for item in restored["layered"]["segments"]] == ["published"] * len(
        restored["layered"]["segments"]
    )
    assert restored["layered"]["withheld"][0]["decision"] == "withheld"


def test_the_knowledge_layer_is_capped_and_labelled():
    long_draft = "这是稳定的通用说明。" * 200
    text, audit = publish_official_fields("一般问题", [], long_draft)

    assert "未使用本次检索结果核实" in text
    assert len(text) < len(long_draft)

# -- the opening: knowledge-stage reply --------------------------------------
def _opening_reply(**overrides):
    from src.web.research.steering_replies import (
        apply_knowledge,
        find_reply,
        research_reply_id,
    )

    replies: list[dict] = []
    replies = apply_knowledge(
        replies,
        run_id="run1",
        turn_id="turn1",
        text="这类选择通常取决于导出流程：批处理能力、脚本支持和协作方式。",
        now="2026-10-19T00:00:01+00:00",
    )
    return replies, find_reply(replies, research_reply_id("run1"))


def test_the_opening_is_published_as_knowledge():
    from src.web.research.steering_replies import STAGE_KNOWLEDGE

    _, reply = _opening_reply()

    assert reply["stage"] == STAGE_KNOWLEDGE
    assert reply["scope"] == "research"
    assert reply["lifecycle"] == "open"
    assert reply["content_version"] == 1


def test_a_sourced_judgment_is_never_replaced_by_the_opening():
    from src.web.research.steering_replies import (
        apply_evidence,
        apply_knowledge,
        find_reply,
        research_reply_id,
    )

    replies, reply = _opening_reply()
    replies = apply_evidence(
        replies,
        reply_id=reply["reply_id"],
        analysis={"text": "已读材料支持：GIMP 走自动化路线。", "citations": [{"url": "https://gimp.org", "quote": "q"}]},
        now="2026-10-19T00:00:02+00:00",
        version=2,
        based_on=1,
        state={"round": 1, "notes": 2, "revision": ""},
    )
    replies = apply_knowledge(
        replies,
        run_id="run1",
        turn_id="turn1",
        text="另一段通用说明。",
        now="2026-10-19T00:00:03+00:00",
    )
    current = find_reply(replies, research_reply_id("run1"))
    assert current["stage"] == "evidence_update"
    assert current["text"] == "已读材料支持：GIMP 走自动化路线。"


def test_a_later_supplement_marks_the_opening_as_not_covering_it():
    from src.web.research.steering_replies import mark_additions_stale

    replies, reply = _opening_reply()
    replies = mark_additions_stale(
        replies, keep_reply_id="run1:steer:s2", added_round=2, now="2026-10-19T00:00:04+00:00"
    )
    current = next(item for item in replies if item["reply_id"] == reply["reply_id"])
    assert current["stale"] is True
    assert current["content_version"] == reply["content_version"] + 1


# -- the planner opening is validated ---------------------------------------
def test_the_planner_accepts_a_general_opening_and_rejects_a_specific_one():
    from src.web.research.deep_planner import _validated_opening

    assert _validated_opening("这是稳定的通用说明：取决于任务类型与现有运行时。")
    assert _validated_opening("最新版本比上个版本快 35%，官方已经确认。") == ""
    assert _validated_opening("x" * 400) == ""
    assert _validated_opening(None) == ""


# -- end to end: the persisted answer is substantive ------------------------
def test_the_persisted_assistant_message_is_a_layered_answer(tmp_path):
    """The reader sees real content, not only the research summary in the UI."""

    from dataclasses import replace

    from src.application.chat_service import ChatCommand, ChatService
    from src.tools.web_agent import WebToolTrace
    from tests.test_chat_service import _service

    service, repository = _service(tmp_path)
    trace = WebToolTrace(
        calls=(
            {
                "name": "web_read",
                "arguments": {"url": "https://example.com/ps"},
                "result": {"status": "failed", "error": "http_403"},
            },
        )
    )
    draft = (
        "这类问题主要看导出流程：批处理能力、格式支持与协作方式决定差异。"
        "Photoshop 2026 最新版本比 GIMP 快 35%，官方已经确认。"
    )
    service = ChatService(
        service.repository,
        replace(
            service.dependencies,
            resolve_web_tools=lambda *args, **kwargs: trace,
            route_request=lambda **kwargs: {
                "role": "nahida",
                "mode": "研究",
                "model_profile": "flash",
                "reason": "test",
                "task_contract": {"task_intent": "research"},
            },
            chat=lambda *args, **kwargs: draft,
        ),
    )

    prepared = service.start_turn(ChatCommand(user_input="Photoshop 和 GIMP 哪个更适合游戏素材？"))
    # complete_turn is the publication seam the route uses to persist the answer.
    service.complete_turn(prepared, draft)
    stored = repository.get_chat_turn(prepared.turn.id).assistant_message

    assert "未使用本次检索结果核实" in stored
    assert "35%" not in stored
    assert "本次未能核实" in stored
    assert "暂不能给出已核实的结论" not in stored
