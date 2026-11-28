"""Degraded research delivery: label the loss, never erase the work."""

from __future__ import annotations

from src.application.research_delivery import (
    DRAFT_HEADING,
    NO_ANSWER_HEADING,
    PARTIAL_HEADING,
    compose_degraded_delivery,
    compose_generation_notice,
    reason_copy,
    withhold_blocks,
)


def test_reason_classes_keep_budget_quality_and_runtime_apart() -> None:
    assert reason_copy("budget_exhausted")[0] == "budget"
    assert reason_copy("consistency_failed:direction_violations")[0] == "quality"
    assert reason_copy("producer_failed:TimeoutError")[0] == "runtime"
    assert reason_copy("output_limit")[0] == "truncation"
    assert reason_copy("something_new")[0] == "runtime"


def test_withhold_blocks_drops_only_the_named_statement() -> None:
    text = (
        "## 结论\n\n"
        "该版本已正式发布。\n\n"
        "该版本支持 Windows 7。\n\n"
        "建议先备份。"
    )
    kept, removed = withhold_blocks(text, ["该版本支持 Windows 7。"])
    assert removed == 1
    assert "该版本已正式发布。" in kept
    assert "建议先备份。" in kept
    assert "Windows 7" not in kept


def test_withhold_blocks_does_not_guess_when_nothing_matches() -> None:
    kept, removed = withhold_blocks("一段没有任何匹配的正文。", ["不存在的句子。"])
    assert removed == 0
    assert kept == "一段没有任何匹配的正文。"


def test_a_draft_is_labelled_and_keeps_the_pages_actually_read() -> None:
    text, record = compose_degraded_delivery(
        "该版本已发布。",
        reason_code="producer_unavailable",
        sources=[
            {"title": "官方发布说明", "url": "https://official.example/release"},
            {"title": "重复来源", "url": "https://official.example/release"},
        ],
    )
    assert text.startswith(DRAFT_HEADING)
    assert "该版本已发布。" in text
    assert text.count("https://official.example/release") == 1
    assert record["outcome"] == "draft"
    assert record["verified"] is False
    assert record["reason_class"] == "runtime"
    assert record["source_count"] == 1
    assert len(record["sources"]) == 1


def test_a_verified_subset_uses_the_partial_label() -> None:
    text, _ = compose_degraded_delivery(
        "通过核验的一段。",
        reason_code="unbound_factual_claim",
        verified_subset=True,
    )
    assert text.startswith(PARTIAL_HEADING)
    assert "通过逐条核验的部分" in text


def test_no_candidate_still_delivers_the_read_sources() -> None:
    text, record = compose_degraded_delivery(
        "",
        reason_code="candidate_unavailable",
        sources=[{"title": "官方文档", "url": "https://docs.example/page"}],
    )
    assert text.startswith(NO_ANSWER_HEADING)
    assert "https://docs.example/page" in text
    assert "没有返回可用的回答正文" in text
    assert record["outcome"] == "no_answer"
    assert record["verified"] is False


def test_no_candidate_and_no_sources_still_states_the_failure() -> None:
    text, record = compose_degraded_delivery(
        "", reason_code="missing_evidence_brief"
    )
    assert text.startswith(NO_ANSWER_HEADING)
    assert "没有成功读取可引用的公开来源" in text
    assert record["outcome"] == "no_answer"


def test_output_limit_note_keeps_the_answer() -> None:
    text, record = compose_generation_notice("前半段正文", reason_code="output_limit")
    assert "前半段正文" in text
    assert "达到输出上限" in text
    assert record["outcome"] == "partial"
    assert record["reason_class"] == "truncation"
