"""Stage B: run the real binder over structure + 24 units (paid, capped).

Experiment only. Production still segments with the 16-segment rule; this
runner patches the segmentation function **in this process** so the production
prompt, parser and server-side checks see the 24 structure units instead.

Safety:

* refuses to call a model unless every spend-guard variable is set explicitly;
* caps the run at the approved 0.50 CNY and a 2000-token output ceiling;
* one attempt per turn: a parse failure is recorded as a failure, never retried;
* each turn writes its units, rows and outcome so the run is auditable.

Usage::

    python tools/binder_stage_b_run.py --dry-run
    python tools/binder_stage_b_run.py --execute

The dry run prints the exact environment gate and the reservation bound.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from src.application import answer_claim_binder as binder_module
from src.application.answer_claim_binder import (
    AnswerClaimBindingRequest,
    AnswerClaimBindingRow,
    bind_answer_claims,
)
from src.web.research.fact_units import DEFAULT_MAX_UNITS, build_fact_units

ROOT = Path("docs/research_quality/answer_ab")
JSON_OUT = Path("docs/research_quality/BINDER_STAGE_B_RUN.json")
MD_OUT = Path("docs/research_quality/BINDER_STAGE_B_RUN.md")

MAX_TOKENS = 2000
REQUIRED_ENV = (
    "LLM_SPEND_EXPERIMENT_CAP_CNY",
    "LLM_SPEND_INPUT_CNY_PER_MTOK",
    "LLM_SPEND_OUTPUT_CNY_PER_MTOK",
    "LLM_SPEND_DEFAULT_MAX_TOKENS",
    "LLM_EXPERIMENT_ALLOWED_MODELS",
    "DEEPSEEK_MODEL_FLASH_NAME",
)
_READ_BLOCK = re.compile(r"^【已读取 (\d+)】(.+)$", re.M)
_RUN_NONCE = os.getenv("STAGE_B_RUN_NONCE", "").strip() or time.strftime("%Y%m%dT%H%M%S")

SELECTED = (
    ("fallback_20261030T012907.json", "astral-sh uv pip", "普通长文"),
    ("ddg_first_20261030T013119.json", "SQLite WAL mode", "表格密集"),
    ("fallback_20261030T012907.json", "星铁 千冶", "含结论标题"),
    ("ddg_first_20261030T013119.json", "PostgreSQL latest", "短篇数字密集"),
)


@dataclass
class TurnOutcome:
    label: str
    file: str
    query: str
    units: int
    rows: int
    status: str = ""
    reason: str = ""
    claims: int = 0
    links: int = 0
    supported_factual: int = 0
    unsupported_factual: int = 0
    coverage_ok: bool = False
    error: str = ""
    raw_output: str = ""


def _iter_turns(root: Path):
    for path in sorted(root.glob("*_2026*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for turn in payload.get("turns") or []:
            if isinstance(turn, dict):
                yield path, turn


def _answer_text(turn: dict) -> str:
    field = turn.get("answer")
    return str(field.get("text") or "") if isinstance(field, dict) else str(field or "")


def _rows(source_block: str) -> tuple[AnswerClaimBindingRow, ...]:
    matches = list(_READ_BLOCK.finditer(source_block))
    rows: list[AnswerClaimBindingRow] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source_block)
        lines = [line.strip() for line in source_block[match.end() : end].splitlines() if line.strip()]
        url = next((line for line in lines if line.startswith("http")), "")
        body = "\n".join(line for line in lines if line != url)
        if not url or not body:
            continue
        rows.append(
            AnswerClaimBindingRow(
                evidence_id=f"read-{match.group(1)}",
                title=match.group(2).strip(),
                url=url,
                grounding_text=body,
            )
        )
    return tuple(rows)


def _select(root: Path) -> list[tuple[str, Path, dict]]:
    turns = list(_iter_turns(root))
    chosen: list[tuple[str, Path, dict]] = []
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
        chosen.append((label, match[0], match[1]))
    return chosen


def _gate() -> str:
    missing = [name for name in REQUIRED_ENV if not os.getenv(name, "").strip()]
    if missing:
        return "missing env: " + ", ".join(missing)
    return ""


def _run_turn(label: str, path: Path, turn: dict) -> TurnOutcome:
    answer = _answer_text(turn)
    research = turn.get("research") if isinstance(turn.get("research"), dict) else {}
    rows = _rows(str(research.get("source_block") or ""))
    units = build_fact_units(answer, max_units=DEFAULT_MAX_UNITS)
    outcome = TurnOutcome(
        label=label,
        file=path.name,
        query=str(turn.get("query") or ""),
        units=units.counted_units,
        rows=len(rows),
    )
    if not units.accepted or not rows:
        outcome.status = "skipped"
        outcome.reason = units.reason or "no_evidence_rows"
        return outcome

    segment_texts = tuple(unit.text for unit in units.units)
    original = binder_module.segment_answer_with_stats

    def fake_segment(_answer: str):
        return segment_texts, {
            "raw_nonempty_segment_count": len(segment_texts),
            "segment_limit": DEFAULT_MAX_UNITS,
            "max_segment_chars": 1200,
            "segment_overflow": False,
            "overflow_reason": "",
            "accepted": True,
        }

    binder_module.segment_answer_with_stats = fake_segment
    provider_error: list[str] = []
    try:
        from src.llm_client import chat
        from src.llm_spend_guard import spend_scope

        def model_fn(messages: Sequence[dict[str, Any]]) -> str:
            try:
                with spend_scope(
                    run_id=f"stage-b:{label}",
                    purpose="answer_claim_binding",
                    experiment=os.getenv("LLM_SPEND_EXPERIMENT_ID", ""),
                ):
                    return chat(
                        list(messages),
                        temperature=0.0,
                        model_profile="flash",
                        provider_profile="deepseek",
                        max_tokens=MAX_TOKENS,
                        task_name="answer_claim_binding",
                        request_max_retries=0,
                        timeout=90,
                        response_format={"type": "json_object"},
                        request_key=f"stage-b|{_RUN_NONCE}|{label}",
                    )
            except Exception as exc:  # noqa: BLE001 - recorded for the run log
                provider_error.append(f"{type(exc).__name__}: {exc}")
                raise

        bound = bind_answer_claims(
            request=AnswerClaimBindingRequest(
                question=str(turn.get("query") or ""),
                final_answer=answer,
                evidence_rows=rows,
            ),
            model_fn=model_fn,
            max_attempts=1,
        )
    except Exception as exc:  # noqa: BLE001 - the experiment records failures
        outcome.status = "error"
        outcome.error = provider_error[-1] if provider_error else f"{type(exc).__name__}: {exc}"
        return outcome
    finally:
        binder_module.segment_answer_with_stats = original

    if provider_error:
        outcome.error = provider_error[-1]

    snapshot = bound.snapshot
    outcome.raw_output = bound.raw_output[:600]
    outcome.status = snapshot.status
    outcome.reason = snapshot.reason
    outcome.claims = len(snapshot.claims)
    outcome.links = len(snapshot.claim_links)
    factual = [claim for claim in snapshot.claims if claim.kind == "factual"]
    supported = {
        link.claim_id
        for link in snapshot.claim_links
        if link.support_type in {"direct_support", "indirect_support"}
        and link.confidence >= 0.6
    }
    outcome.supported_factual = sum(1 for claim in factual if claim.id in supported)
    outcome.unsupported_factual = len(factual) - outcome.supported_factual
    outcome.coverage_ok = outcome.claims == len(segment_texts)
    return outcome


def _report(outcomes: Sequence[TurnOutcome], gate: str) -> str:
    lines = [
        "# 阶段 B：structure + 24 真实绑定结果",
        "",
        "> 实验专用：仅在本进程内替换分段函数，未修改生产入口。",
        "> 模型 deepseek-flash，max_tokens 2000，单次尝试，不自动重试。",
        "",
    ]
    if gate:
        lines += [f"**未执行**：{gate}", ""]
        return "\n".join(lines)
    lines += [
        "| 形态 | 文件 | 单元 | 证据行 | 状态 | 原因 | claims | links | 已支持 factual | 未支持 factual | 全段覆盖 |",
        "| --- | --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for outcome in outcomes:
        lines.append(
            f"| {outcome.label} | {outcome.file} | {outcome.units} | {outcome.rows} | "
            f"{outcome.status} | {outcome.reason or '-'} | {outcome.claims} | "
            f"{outcome.links} | {outcome.supported_factual} | "
            f"{outcome.unsupported_factual} | {'是' if outcome.coverage_ok else '否'} |"
        )
    lines += [
        "",
        "说明：`未支持 factual` 包含服务端按原句规则拒绝的改写型陈述，"
        "这正是 A3 尚未能力化之前应有的结果；本次不评估语义支持正确率。",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json-out", type=Path, default=JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=MD_OUT)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", type=int, default=-1)
    args = parser.parse_args(argv)

    gate = _gate()
    if not args.execute:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "gate": gate or "ready",
                    "turns": [
                        {"label": label, "file": path.name, "query": str(turn.get("query") or "")}
                        for label, path, turn in _select(args.root)
                    ],
                    "max_tokens": MAX_TOKENS,
                    "cap_cny": os.getenv("LLM_SPEND_EXPERIMENT_CAP_CNY", ""),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if gate:
        raise SystemExit(gate)

    ledger_db = os.getenv("LLM_SPEND_LEDGER_DB", "").strip()
    if ledger_db:
        from src.infrastructure.sqlite.database import RuntimeDatabase

        RuntimeDatabase(Path(ledger_db)).initialize()

    selected = _select(args.root)
    if args.only >= 0:
        selected = [selected[args.only]]
    outcomes = [_run_turn(label, path, turn) for label, path, turn in selected]
    args.json_out.write_text(
        json.dumps([asdict(outcome) for outcome in outcomes], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    args.md_out.write_text(_report(outcomes, ""), encoding="utf-8")
    print(json.dumps([asdict(outcome) for outcome in outcomes], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
