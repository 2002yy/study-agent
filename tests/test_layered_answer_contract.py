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
