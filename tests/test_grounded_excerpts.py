"""§40d grounded input: bounded excerpts and segment-overflow diagnostics."""

from __future__ import annotations

import pytest

from src.application.answer_claim_binder import (
    _segment_answer,
    segment_answer_with_stats,
)
from src.web.research.grounded_excerpts import (
    ANSWER_SHAPE_CONTRACT,
    GROUNDED_INPUT_ENV,
    grounded_excerpt,
    grounded_input_enabled,
)

CONTENT = (
    "前言。" * 120
    + "Node.js has two module systems: CommonJS modules and ECMAScript modules."
    + "后续内容。" * 120
)


def test_flag_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GROUNDED_INPUT_ENV, raising=False)
    assert grounded_input_enabled() is False
    monkeypatch.setenv(GROUNDED_INPUT_ENV, "on")
    assert grounded_input_enabled() is True


def test_excerpt_prefers_anchor_surroundings_and_is_bounded() -> None:
    excerpt = grounded_excerpt(CONTENT, anchor="CommonJS modules and ECMAScript modules")
    assert "CommonJS modules and ECMAScript modules" in excerpt
    assert excerpt.startswith("…")
    assert excerpt.endswith("…")
    assert len(excerpt) <= 402


def test_excerpt_falls_back_to_page_head() -> None:
    excerpt = grounded_excerpt("短内容开头的正文。", anchor="不存在的锚点")
    assert excerpt.startswith("短内容开头的正文")
    assert len(excerpt) <= 402


def test_empty_content_yields_no_excerpt() -> None:
    assert grounded_excerpt("", anchor="x") == ""
    assert grounded_excerpt("   ") == ""


def test_shape_contract_is_bounded_and_explicit() -> None:
    assert "最多 12" in ANSWER_SHAPE_CONTRACT
    assert "16" not in ANSWER_SHAPE_CONTRACT


def _sentence(index: int) -> str:
    return f"结论{index}：这是一条足够长的中文句子，用来占用分段预算。"


def test_segment_stats_report_overflow_instead_of_zero() -> None:
    answer = "".join(_sentence(index) for index in range(20))
    segments, stats = segment_answer_with_stats(answer)
    assert segments == ()
    assert stats["raw_nonempty_segment_count"] == 20
    assert stats["segment_limit"] == 16
    assert stats["segment_overflow"] is True
    assert stats["overflow_reason"] == "segment_count"
    assert stats["accepted"] is False


def test_segment_stats_report_accepted_segments() -> None:
    answer = "".join(_sentence(index) for index in range(12))
    segments, stats = segment_answer_with_stats(answer)
    assert len(segments) == 12
    assert _segment_answer(answer) == segments
    assert stats["raw_nonempty_segment_count"] == 12
    assert stats["segment_overflow"] is False
    assert stats["accepted"] is True


def test_segment_chars_overflow_is_reported() -> None:
    answer = "甲" * 1300 + "。"
    segments, stats = segment_answer_with_stats(answer)
    assert segments == ()
    assert stats["segment_overflow"] is True
    assert stats["overflow_reason"] == "segment_chars"
