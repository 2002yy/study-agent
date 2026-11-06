"""Zero-cost plan for the approved structure + 24 binder comparison.

The comparison itself needs a paid model call, so this tool does not make one.
It fixes the four answers, builds their units and evidence rows, and prints the
reservation bounds the spend guard would compute - so the cap can be approved
against measured numbers instead of a guess.

The four answers are chosen from the ones that fit 24 units, therefore they can
actually be bound. A code-dense answer does not fit 24 (its extra units are
prose, not code), which the plan reports rather than hides.

Run: ``PYTHONPATH=. python tools/binder_stage_b_plan.py``
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

from src.web.research.fact_units import DEFAULT_MAX_UNITS, build_fact_units

ROOT = Path("docs/research_quality/answer_ab")
JSON_OUT = Path("docs/research_quality/BINDER_STAGE_B_PLAN.json")

#: Prices the archived A/B run already used and the project accepted.
INPUT_CNY_PER_MTOK = 2.5
OUTPUT_CNY_PER_MTOK = 9.0
#: Requested output ceiling per turn; one record per unit plus JSON scaffolding.
MAX_TOKENS = 2000
#: The binder renders question + unit block + evidence rows into one prompt.
CONTEXT_CHARS = 16000
SYSTEM_CHARS = 1500

_READ_BLOCK = re.compile(r"^【已读取 (\d+)】(.+)$", re.M)

#: (file, query fragment) - one answer per shape, all inside the 24-unit budget.
SELECTED = (
    ("fallback_20261030T012907.json", "astral-sh uv pip", "普通长文"),
    ("ddg_first_20261030T013119.json", "SQLite WAL mode", "表格密集"),
    ("fallback_20261030T012907.json", "星铁 千冶", "含结论标题"),
    ("ddg_first_20261030T013119.json", "PostgreSQL latest", "短篇数字密集"),
)


@dataclass
class PlannedTurn:
    label: str
    file: str
    query: str
    units: int
    units_accepted: bool
    unit_reason: str
    unit_prompt_chars: int
    rows: int
    row_chars: int
    context_chars: int
    prompt_chars_bound: int
    cost_upper_cny: float


def _iter_turns(root: Path) -> Iterable[tuple[Path, dict]]:
    for path in sorted(root.glob("*_2026*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for turn in payload.get("turns") or []:
            if isinstance(turn, dict):
                yield path, turn


def _answer_text(turn: dict) -> str:
    field = turn.get("answer")
    return (
        str(field.get("text") or "")
        if isinstance(field, dict)
        else str(field or "")
    )


def _read_blocks(source_block: str) -> list[tuple[str, str, str]]:
    matches = list(_READ_BLOCK.finditer(source_block))
    blocks: list[tuple[str, str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source_block)
        lines = [line.strip() for line in source_block[match.end() : end].splitlines() if line.strip()]
        url = next((line for line in lines if line.startswith("http")), "")
        body = "\n".join(line for line in lines if line != url)
        if url and body:
            blocks.append((match.group(2).strip(), url, body))
    return blocks


def _plan(root: Path) -> list[PlannedTurn]:
    turns = list(_iter_turns(root))
    planned: list[PlannedTurn] = []
    for file_name, fragment, label in SELECTED:
        match = next(
            (
                (path, turn)
                for path, turn in turns
                if path.name == file_name and fragment in str(turn.get("query") or "")
            ),
            None,
        )
        if match is None:
            raise SystemExit(f"selected answer not found: {file_name} / {fragment}")
        path, turn = match
        answer = _answer_text(turn)
        research = turn.get("research") if isinstance(turn.get("research"), dict) else {}
        blocks = _read_blocks(str(research.get("source_block") or ""))
        units = build_fact_units(answer, max_units=DEFAULT_MAX_UNITS)
        row_chars = sum(len(title) + len(url) + len(body) + 40 for title, url, body in blocks)
        context = min(CONTEXT_CHARS, row_chars)
        prompt_bound = min(CONTEXT_CHARS, units.prompt_chars + context) + SYSTEM_CHARS
        cost = prompt_bound / 1_000_000 * INPUT_CNY_PER_MTOK + (
            MAX_TOKENS / 1_000_000 * OUTPUT_CNY_PER_MTOK
        )
        planned.append(
            PlannedTurn(
                label=label,
                file=path.name,
                query=str(turn.get("query") or ""),
                units=units.counted_units,
                units_accepted=units.accepted,
                unit_reason=units.reason,
                unit_prompt_chars=units.prompt_chars,
                rows=len(blocks),
                row_chars=row_chars,
                context_chars=context,
                prompt_chars_bound=prompt_bound,
                cost_upper_cny=round(cost, 4),
            )
        )
    return planned


def _report(planned: Sequence[PlannedTurn]) -> str:
    total = round(sum(turn.cost_upper_cny for turn in planned), 4)
    lines = [
        "# 阶段 B 计划（structure + 24，未执行）",
        "",
        "> 本文件只做零费用规划：选定答案、构建单元、按 spend guard 口径估算上界。",
        "> 未调用任何模型。",
        "",
        "## 1. 选定的 4 轮",
        "",
        "| 形态 | 文件 | 查询 | 单元 | 可绑定 | 单元 prompt | 证据行 | 上下文 | prompt 上界 | 单轮费用上界 |",
        "| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for turn in planned:
        lines.append(
            f"| {turn.label} | {turn.file} | {turn.query[:22]} | {turn.units} | "
            f"{'是' if turn.units_accepted else '否（' + turn.unit_reason + '）'} | "
            f"{turn.unit_prompt_chars} | {turn.rows} | {turn.context_chars} | "
            f"{turn.prompt_chars_bound} | ¥{turn.cost_upper_cny:.4f} |"
        )
    lines += [
        "",
        f"**4 轮合计上界：¥{total:.4f}**（输入 ¥{INPUT_CNY_PER_MTOK}/M、输出 "
        f"¥{OUTPUT_CNY_PER_MTOK}/M、max_tokens {MAX_TOKENS}）。",
        "",
        "## 2. 预算闸门（需确认后才执行）",
        "",
        "```",
        "LLM_SPEND_EXPERIMENT_CAP_CNY=0.50",
        f"LLM_SPEND_INPUT_CNY_PER_MTOK={INPUT_CNY_PER_MTOK}",
        f"LLM_SPEND_OUTPUT_CNY_PER_MTOK={OUTPUT_CNY_PER_MTOK}",
        f"LLM_SPEND_DEFAULT_MAX_TOKENS={MAX_TOKENS}",
        "LLM_EXPERIMENT_ALLOWED_MODELS=<确认的 flash 模型 id>",
        "```",
        "",
        "上界合计远低于 ¥0.50；即使 4 轮全部用满上下文与输出上限也不会超。",
        "不设自动重试：任何一次解析失败都按失败记录，不追加调用。",
        "",
        "## 3. 已发现的一个选择限制",
        "",
        "代码密集的答案（FastAPI 两轮，6 个代码块）需要 38～43 个单元，"
        "**进不了 24 单元预算**；它们多出来的单元主要是散文与列表，不是代码。"
        "因此本次 4 轮不包含代码密集形态——代码形态能否在 24 内处理，"
        "要等 24 的结果或改用 32 才能回答。",
        "",
        "## 4. 验收口径（执行时逐条记录）",
        "",
        "| 指标 | 要求 |",
        "| --- | --- |",
        "| 每条单元是否都有且仅有一条记录 | 必须 |",
        "| 记录与单元的映射 | 不允许错位 / 重复 / 未知 ref |",
        "| 无依据的支持结论 | 0（服务端仍按原句/资格规则裁决） |",
        "| 表头语义 | 行单元里的字段名与取值一致 |",
        "| 标题事实 | 不丢失（构建器已保留，模型不得推断） |",
        "| 输出截断 | 0 次被当作成功 |",
        "| 单轮费用 | ≤ 上表上界，且总量 ≤ cap |",
        "| 超预算 | 必须拒绝，不能继续调用 |",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json-out", type=Path, default=JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=JSON_OUT.with_suffix(".md"))
    args = parser.parse_args(argv)

    planned = _plan(args.root)
    args.json_out.write_text(
        json.dumps(
            {
                "prices": {
                    "input_cny_per_mtok": INPUT_CNY_PER_MTOK,
                    "output_cny_per_mtok": OUTPUT_CNY_PER_MTOK,
                },
                "max_tokens": MAX_TOKENS,
                "turns": [asdict(turn) for turn in planned],
                "total_upper_cny": round(sum(t.cost_upper_cny for t in planned), 4),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    args.md_out.write_text(_report(planned), encoding="utf-8")
    print(
        json.dumps(
            {
                "turns": len(planned),
                "total_upper_cny": round(sum(t.cost_upper_cny for t in planned), 4),
                "units": [t.units for t in planned],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
