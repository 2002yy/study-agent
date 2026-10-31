"""A4 shadow with a real model: does deepseek-flash judge support correctly?

The offline report measured the gate with human verdicts as input. This run asks
the model for the verdict instead and compares it with the same annotations, so
the question becomes the one that decides production: are the model's
``supports`` verdicts right, and what does it cost?

Paid, bounded, one attempt per case, no retries. The model never publishes; the
shadow ledger decides whether a release *would* have happened.

Run::

    python tools/a4_shadow_model_run.py --dry-run
    python tools/a4_shadow_model_run.py --execute
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.web.research.claim_span_provenance import verify_claim_span
from src.web.research.read_evidence import ReadEvidence
from src.web.research.support_qualification import ClaimJudgement, decide_claim_support

CASES = Path("tests/fixtures/research_quality/a4_shadow_cases.json")
JSON_OUT = Path("docs/research_quality/A4_SHADOW_MODEL_RUN.json")
MD_OUT = Path("docs/research_quality/A4_SHADOW_MODEL_RUN.md")

MAX_TOKENS = 300
CASE_LIMIT = 6
REQUIRED_ENV = (
    "LLM_SPEND_EXPERIMENT_CAP_CNY",
    "LLM_SPEND_INPUT_CNY_PER_MTOK",
    "LLM_SPEND_OUTPUT_CNY_PER_MTOK",
    "LLM_SPEND_DEFAULT_MAX_TOKENS",
    "LLM_EXPERIMENT_ALLOWED_MODELS",
    "DEEPSEEK_MODEL_FLASH_NAME",
    "LLM_SPEND_EXPERIMENT_ID",
)

SYSTEM = (
    "You judge whether ONE quoted passage supports ONE claim.\n"
    "Return JSON only: {\"verdict\": \"supports|contradicts|insufficient\", "
    "\"evidence_span\": \"exact words copied from the passage\", "
    "\"reason\": \"one short sentence\"}.\n"
    "Rules:\n"
    "1. supports only when the passage itself asserts the claim, including "
    "direction, subject/object, polarity and numbers.\n"
    "2. Two things happening together is NOT causation; a causal claim needs the "
    "passage to state the causal relation.\n"
    "3. If the passage denies or reverses the claim, answer contradicts.\n"
    "4. If the passage does not address the claim, answer insufficient.\n"
    "5. evidence_span must be copied verbatim from the passage."
)


@dataclass
class CaseOutcome:
    claim_id: str
    claim_text: str
    model_verdict: str = ""
    model_span: str = ""
    span_inside: bool = False
    gate_publishable: bool = False
    annotation_correct: bool | None = None
    literal_bound: bool = False
    increment: bool = False
    false_release: bool = False
    raw: str = ""
    error: str = ""
    seconds: float = 0.0


@dataclass
class RunSummary:
    cases: int = 0
    model_supports: int = 0
    model_contradicts: int = 0
    model_insufficient: int = 0
    invalid: int = 0
    gate_releases: int = 0
    correct_releases: int = 0
    false_releases: int = 0
    increment: int = 0
    errors: list[str] = field(default_factory=list)


def _gate() -> str:
    missing = [name for name in REQUIRED_ENV if not os.getenv(name, "").strip()]
    return "missing env: " + ", ".join(missing) if missing else ""


def _passage_key(raw: Mapping[str, Any], start: int, span: str) -> str:
    return (
        f"{raw.get('claim_id')}|{raw.get('evidence_id')}"
        f"|{raw.get('read_id')}|{start}-{start + len(span)}"
    )


def _ask(messages: list[dict[str, str]], label: str):
    from src.llm_client import chat
    from src.llm_spend_guard import spend_scope

    with spend_scope(
        run_id=f"a4-shadow:{label}",
        purpose="claim_support_judgement",
        experiment=os.getenv("LLM_SPEND_EXPERIMENT_ID", ""),
    ):
        return chat(
            messages,
            temperature=0.0,
            model_profile="flash",
            provider_profile="deepseek",
            max_tokens=MAX_TOKENS,
            task_name="claim_support_judgement",
            request_max_retries=0,
            timeout=90,
            response_format={"type": "json_object"},
            request_key=f"a4-shadow|{time.strftime('%Y%m%dT%H%M%S')}|{label}",
        )


def _run_case(raw: Mapping[str, Any]) -> CaseOutcome:
    claim_id = str(raw.get("claim_id") or "")
    claim_text = str(raw.get("claim_text") or "")
    passage = str(raw.get("passage") or "")
    span = str(raw.get("span_text") or "")
    outcome = CaseOutcome(
        claim_id=claim_id,
        claim_text=claim_text,
        annotation_correct=(raw.get("annotation") or {}).get("support_is_correct"),
        literal_bound=bool(raw.get("literal_bound")),
    )
    start = passage.index(span) if span and span in passage else 0
    record = ReadEvidence.build(
        url=str(raw.get("url") or ""),
        excerpt=passage,
        read_id=str(raw.get("read_id") or ""),
    )
    evidence_id = str(raw.get("evidence_id") or "")
    candidate = verify_claim_span(
        {
            "claim_id": claim_id,
            "claim_text": claim_text,
            "evidence_id": evidence_id,
            "url": str(raw.get("url") or ""),
            "read_id": str(raw.get("read_id") or ""),
            "span_start": start,
            "span_end": start + len(span),
            "span_text": span,
            "excerpt_sha256": record.content_sha256,
        },
        evidence=[record],
        evidence_ids={evidence_id},
        evidence_urls={evidence_id: str(raw.get("url") or "")},
    )

    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": f"Claim:\n{claim_text}\n\nPassage:\n{passage}",
        },
    ]
    started = time.monotonic()
    try:
        raw_output = _ask(messages, claim_id)
    except Exception as exc:  # noqa: BLE001 - the run records failures
        outcome.error = f"{type(exc).__name__}: {exc}"
        return outcome
    outcome.seconds = round(time.monotonic() - started, 2)
    outcome.raw = raw_output[:400]

    try:
        payload = json.loads(raw_output)
    except ValueError:
        outcome.error = "invalid_json"
        return outcome
    verdict = str(payload.get("verdict") or "").strip().lower()
    evidence_span = str(payload.get("evidence_span") or "")
    outcome.model_verdict = verdict
    outcome.model_span = evidence_span[:200]
    outcome.span_inside = bool(evidence_span) and evidence_span in passage

    decision = decide_claim_support(
        claim_id,
        candidates=[candidate],
        judgements=[
            ClaimJudgement(
                claim_id=claim_id,
                passage_key=_passage_key(raw, start, span),
                verdict=verdict,
                evidence_span=evidence_span,
                reason=str(payload.get("reason") or "")[:200],
            )
        ],
    )
    outcome.gate_publishable = decision.publishable
    correct = outcome.annotation_correct
    outcome.increment = (
        decision.publishable and correct is True and not outcome.literal_bound
    )
    outcome.false_release = decision.publishable and correct is False
    return outcome


def _report(outcomes: Sequence[CaseOutcome], summary: RunSummary) -> str:
    lines = [
        "# A4 影子：真实模型 verdict 报告（deepseek-flash）",
        "",
        "> 只记录、不发布；每例 1 次调用、不重试；verdict 由模型给出，标注由人工给定。",
        "",
        "## 1. 汇总",
        "",
        "| 指标 | 值 |",
        "| --- | ---: |",
        f"| 用例 | {summary.cases} |",
        f"| 模型 supports / contradicts / insufficient | "
        f"{summary.model_supports} / {summary.model_contradicts} / {summary.model_insufficient} |",
        f"| 输出非法（非 JSON 等） | {summary.invalid} |",
        f"| 闸门放行 | {summary.gate_releases} |",
        f"| **正确放行** | **{summary.correct_releases}** |",
        f"| **错误放行** | **{summary.false_releases}** |",
        f"| 相对原句规则的正确增量 | {summary.increment} |",
        "",
    ]
    if summary.errors:
        lines += [f"- 错误：{error}" for error in summary.errors] + [""]
    lines += [
        "## 2. 逐例",
        "",
        "| claim | 模型 verdict | 引文在片段内 | 闸门放行 | 标注正确 | 增量 | 错误放行 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for outcome in outcomes:
        correct = (
            "-"
            if outcome.annotation_correct is None
            else ("是" if outcome.annotation_correct else "否")
        )
        lines.append(
            f"| {outcome.claim_text[:24]} | {outcome.model_verdict or '-'} | "
            f"{'是' if outcome.span_inside else '否'} | "
            f"{'是' if outcome.gate_publishable else '否'} | {correct} | "
            f"{'是' if outcome.increment else '否'} | "
            f"{'是' if outcome.false_release else '否'} |"
        )
    lines += [
        "",
        "## 3. 解读",
        "",
        "- 「正确放行」= 模型 verdict 经闸门后放行，且人工标注为支持；",
        "- 「错误放行」是硬性安全指标，任何一条都使该配置不可上线；",
        "- 样本量很小（6 例），只能说明方向，不能给出准确率置信区间；",
        "- 模型引文若不在片段内，闸门会拒绝——这条规则独立于模型判断。",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--json-out", type=Path, default=JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=MD_OUT)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)

    gate = _gate()
    raw_cases = json.loads(args.cases.read_text(encoding="utf-8"))[:CASE_LIMIT]
    if not args.execute:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "gate": gate or "ready",
                    "cases": len(raw_cases),
                    "cap_cny": os.getenv("LLM_SPEND_EXPERIMENT_CAP_CNY", ""),
                    "max_tokens": MAX_TOKENS,
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

    outcomes = [_run_case(raw) for raw in raw_cases]
    summary = RunSummary(cases=len(outcomes))
    for outcome in outcomes:
        summary.gate_releases += int(outcome.gate_publishable)
        summary.correct_releases += int(outcome.gate_publishable and outcome.annotation_correct is True)
        summary.false_releases += int(bool(outcome.false_release))
        summary.increment += int(outcome.increment)
        summary.model_supports += int(outcome.model_verdict == "supports")
        summary.model_contradicts += int(outcome.model_verdict == "contradicts")
        summary.model_insufficient += int(outcome.model_verdict == "insufficient")
        if outcome.error:
            summary.invalid += 1
            summary.errors.append(f"{outcome.claim_id}: {outcome.error}")

    args.json_out.write_text(
        json.dumps(
            {"summary": asdict(summary), "cases": [asdict(o) for o in outcomes]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    args.md_out.write_text(_report(outcomes, summary), encoding="utf-8")
    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
