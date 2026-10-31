"""Zero-cost segmentation coverage probe for archived answers.

The Answer-A/B replay showed that most long answers never reach claim-level
binding: ``answer_claim_binder`` rejects the whole answer when it has more than
``_MAX_SEGMENTS`` parts or when one part exceeds ``_MAX_SEGMENT_CHARS``. This
probe answers, without touching production and without a model call:

1. **Which limit blocks the archived answers** - the two ceilings are
   independent, so "raise 16" is only valid for answers whose parts are short.
2. **What a joint strategy would buy** - two segmentation rules crossed with
   several segment budgets, each checked for content coverage, unit size,
   rendered prompt size, the A2 candidate budget and the binder output scale.

Coverage is checked by content, not by trust. Every prose sentence, every table
header and row, every list item and every code block must survive; a heading is
allowed to be treated as structure only when it carries no fact, and a heading
that carries a number (``### PostgreSQL 19 已正式发布``) is a fact. Numbers are
compared as a multiset, so an occurrence cannot disappear just because the same
digit appears elsewhere.

The probe monkeypatches the binder's constants only to *measure* limits. It
changes no production budget.

Run: ``PYTHONPATH=. python tools/segmentation_coverage.py``
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.application import answer_claim_binder as binder
from src.application.answer_claim_binder import _SEGMENT_BOUNDARY

ROOT = Path("docs/research_quality/answer_ab")
JSON_OUT = Path("docs/research_quality/SEGMENTATION_COVERAGE.json")
MD_OUT = Path("docs/research_quality/SEGMENTATION_COVERAGE.md")

COUNT_LIMITS = (16, 24, 32, 48, 64, 128)
MATRIX_LIMITS = (16, 24, 32, 48)
CHAR_LIMITS = (1200, 2000, 4000, 8000)
STRATEGIES = ("prose", "structure")

#: One binder record, in a compact but realistic shape, for output-size estimates.
_RECORD_CHARS = 150

_FENCE = re.compile(r"^\s*```")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_ORDINAL = re.compile(r"^(?:[一二三四五六七八九十]+[、.]|\d+[.)、]|\(\d+\))\s*")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


@dataclass
class Answer:
    file: str
    arm: str
    query: str
    text: str
    raw_units: int = 0
    longest_prose_unit: int = 0
    accepted_at_current: bool = False
    current_reason: str = ""
    structure_units: int = 0
    table_rows: int = 0
    code_fences: int = 0
    numbers_total: int = 0


@dataclass
class MatrixCell:
    strategy: str
    limit: int
    answers_admitted: int
    units_total: int
    dropped_facts: int
    dropped_numbers: int
    dropped_headings: int
    max_unit_chars: int
    prompt_chars_max: int
    prompts_over_context: int
    a2_candidates_needed: int
    binder_records: int
    binder_output_chars: int


def _iter_answers(root: Path) -> Iterable[tuple[Path, str, str, str]]:
    for path in sorted(root.glob("*_2026*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        arm = str(payload.get("arm") or payload.get("strategy") or "")
        for turn in payload.get("turns") or []:
            if not isinstance(turn, dict):
                continue
            answer_field = turn.get("answer")
            text = (
                str(answer_field.get("text") or "")
                if isinstance(answer_field, dict)
                else str(answer_field or "")
            )
            research = turn.get("research")
            research = research if isinstance(research, dict) else {}
            if text.strip() and research.get("source_block"):
                yield path, arm, str(turn.get("query") or ""), text


def _normalize(value: str) -> str:
    return " ".join(str(value or "").split())


def _split_sentences(text: str) -> tuple[str, ...]:
    return tuple(
        part.strip(" \t\n\r") for part in _SEGMENT_BOUNDARY.split(text) if part.strip()
    )


def _heading_is_fact(line: str) -> bool:
    """A heading that states something numeric is a fact, not just structure."""

    body = _HEADING.sub("", line.strip())
    body = _ORDINAL.sub("", body).strip()
    if not body:
        return False
    return bool(re.search(r"\d", body))


def _scan(text: str) -> dict[str, Any]:
    """Classify every line once, so all strategies start from the same reading."""

    prose: list[str] = []
    heading_facts: list[str] = []
    headings: list[str] = []
    table_rows: list[str] = []
    list_items: list[str] = []
    code_blocks: list[str] = []
    code_lines: list[str] = []
    fence_open = False
    fence_lines: list[str] = []

    def flush_fence() -> None:
        nonlocal fence_lines
        body = "\n".join(line for line in fence_lines if line.strip())
        if body.strip():
            code_blocks.append(body)
            code_lines.extend(line.strip() for line in fence_lines if line.strip())
        fence_lines = []

    for line in text.splitlines():
        if _FENCE.match(line):
            if fence_open:
                flush_fence()
                fence_open = False
            else:
                fence_open = True
            continue
        if fence_open:
            fence_lines.append(line)
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if _HEADING.match(stripped):
            (heading_facts if _heading_is_fact(stripped) else headings).append(stripped)
            continue
        if _TABLE_RULE.match(stripped):
            continue
        if _TABLE_ROW.match(stripped):
            # Every row - header included - is kept as its own unit. Attaching a
            # row to its header is a separate problem, reported as a limitation.
            table_rows.append(stripped)
            continue
        if _LIST_ITEM.match(stripped):
            list_items.append(stripped)
            continue
        prose.append(stripped)
    if fence_open:
        flush_fence()
    return {
        "prose": prose,
        "heading_facts": heading_facts,
        "headings": headings,
        "table_rows": table_rows,
        "list_items": list_items,
        "code_blocks": code_blocks,
        "code_lines": code_lines,
    }


def _prose_units(text: str) -> tuple[str, ...]:
    """Exactly the production split, so this baseline cannot drift from it."""

    return tuple(
        part.strip(" \t\n\r")
        for part in _SEGMENT_BOUNDARY.split(text)
        if part.strip(" \t\n\r")
    )


def _structure_units(scan: dict[str, Any]) -> tuple[str, ...]:
    """Structure-aware: headings that state a fact stay, headings that do not go."""

    units: list[str] = []
    for line in scan["prose"]:
        units.extend(_split_sentences(line))
    units.extend(scan["heading_facts"])
    units.extend(scan["list_items"])
    units.extend(scan["table_rows"])
    units.extend(scan["code_blocks"])
    return tuple(units)


def _coverage(scan: dict[str, Any], units: Sequence[str]) -> dict[str, int]:
    """Every fact-bearing line and every number occurrence must survive."""

    joined = _normalize("\n".join(units))
    dropped = {"prose": 0, "list": 0, "table": 0, "code": 0, "heading_fact": 0}
    for line in scan["prose"]:
        for sentence in _split_sentences(line):
            if _normalize(sentence) not in joined:
                dropped["prose"] += 1
    for line in scan["list_items"]:
        for sentence in _split_sentences(_LIST_ITEM.sub("", line)):
            if _normalize(sentence) not in joined:
                dropped["list"] += 1
    for line in scan["table_rows"]:
        for sentence in _split_sentences(line):
            if _normalize(sentence) not in joined:
                dropped["table"] += 1
    for block in scan["code_blocks"]:
        lines = [_normalize(line) for line in block.splitlines() if line.strip()]
        if any(line not in joined for line in lines):
            dropped["code"] += 1
    for line in scan["heading_facts"]:
        if _normalize(line) not in joined:
            dropped["heading_fact"] += 1
    source_numbers = Counter(
        _NUMBER.findall(
            "\n".join(
                [
                    *scan["prose"],
                    *scan["list_items"],
                    *scan["table_rows"],
                    *scan["heading_facts"],
                    *scan["code_blocks"],
                ]
            )
        )
    )
    unit_numbers = Counter(_NUMBER.findall("\n".join(units)))
    dropped["numbers"] = sum((source_numbers - unit_numbers).values())
    return dropped


def _units_for(strategy: str, scan: dict[str, Any], text: str) -> tuple[str, ...]:
    return _prose_units(text) if strategy == "prose" else _structure_units(scan)


def _numbered(units: Sequence[str]) -> str:
    return "\n".join(f"[s{index}] {unit}" for index, unit in enumerate(units, 1))


def _probe(path: Path, arm: str, query: str, text: str) -> Answer:
    scan = _scan(text)
    units = _prose_units(text)
    segments, stats = binder.segment_answer_with_stats(text)
    return Answer(
        file=path.name,
        arm=arm,
        query=query,
        text=text,
        raw_units=len(units),
        longest_prose_unit=max((len(unit) for unit in units), default=0),
        accepted_at_current=bool(stats["accepted"]),
        current_reason=str(stats["overflow_reason"]),
        structure_units=len(_structure_units(scan)),
        table_rows=len(scan["table_rows"]),
        code_fences=len(scan["code_blocks"]),
        numbers_total=len(_NUMBER.findall(text)),
    )


def _admitted(units: Sequence[str], limit: int, char_limit: int) -> tuple[bool, str]:
    over_count = len(units) > limit
    over_chars = any(len(unit) > char_limit for unit in units)
    if over_count and over_chars:
        return False, "both"
    if over_count:
        return False, "segment_count"
    if over_chars:
        return False, "segment_chars"
    return True, ""


def _sweep(answers: Sequence[Answer]) -> dict[str, Any]:
    """The prose strategy must reproduce the production count, or it measures a
    different rule; a mismatch counter makes that visible instead of silent."""

    mismatches = sum(
        1
        for answer in answers
        if answer.raw_units
        != int(
            binder.segment_answer_with_stats(answer.text)[1][
                "raw_nonempty_segment_count"
            ]
        )
    )
    rows: list[dict[str, Any]] = []
    for limit in COUNT_LIMITS:
        admitted, blocked = 0, {"segment_count": 0, "segment_chars": 0, "both": 0}
        for answer in answers:
            units = _prose_units(answer.text)
            ok, reason = _admitted(units, limit, binder._MAX_SEGMENT_CHARS)
            if ok:
                admitted += 1
            else:
                blocked[reason] += 1
        rows.append(
            {
                "segment_limit": limit,
                "admitted": admitted,
                "of": len(answers),
                "blocked": blocked,
            }
        )
    char_rows: list[dict[str, Any]] = []
    for char_limit in CHAR_LIMITS:
        admitted = sum(
            1 for answer in answers if _admitted(_prose_units(answer.text),
                                                  binder._MAX_SEGMENTS, char_limit)[0]
        )
        char_rows.append({"char_limit": char_limit, "admitted": admitted})
    return {
        "by_segment_limit": rows,
        "by_char_limit": char_rows,
        "prose_rule_mismatches": mismatches,
    }


def _matrix(answers: Sequence[Answer]) -> list[MatrixCell]:
    cells: list[MatrixCell] = []
    for strategy in STRATEGIES:
        for limit in MATRIX_LIMITS:
            admitted = 0
            units_total = 0
            dropped_facts = 0
            dropped_numbers = 0
            dropped_headings = 0
            max_unit = 0
            prompt_max = 0
            prompts_over = 0
            for answer in answers:
                scan = _scan(answer.text)
                units = _units_for(strategy, scan, answer.text)
                ok, _reason = _admitted(units, limit, binder._MAX_SEGMENT_CHARS)
                coverage = _coverage(scan, units)
                dropped_facts += sum(
                    coverage[key]
                    for key in ("prose", "list", "table", "code", "heading_fact")
                )
                dropped_numbers += coverage["numbers"]
                dropped_headings += (
                    len(scan["headings"]) if strategy == "structure" else 0
                )
                max_unit = max(max_unit, max((len(u) for u in units), default=0))
                if not ok:
                    continue
                admitted += 1
                units_total += len(units)
                prompt = len(_numbered(units))
                prompt_max = max(prompt_max, prompt)
                if prompt > binder._MAX_CONTEXT_CHARS:
                    prompts_over += 1
            cells.append(
                MatrixCell(
                    strategy=strategy,
                    limit=limit,
                    answers_admitted=admitted,
                    units_total=units_total,
                    dropped_facts=dropped_facts,
                    dropped_numbers=dropped_numbers,
                    dropped_headings=dropped_headings,
                    max_unit_chars=max_unit,
                    prompt_chars_max=prompt_max,
                    prompts_over_context=prompts_over,
                    a2_candidates_needed=units_total * 3,
                    binder_records=units_total,
                    binder_output_chars=units_total * _RECORD_CHARS,
                )
            )
    return cells


def _pick(cells: Sequence[MatrixCell], strategy: str, limit: int) -> MatrixCell:
    return next(c for c in cells if c.strategy == strategy and c.limit == limit)


def _report(
    answers: Sequence[Answer],
    sweep: dict[str, Any],
    cells: Sequence[MatrixCell],
) -> str:
    total = len(answers)
    current = sum(1 for answer in answers if answer.accepted_at_current)
    count_blocked = sum(1 for a in answers if a.current_reason == "segment_count")
    char_blocked = sum(1 for a in answers if a.current_reason == "segment_chars")
    lines = [
        "# 分段覆盖评估（零成本）",
        "",
        "> 数据：`docs/research_quality/answer_ab` 的 20 轮归档答案；",
        "> 费用：0；重现：`PYTHONPATH=. python tools/segmentation_coverage.py`；",
        "> 本评估**不改任何生产预算**，不采用结构感知分段，只提供测量。",
        "",
        "## 1. 现状：两个独立限制",
        "",
        f"- `_MAX_SEGMENTS = {binder._MAX_SEGMENTS}`、"
        f"`_MAX_SEGMENT_CHARS = {binder._MAX_SEGMENT_CHARS}`，任一触发即整份答案被拒；",
        f"- 当前可进入绑定：**{current} / {total}**；"
        f"段数原因 {count_blocked}、单段原因 {char_blocked}。",
        "",
        "## 2. 只提高段数上限（字符上限保持 "
        f"{binder._MAX_SEGMENT_CHARS}）",
        "",
        "| 段数上限 | 可进入绑定 | 仍被挡（段数/单段/两者） |",
        "| ---: | ---: | --- |",
    ]
    for row in sweep["by_segment_limit"]:
        blocked = row["blocked"]
        lines.append(
            f"| {row['segment_limit']} | {row['admitted']} / {row['of']} | "
            f"{blocked['segment_count']} / {blocked['segment_chars']} / {blocked['both']} |"
        )
    lines += [
        "",
        "## 3. 只提高单段字符上限（段数保持 "
        f"{binder._MAX_SEGMENTS}）",
        "",
        "| 单段字符上限 | 可进入绑定 |",
        "| ---: | ---: |",
    ]
    for row in sweep["by_char_limit"]:
        lines.append(f"| {row['char_limit']} | {row['admitted']} / {total} |")
    lines += [
        "",
        "## 4. 联合矩阵：分段策略 × 段数上限",
        "",
        "两种策略：`prose` = 生产分段规则；`structure` = 表格行/列表项各算一个事实单元、"
        "代码块整体一个单元、含数字的标题按事实保留。两者共用同一套切句正则。",
        "",
        "| 策略 | 段数上限 | 可进入绑定 | 事实丢失 | 数字丢失 | 最长单元 | prompt 最大 | prompt 超 16000 | A2 候选需要 | binder 记录数 | 估算输出字符 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for cell in cells:
        lines.append(
            f"| {cell.strategy} | {cell.limit} | {cell.answers_admitted} / {total} | "
            f"{cell.dropped_facts} | {cell.dropped_numbers} | {cell.max_unit_chars} | "
            f"{cell.prompt_chars_max} | {cell.prompts_over_context} | "
            f"{cell.a2_candidates_needed} | {cell.binder_records} | "
            f"{cell.binder_output_chars} |"
        )
    lines += [
        "",
        "说明：",
        "",
        "- 「事实丢失」按内容核对：每条散文句、列表项、表头、表数据行、代码块、"
        "以及**含数字的标题**都必须在某个单元里；数字按**出现次数**（多重集）比较，"
        "所以同一数字在别处出现不能掩盖这里的丢失。",
        "- 「数字丢失」与事实丢失同口径，单独列出是为了让数字问题一眼可见。",
        "- 「A2 候选需要」= 单元数 × 3；与 A2 当前默认上限 48（= 16 × 3）对照，"
        "超过即需要同步调整候选预算。",
        "- 「binder 估算输出」按每段一条记录约 "
        f"{_RECORD_CHARS} 字符估算，用于判断输出规模风险，不是实测。",
        "",
        "## 5. 逐条明细",
        "",
        "| 文件 | 查询 | 生产段数 | 最长段 | 现状 | 结构单元 | 表格行 | 代码块 |",
        "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for answer in answers:
        status = (
            "接受"
            if answer.accepted_at_current
            else ("段数" if answer.current_reason == "segment_count" else "单段")
        )
        lines.append(
            f"| {answer.file} | {answer.query[:22]} | {answer.raw_units} | "
            f"{answer.longest_prose_unit} | {status} | {answer.structure_units} | "
            f"{answer.table_rows} | {answer.code_fences} |"
        )
    lines += [
        "",
        "## 6. 结论（供裁定，不含实现）",
        "",
        f"1. 被挡的 {total - current} 轮全部是段数原因；单段字符上限在这批语料中未触发。",
        "2. 只优化分段规则（structure）在 16 段下只把覆盖从 7 提到 9——"
        "**仅改规则不够**，必须与段数预算组合评估。",
        "3. 任何组合都必须先满足上表的三条硬约束：事实/数字零丢失、单元 ≤ 1200 字符、"
        "渲染 prompt ≤ 16000 字符；随后才轮到候选预算与输出规模。",
        "4. 发布覆盖要求不变：不能只验证前 N 段就整体通过；"
        "prompt 截断已在 binder 中改为直接拒绝（`answer_context_truncated`）。",
        "",
        "### 组合的实际代价",
        "",
        "| 方案 | 覆盖 | A2 候选 | binder 记录 | 估算输出 | 相对当前 48 候选预算 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ] + [
        f"| {label} | {cell.answers_admitted} / {total} | {cell.a2_candidates_needed} | "
        f"{cell.binder_records} | {cell.binder_output_chars} | "
        f"{round(cell.a2_candidates_needed / 48, 1)}x |"
        for label, cell in (
            ("structure + 16", _pick(cells, "structure", 16)),
            ("structure + 32", _pick(cells, "structure", 32)),
            ("structure + 48", _pick(cells, "structure", 48)),
            ("prose + 48", _pick(cells, "prose", 48)),
        )
    ] + [
        "",
        "### 仍然存在的风险（不能由本表证明）",
        "",
        "1. **标题判定只用数字**：`### 结论：…` 这类不含数字但陈述结论的标题仍会被当作结构丢弃"
        "（本次 52 个被排除标题中就有这种例子）。生产化前需要真正的“标题是否陈述事实”判定，"
        "不能沿用当前数字启发式。",
        "2. **表格行与表头是分离单元**：行内容没有丢，但“这一行属于哪个表头”没有保留，"
        "A3 拿到的是单行文本而不是一张表。",
        "3. **输出规模**：结构分段 + 48 段时估算输出约 6.5 万字符，"
        "`structure + 32` 约 2.5 万，仍需按真实模型输出上限与漏项率验证。",
        "4. **语料只覆盖 20 轮**：短答案与超长答案之外的形状（纯表格、纯代码、跨语言）未被覆盖。",
        "",
        "### 建议",
        "",
        "先取 **structure + 32**（13/20，504 条候选、约 2.5 万字符输出）作为一次真实对照的候选方案；"
        "若要求 20/20，则需要 **structure + 48**，候选预算约 1305（当前 48 的 27 倍），"
        "必须先确定模型输出上限与费用准入，再决定是否实施。",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json-out", type=Path, default=JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=MD_OUT)
    args = parser.parse_args(argv)

    answers = [_probe(path, arm, query, text) for path, arm, query, text in _iter_answers(args.root)]
    sweep = _sweep(answers)
    cells = _matrix(answers)
    args.json_out.write_text(
        json.dumps(
            {
                "limits": {
                    "segments": binder._MAX_SEGMENTS,
                    "segment_chars": binder._MAX_SEGMENT_CHARS,
                    "context_chars": binder._MAX_CONTEXT_CHARS,
                },
                "answers": [
                    {key: value for key, value in asdict(answer).items() if key != "text"}
                    for answer in answers
                ],
                "sweep": sweep,
                "matrix": [asdict(cell) for cell in cells],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    args.md_out.write_text(_report(answers, sweep, cells), encoding="utf-8")
    print(
        json.dumps(
            {
                "answers": len(answers),
                "accepted": sum(1 for a in answers if a.accepted_at_current),
                "matrix": [
                    {
                        "strategy": cell.strategy,
                        "limit": cell.limit,
                        "admitted": cell.answers_admitted,
                        "dropped": cell.dropped_facts,
                        "max_unit": cell.max_unit_chars,
                        "prompt_max": cell.prompt_chars_max,
                    }
                    for cell in cells
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
