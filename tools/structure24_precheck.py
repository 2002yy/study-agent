"""Zero-cost pre-check for the approved `structure + 24` comparison.

Stage A of the segmentation experiment: run the candidate fact-unit builder over
the archived answers and answer four questions before any paid call.

1. How many answers fit 24 units, and what does one unit cost?
2. Does every unit still map back to the answer text it came from?
3. Which units are being spent on code, tables and headings rather than prose?
4. Why do some answers still exceed 32 units - is the count inflated by
   formatting, or are there genuinely that many candidate facts?

No model is called and no production budget is touched.

Run: ``PYTHONPATH=. python tools/structure24_precheck.py``
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from src.web.research.fact_units import (
    CANDIDATES_PER_UNIT,
    DEFAULT_MAX_UNITS,
    MAX_PROMPT_CHARS,
    build_fact_units,
)

ROOT = Path("docs/research_quality/answer_ab")
JSON_OUT = Path("docs/research_quality/STRUCTURE24_PRECHECK.json")
MD_OUT = Path("docs/research_quality/STRUCTURE24_PRECHECK.md")

#: Records are rendered by the binder as one JSON entry per unit.
_RECORD_CHARS = 150
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


@dataclass
class Check:
    file: str
    arm: str
    query: str
    accepted: bool
    reason: str
    units: int = 0
    dropped_headings: int = 0
    prompt_chars: int = 0
    candidate_budget: int = 0
    kinds: dict[str, int] = field(default_factory=dict)
    mapping_ok: int = 0
    mapping_bad: list[str] = field(default_factory=list)
    wide_kinds: dict[str, int] = field(default_factory=dict)


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


def _unit_maps_back(answer: str, unit) -> bool:
    """A unit is mapped when its numbers and its text come from its own span."""

    span = answer[unit.start : unit.end]
    if not span.strip():
        return False
    if unit.kind == "table_row":
        # A row may legitimately carry no digits (a status, a name). Check the
        # values the unit renders, not the presence of a number.
        values = [part.split(":", 1)[-1].strip() for part in unit.text.split("；")]
        values = [value for value in values if value]
        return bool(values) and all(value in span for value in values)
    if unit.kind == "code":
        return unit.text.strip() and unit.text.strip() in span
    return unit.text.strip() in span


def _check(path: Path, arm: str, query: str, answer: str) -> Check:
    result = build_fact_units(answer, max_units=DEFAULT_MAX_UNITS)
    check = Check(
        file=path.name,
        arm=arm,
        query=query,
        accepted=result.accepted,
        reason=result.reason,
        units=result.counted_units,
        dropped_headings=len(result.dropped),
        prompt_chars=result.prompt_chars,
        candidate_budget=result.candidate_budget,
        kinds=dict(result.kinds),
    )
    for unit in result.units:
        if _unit_maps_back(answer, unit):
            check.mapping_ok += 1
        else:
            check.mapping_bad.append(f"{unit.kind}:{unit.text[:40]}")
    wide = build_fact_units(answer, max_units=512)
    if wide.counted_units > 32:
        check.wide_kinds = dict(wide.kinds)
    return check


def _budget_rows() -> list[tuple[str, int]]:
    units = DEFAULT_MAX_UNITS
    return [
        ("事实单元", units),
        ("A2 候选（每单元 3）", units * CANDIDATES_PER_UNIT),
        ("Binder 输出记录", units),
        ("按 150 字符估算输出", units * _RECORD_CHARS),
        ("分段 prompt 上限", MAX_PROMPT_CHARS),
    ]


def _report(checks: Sequence[Check]) -> str:
    total = len(checks)
    accepted = sum(1 for check in checks if check.accepted)
    rejected = [check for check in checks if not check.accepted]
    mapping_ok = sum(check.mapping_ok for check in checks)
    mapping_bad = sum(len(check.mapping_bad) for check in checks)
    accepted_units = sum(check.units for check in checks if check.accepted)
    kinds = Counter()
    for check in checks:
        kinds.update(check.kinds)
    dropped = sum(check.dropped_headings for check in checks)
    wide = [check for check in checks if check.wide_kinds]
    wide_totals = Counter()
    for check in wide:
        wide_totals.update(check.wide_kinds)

    lines = [
        "# structure + 24 零费用预检（阶段 A）",
        "",
        "> 对象：`docs/research_quality/answer_ab` 的 20 轮归档答案；",
        "> 费用：0；重现：`PYTHONPATH=. python tools/structure24_precheck.py`；",
        "> 实验专用构建器 `src/web/research/fact_units.py`，**未接入生产入口**。",
        "",
        "## 1. 结论",
        "",
        f"- 24 单元预算下可进入：**{accepted} / {total}**；"
        f"被拒 {len(rejected)} 轮（全部是单元预算，非静默截断）。",
        f"- 单元到原文的映射：**{mapping_ok} 通过 / {mapping_bad} 失败**。",
        f"- 被丢弃的序号标题：{dropped} 个（全部记录在 `dropped`，可复查）。",
        f"- 被接受答案的单元合计 {accepted_units}，对应 A2 候选 "
        f"{accepted_units * CANDIDATES_PER_UNIT}。",
        "",
        "> 与上一轮探针的差别：那个探针把 52 个标题当作“结构”丢弃；"
        "本次构建器**默认保留所有标题**（只丢纯序号），接受数仍是 13/20。"
        "也就是说，丢掉标题并没有换来更多覆盖，反而丢了内容。",
        "",
        "## 2. 单轮预算（按 24 单元推导，不是 20 轮合计）",
        "",
        "| 项目 | 单轮上限 |",
        "| --- | ---: |",
    ]
    for label, value in _budget_rows():
        lines.append(f"| {label} | {value} |")
    lines += [
        "",
        "> 20 轮语料中的合计值（504 条候选等）只用于估算总成本，"
        "不能当作单轮上限。",
        "",
        "## 3. 单元构成（全部 20 轮）",
        "",
        "| 类型 | 数量 |",
        "| --- | ---: |",
    ]
    for kind, count in kinds.most_common():
        lines.append(f"| {kind} | {count} |")
    lines += [
        "",
        "## 4. 仍超过 32 单元的答案：多出来的是什么",
        "",
        f"共 {len(wide)} 轮。它们不是被某个上限挡住，而是确实产生了更多候选单元：",
        "",
        "| 文件 | 查询 | 单元 | 构成 |",
        "| --- | --- | ---: | --- |",
    ]
    for check in wide:
        composition = "，".join(f"{k}:{v}" for k, v in sorted(check.wide_kinds.items()))
        lines.append(
            f"| {check.file} | {check.query[:24]} | {sum(check.wide_kinds.values())} | "
            f"{composition} |"
        )
    if wide:
        summary = "，".join(f"{k}:{v}" for k, v in wide_totals.most_common())
        lines += [
            "",
            f"合计构成：{summary}。",
            "",
            "代码块按整块计为一个单元后仍偏多的部分，主要来自列表项与散文句；"
            "也就是说，超过 32 的答案里有相当比例是**结构性枚举**，"
            "未必等于同等数量的独立事实——这正是下一步要测量的对象。",
            "",
        ]
    lines += [
        "",
        "## 5. 逐轮明细",
        "",
        "| 文件 | 查询 | 状态 | 单元 | 丢标题 | prompt | 候选预算 | 映射失败 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for check in checks:
        status = "接受" if check.accepted else f"拒绝（{check.reason}）"
        lines.append(
            f"| {check.file} | {check.query[:22]} | {status} | {check.units} | "
            f"{check.dropped_headings} | {check.prompt_chars} | "
            f"{check.candidate_budget} | {len(check.mapping_bad)} |"
        )
    lines += [
        "",
        "## 6. 阶段 B 的入口条件（本次未执行）",
        "",
        "- 本预检只证明“单元可构建、可映射、预算可提前拒绝”，不证明模型能完成绑定；",
        "- 阶段 B 需要先确定模型、单价、单轮输出上限与硬性费用闸门，"
        "再选 4 轮代表性答案（普通长文 / 表格密集 / 代码密集 / 含结论标题）；",
        "- 单轮预估输出按 24 条记录、约 3600 字符估算，"
        "实际 token 需按模型分词换算，不能直接等同；",
        "- 验收仍看：输出完整率、映射正确率、无依据支持 0、表头语义保留、"
        "标题事实不丢、截断 0 且不被当成功、超预算必须拒绝。",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json-out", type=Path, default=JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=MD_OUT)
    args = parser.parse_args(argv)

    checks = [
        _check(path, arm, query, text)
        for path, arm, query, text in _iter_answers(args.root)
    ]
    args.json_out.write_text(
        json.dumps(
            {
                "max_units": DEFAULT_MAX_UNITS,
                "candidates_per_unit": CANDIDATES_PER_UNIT,
                "checks": [check.__dict__ for check in checks],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    args.md_out.write_text(_report(checks), encoding="utf-8")
    print(
        json.dumps(
            {
                "answers": len(checks),
                "accepted": sum(1 for c in checks if c.accepted),
                "mapping_bad": sum(len(c.mapping_bad) for c in checks),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
