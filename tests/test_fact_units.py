"""Pre-check controls for the experiment-only fact unit builder.

These pass no model and touch no production path: they pin the four conditions
the segmentation review required before a paid comparison.
"""

from __future__ import annotations

from src.web.research.fact_units import (
    CANDIDATES_PER_UNIT,
    DEFAULT_MAX_UNITS,
    REASON_PROMPT_BUDGET,
    REASON_UNIT_BUDGET,
    build_fact_units,
)

ANSWER = (
    "### 结论：千冶·刃 在黄泉队走辅助型输出路线\n"
    "### 1. 遗器选择\n"
    "刃的强化普攻消耗生命值，几乎常驻触发 4 件套。\n"
    "\n"
    "| 版本 | 发布日期 |\n"
    "|---|---|\n"
    "| 19 | 2026-10-15 |\n"
    "\n"
    "```python\n"
    "engine = create_engine(url)\n"
    "session = Session(engine)\n"
    "```\n"
)


def test_a_conclusion_heading_without_digits_is_kept():
    result = build_fact_units(ANSWER)

    headings = [unit for unit in result.units if unit.kind == "heading"]
    texts = [unit.text for unit in headings]

    assert "结论：千冶·刃 在黄泉队走辅助型输出路线" in texts


def test_a_heading_with_content_survives_even_with_a_number_prefix():
    result = build_fact_units(ANSWER)

    kept = [unit.text for unit in result.units]

    assert "1. 遗器选择" in kept


def test_an_ordinal_only_heading_is_dropped_and_recorded():
    answer = "### 一、\n正文一段。\n### 1.\n"

    result = build_fact_units(answer)

    dropped = [unit.text for unit in result.dropped]
    kept = [unit.text for unit in result.units]

    assert dropped == ["一、", "1."]
    assert all(text not in kept for text in dropped)


def test_a_table_row_keeps_the_header_that_gives_it_meaning():
    result = build_fact_units(ANSWER)

    rows = [unit for unit in result.units if unit.kind == "table_row"]

    assert len(rows) == 1
    row = rows[0]
    assert "版本: 19" in row.text
    assert "发布日期: 2026-10-15" in row.text
    assert row.context == "版本 | 发布日期"
    assert "19" in ANSWER[row.start : row.end]
    assert "2026-10-15" in ANSWER[row.start : row.end]


def test_a_table_header_is_its_own_unit_so_nothing_is_lost():
    result = build_fact_units(ANSWER)

    headers = [unit for unit in result.units if unit.kind == "table_header"]

    assert len(headers) == 1
    assert headers[0].text == "| 版本 | 发布日期 |"


def test_a_code_block_is_one_unit_not_statement_lines():
    result = build_fact_units(ANSWER)

    code = [unit for unit in result.units if unit.kind == "code"]

    assert len(code) == 1
    assert "create_engine" in code[0].text
    assert "Session(engine)" in code[0].text


def test_prose_units_slice_back_to_their_source_text():
    result = build_fact_units(ANSWER)

    prose = [unit for unit in result.units if unit.kind == "prose"]

    assert prose
    for unit in prose:
        assert unit.text.strip() in ANSWER[unit.start : unit.end]
        assert unit.text == unit.text.strip()


def test_the_candidate_budget_follows_the_unit_limit():
    result = build_fact_units(ANSWER)

    assert result.max_units == DEFAULT_MAX_UNITS
    assert result.candidate_budget == DEFAULT_MAX_UNITS * CANDIDATES_PER_UNIT


def test_an_over_budget_answer_is_refused_instead_of_truncated():
    answer = "。".join(f"第{index}条事实" for index in range(30)) + "。"

    result = build_fact_units(answer, max_units=24)

    assert result.reason == REASON_UNIT_BUDGET
    assert result.units == ()
    assert result.counted_units > 24


def test_an_over_budget_prompt_is_refused_instead_of_truncated():
    # 24 sentences of ~700 characters stay inside the unit limit but their
    # rendered block exceeds the binder's context budget.
    sentence = "事实内容" + "甲" * 690 + "。"
    answer = "".join(sentence for _ in range(24))

    result = build_fact_units(answer, max_units=24)

    assert result.reason == REASON_PROMPT_BUDGET
    assert result.units == ()
    assert result.prompt_chars > 16000


def test_a_budget_of_zero_refuses_any_answer_with_units():
    result = build_fact_units(ANSWER, max_units=0)

    assert result.reason == REASON_UNIT_BUDGET
    assert result.units == ()
    assert result.candidate_budget == 0

def test_indented_prose_offsets_point_at_the_real_characters():
    answer = "    缩进写下的第一句事实。第二句事实。\n"

    result = build_fact_units(answer)

    prose = [unit for unit in result.units if unit.kind == "prose"]
    assert prose
    for unit in prose:
        assert answer[unit.start : unit.end] == unit.text


def test_two_tables_do_not_share_their_header():
    answer = (
        "| 版本 | 日期 |\n"
        "|---|---|\n"
        "| 19 | 2026-10-15 |\n"
        "\n"
        "| 名称 | 状态 |\n"
        "|---|---|\n"
        "| 纯文本 | 已发布 |\n"
    )

    result = build_fact_units(answer)

    rows = [unit for unit in result.units if unit.kind == "table_row"]
    assert len(rows) == 2
    assert "版本: 19" in rows[0].text
    assert "名称: 纯文本" in rows[1].text
    assert "状态: 已发布" in rows[1].text
    assert rows[1].context == "名称 | 状态"


def test_a_row_wider_than_its_header_does_not_crash():
    answer = (
        "| 版本 | 日期 |\n"
        "|---|---|\n"
        "| 19 | 2026-10-15 | 备注 |\n"
    )

    result = build_fact_units(answer)

    rows = [unit for unit in result.units if unit.kind == "table_row"]
    assert len(rows) == 1
    assert "备注" in rows[0].text

def test_a_digit_free_table_row_still_maps_back():
    from tools.structure24_precheck import _unit_maps_back

    answer = (
        "| 名称 | 状态 |\n"
        "|---|---|\n"
        "| 纯文本 | 已发布 |\n"
    )
    result = build_fact_units(answer)
    rows = [unit for unit in result.units if unit.kind == "table_row"]

    assert rows
    assert _unit_maps_back(answer, rows[0]) is True
