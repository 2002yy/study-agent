"""Zero-cost segmentation coverage probe for archived answers.

The Answer-A/B replay showed that most long answers never reach claim-level
binding: ``answer_claim_binder`` rejects the whole answer when it has more than
``_MAX_SEGMENTS`` parts or when one part exceeds ``_MAX_SEGMENT_CHARS``. This
probe answers two questions without touching production code and without a
model call:

1. **Which limit actually blocks the archived answers**, and what would raising
   the count limit recover? The two limits are independent, so "raise 16" is
   only a valid answer for answers whose parts are all short.
2. **Would structure-aware segmentation help more cheaply?** Markdown headings,
   table rows, list items and code fences are not sentences; splitting them as
   prose inflates the count. The probe measures how many segments each rule
   yields and, critically, whether any table fact or code assertion is dropped.

The probe monkeypatches the binder's module constants to sweep limits. It writes
a JSON artefact and a Markdown report; it changes no production budget.

Run: ``PYTHONPATH=. python tools/segmentation_coverage.py``
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.application.answer_claim_binder import _SEGMENT_BOUNDARY
from src.application import answer_claim_binder as binder

ROOT = Path("docs/research_quality/answer_ab")
JSON_OUT = Path("docs/research_quality/SEGMENTATION_COVERAGE.json")
MD_OUT = Path("docs/research_quality/SEGMENTATION_COVERAGE.md")

COUNT_LIMITS = (16, 24, 32, 48, 64, 128)
CHAR_LIMITS = (1200, 2000, 4000, 8000)
_FENCE = re.compile(r"^\s*```")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


@dataclass
class Answer:
    file: str
    arm: str
    query: str
    text: str
    raw_segments: int = 0
    longest_segment: int = 0
    max_segments_in_text: int = 0
    accepted_at_current: bool = False
    current_reason: str = ""
    structure_segments: int = 0
    structure_char_max: int = 0
    table_rows: int = 0
    code_fences: int = 0
    numbers_total: int = 0
    numbers_lost: int = 0
    numbers_in_headings: int = 0
    table_rows_lost: int = 0
    code_fences_lost: int = 0


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


def _split_sentences(text: str) -> tuple[str, ...]:
    return tuple(
        part.strip(" \t\n\r") for part in _SEGMENT_BOUNDARY.split(text) if part.strip()
    )


def _structure_segments(
    text: str,
) -> tuple[tuple[str, ...], dict[str, int], set[str]]:
    """Markdown-aware probe: headings are structure, table rows/code are facts."""

    segments: list[str] = []
    counts = {"table_rows": 0, "code_fences": 0, "headings": 0}
    heading_numbers: set[str] = set()
    fence_open = False
    fence_lines: list[str] = []

    def flush_fence() -> None:
        nonlocal fence_lines
        body = "\n".join(line for line in fence_lines if line.strip())
        if body.strip():
            segments.append(body)
            counts["code_fences"] += 1
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
            counts["headings"] += 1
            heading_numbers.update(_NUMBER.findall(stripped))
            continue
        if _TABLE_RULE.match(stripped):
            continue
        if _TABLE_ROW.match(stripped):
            segments.append(stripped)
            counts["table_rows"] += 1
            continue
        if _LIST_ITEM.match(stripped):
            segments.append(stripped)
            continue
        segments.extend(_split_sentences(stripped))
    if fence_open:
        flush_fence()
    return (
        tuple(segment for segment in segments if segment.strip()),
        counts,
        heading_numbers,
    )


def _probe(path: Path, arm: str, query: str, text: str) -> Answer:
    segments, stats = binder.segment_answer_with_stats(text)
    structure, counts, heading_numbers = _structure_segments(text)
    numbers = set(_NUMBER.findall(text))
    structure_text = "\n".join(structure)
    lost = numbers - set(_NUMBER.findall(structure_text))
    return Answer(
        file=path.name,
        arm=arm,
        query=query,
        text=text,
        raw_segments=int(stats["raw_nonempty_segment_count"]),
        longest_segment=max(
            (len(part) for part in _split_sentences(text)), default=0
        ),
        accepted_at_current=bool(stats["accepted"]),
        current_reason=str(stats["overflow_reason"]),
        structure_segments=len(structure),
        structure_char_max=max((len(part) for part in structure), default=0),
        table_rows=counts["table_rows"],
        code_fences=counts["code_fences"],
        numbers_total=len(numbers),
        numbers_lost=len(lost - heading_numbers),
        numbers_in_headings=len(lost & heading_numbers),
        table_rows_lost=max(0, counts["table_rows"] - _count_table_rows(structure)),
        code_fences_lost=max(0, counts["code_fences"] - _count_code_blocks(structure)),
    )


def _count_table_rows(segments: Sequence[str]) -> int:
    return sum(1 for segment in segments if _TABLE_ROW.match(segment))


def _count_code_blocks(segments: Sequence[str]) -> int:
    return sum(1 for segment in segments if "\n" in segment and not _TABLE_ROW.match(segment))


def _admitted_at(answer: Answer, count_limit: int, char_limit: int) -> tuple[bool, str]:
    """Would this answer survive the two limits, and which one blocks it?"""

    segments = _split_sentences(answer.text)
    over_count = len(segments) > count_limit
    over_chars = any(len(part) > char_limit for part in segments)
    if over_count and over_chars:
        return False, "both"
    if over_count:
        return False, "segment_count"
    if over_chars:
        return False, "segment_chars"
    return True, ""


def _sweep(answers: Sequence[Answer]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for limit in COUNT_LIMITS:
        admitted, blocked = 0, {"segment_count": 0, "segment_chars": 0, "both": 0}
        for answer in answers:
            ok, reason = _admitted_at(answer, limit, binder._MAX_SEGMENT_CHARS)
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
            1
            for answer in answers
            if _admitted_at(answer, binder._MAX_SEGMENTS, char_limit)[0]
        )
        char_rows.append({"char_limit": char_limit, "admitted": admitted})
    return {"by_segment_limit": rows, "by_char_limit": char_rows}


def _report(answers: Sequence[Answer], sweep: dict[str, Any]) -> str:
    total = len(answers)
    current = sum(1 for answer in answers if answer.accepted_at_current)
    count_blocked = sum(1 for answer in answers if answer.current_reason == "segment_count")
    char_blocked = sum(1 for answer in answers if answer.current_reason == "segment_chars")
    structure_ok = sum(1 for answer in answers if answer.structure_segments <= 16)
    reduction = sum(answer.raw_segments for answer in answers) - sum(
        answer.structure_segments for answer in answers
    )
    lost_numbers = sum(answer.numbers_lost for answer in answers)
    heading_numbers = sum(answer.numbers_in_headings for answer in answers)
    lost_rows = sum(answer.table_rows_lost for answer in answers)
    lost_code = sum(answer.code_fences_lost for answer in answers)

    lines = [
        "# 分段覆盖评估（零成本）",
        "",
        "> 数据：`docs/research_quality/answer_ab` 的 20 轮归档答案；",
        "> 费用：0；重现：`PYTHONPATH=. python tools/segmentation_coverage.py`；",
        "> 本评估**不改任何生产预算**，只测量两个独立限制的影响。",
        "",
        "## 1. 现状：两个独立限制",
        "",
        f"- 当前 `_MAX_SEGMENTS = {binder._MAX_SEGMENTS}`、"
        f"`_MAX_SEGMENT_CHARS = {binder._MAX_SEGMENT_CHARS}`；任一触发即整份答案被拒；",
        f"- 当前可进入绑定：**{current} / {total}**；",
        f"- 其中因**段数**被挡：{count_blocked}；因**单段过长**被挡：{char_blocked}。",
        "",
        "这条区分很重要：如果被挡的答案里有单段超过 1200 字符，单纯提高段数上限也救不回来。",
        "",
        "## 2. 只提高段数上限能救回多少（字符上限保持 "
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
        "> 这是**允许进入分段**的静态结果，不是模型成功绑定率，也不是回答质量。",
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
        "## 4. 结构感知分段的探针（不修改生产）",
        "",
        "把 Markdown 标题视为结构（不计为事实）、表格行与列表项各算一个事实单元、"
        "代码块整体算一个单元、其余按生产分段正则切句。",
        "",
        "| 指标 | 值 |",
        "| --- | ---: |",
        f"| 现有规则的总分段数 | {sum(a.raw_segments for a in answers)} |",
        f"| 结构感知探针的总单元数 | {sum(a.structure_segments for a in answers)} |",
        f"| 减少的单元数 | {reduction} |",
        f"| 结构规则下能进 16 段的答案 | {structure_ok} / {total} |",
        f"| 数字丢失（标题以外，应恒为 0） | **{lost_numbers}** |",
        f"| 仅出现在标题里的数字（有意排除，已单列） | {heading_numbers} |",
        f"| 表格行丢失（应恒为 0） | **{lost_rows}** |",
        f"| 代码块丢失（应恒为 0） | **{lost_code}** |",
        "",
        "「丢失」按内容核对：答案里出现的每个数字都必须仍出现在某个事实单元里。"
        "标题被有意排除（它不陈述事实），但标题里出现的数字单独计数，"
        "以便判断是否需要把含数字的标题也纳入核验。",
        "",
        "## 5. 逐条明细",
        "",
        "| 文件 | 查询 | 段数 | 最长段 | 现状 | 结构单元 | 表格行 | 代码块 | 丢数字 |",
        "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for answer in answers:
        status = "接受" if answer.accepted_at_current else (
            "段数" if answer.current_reason == "segment_count" else "单段"
        )
        lines.append(
            f"| {answer.file} | {answer.query[:22]} | {answer.raw_segments} | "
            f"{answer.longest_segment} | {status} | {answer.structure_segments} | "
            f"{answer.table_rows} | {answer.code_fences} | {answer.numbers_lost} |"
        )
    lines += [
        "",
        "## 6. 对 A2/A3 预算的含义",
        "",
        "- A2 的候选预算当前按 `段数 × 3` 推导；段数上限变化后必须同步重算，"
        "否则会出现“答案能进绑定，但尾部 claim 拿不到候选”。",
        "- Binder 要求模型对**每个** segment 返回一条记录；段数增加会同时放大"
        "输出长度、漏项/重复/格式错误的风险。",
        "- Binder 另有 24 条证据行与输入长度约束；提高分段上限不会自动解除它们。",
        "",
        "## 7. 结论（供裁定，不含实现）",
        "",
        f"1. 目前被挡的 {total - current} 轮答案中，段数原因 {count_blocked} 轮、"
        f"单段原因 {char_blocked} 轮——两者必须分开处理。",
        f"2. 结构感知分段把总单元从 {sum(a.raw_segments for a in answers)} 降到 "
        f"{sum(a.structure_segments for a in answers)}；标题以外的数字丢失 "
        f"{lost_numbers} 个、表格行丢失 {lost_rows} 行、代码块丢失 {lost_code} 块，"
        f"仅出现在标题里的数字 {heading_numbers} 个（有意排除、需单独决定）；"
        f"按 16 段预算可覆盖 {structure_ok} / {total} 轮答案。",
        "3. 发布覆盖要求不变：不能只验证前 N 段就把整份答案标为通过；"
        "任何分段策略都必须保持“所有 factual claim 都有判定”这一条。",
        f"4. 本轮同时堵上一个覆盖漏洞：16 段以内但渲染后超过 "
        f"{binder._MAX_CONTEXT_CHARS} 字符的 prompt 过去会被**静默截断**，"
        "等于要求模型为它没看到的尾部段落作判定；现在直接以 "
        "`answer_context_truncated` 拒绝并**不调用模型**（负控已加）。"
        "这是 fail-closed，不改变任何预算。",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json-out", type=Path, default=JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=MD_OUT)
    args = parser.parse_args(argv)

    answers = [
        _probe(path, arm, query, text)
        for path, arm, query, text in _iter_answers(args.root)
    ]
    sweep = _sweep(answers)
    args.json_out.write_text(
        json.dumps(
            {
                "limits": {
                    "segments": binder._MAX_SEGMENTS,
                    "segment_chars": binder._MAX_SEGMENT_CHARS,
                },
                "answers": [
                    {key: value for key, value in asdict(answer).items() if key != "text"}
                    for answer in answers
                ],
                "sweep": sweep,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    args.md_out.write_text(_report(answers, sweep), encoding="utf-8")
    print(
        json.dumps(
            {
                "answers": len(answers),
                "accepted": sum(1 for a in answers if a.accepted_at_current),
                "structure_ok_at_16": sum(1 for a in answers if a.structure_segments <= 16),
                "sweep": sweep["by_segment_limit"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
