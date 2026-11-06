"""Zero-cost A4 shadow report over annotated cases.

Reads a case file (claim, passage, the verdict A3 would have produced, and an
independent annotation), builds the candidates through the same verification
used in A2/A3, runs the shadow path and prints the two gate metrics.

The report never publishes anything and never calls a model: the verdict is an
input, so this measures the *gate*, not a model's accuracy.

Run: ``PYTHONPATH=. python tools/a4_shadow_report.py``
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.web.research.claim_span_provenance import verify_claim_span
from src.web.research.read_evidence import ReadEvidence
from src.web.research.support_qualification import ClaimJudgement
from src.web.research.support_shadow import ShadowCase, as_rows, run_shadow

CASES = Path("tests/fixtures/research_quality/a4_shadow_cases.json")
JSON_OUT = Path("docs/research_quality/A4_SHADOW_REPORT.json")
MD_OUT = Path("docs/research_quality/A4_SHADOW_REPORT.md")


def _build_case(raw: Mapping[str, Any]) -> ShadowCase:
    passage = str(raw.get("passage") or "")
    span_text = str(raw.get("span_text") or "")
    start = passage.index(span_text) if span_text and span_text in passage else 0
    record = ReadEvidence.build(
        url=str(raw.get("url") or ""),
        excerpt=passage,
        read_id=str(raw.get("read_id") or ""),
    )
    evidence_id = str(raw.get("evidence_id") or "")
    verification = verify_claim_span(
        {
            "claim_id": str(raw.get("claim_id") or ""),
            "claim_text": str(raw.get("claim_text") or ""),
            "evidence_id": evidence_id,
            "url": str(raw.get("url") or ""),
            "read_id": str(raw.get("read_id") or ""),
            "span_start": start,
            "span_end": start + len(span_text),
            "span_text": span_text,
            "excerpt_sha256": record.content_sha256,
        },
        evidence=[record],
        evidence_ids={evidence_id},
        evidence_urls={evidence_id: str(raw.get("url") or "")},
    )
    return ShadowCase(
        claim_id=str(raw.get("claim_id") or ""),
        claim_text=str(raw.get("claim_text") or ""),
        candidates=(verification,),
        judgements=(
            ClaimJudgement(
                claim_id=str(raw.get("claim_id") or ""),
                passage_key=(
                    f"{str(raw.get('claim_id') or '')}|{evidence_id}"
                    f"|{str(raw.get('read_id') or '')}|{start}-{start + len(span_text)}"
                ),
                verdict=str(raw.get("verdict") or ""),
                evidence_span=str(raw.get("evidence_span") or ""),
            ),
        ),
        literal_bound=bool(raw.get("literal_bound")),
    )


def load_cases(path: Path) -> tuple[tuple[ShadowCase, ...], tuple[dict[str, Any], ...]]:
    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    cases = tuple(_build_case(raw) for raw in raw_cases)
    annotations = tuple(
        raw["annotation"] | {"claim_id": raw["claim_id"]}
        for raw in raw_cases
        if isinstance(raw.get("annotation"), dict)
    )
    return cases, annotations


def _report(report, rows: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# A4 影子报告（零费用，离线）",
        "",
        "> 只测量资格闸门，不发布、不调用模型；verdict 是输入数据。",
        "",
        "## 1. 闸门指标",
        "",
        "| 指标 | 值 |",
        "| --- | ---: |",
        f"| 原句规则拒绝 | {report.literal_refused} |",
        f"| 影子路径可发布 | {report.shadow_qualified} |",
        f"| **正确增量**（拒绝→可发布→独立标注为正确） | **{report.correct_increment}** |",
        f"| **错误放行**（可发布但标注为不支持） | **{report.false_release}** |",
        f"| 无独立标注的放行 | {report.unannotated} |",
        f"| 已测量 | {'是' if report.measured else '否'} |",
        f"| **安全**（无错误放行且无未标注放行） | "
        f"{'是' if report.safe else '**否**'} |",
        "",
    ]
    if report.notes:
        lines += ["> " + note for note in report.notes] + [""]
    lines += [
        "## 2. 逐条",
        "",
        "| claim | 原句规则 | 影子判定 | 可发布 | 标注正确 | 增量 | 错误放行 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['claim_text'][:26]} | "
            f"{'通过' if row['literal_bound'] else '拒绝'} | "
            f"{row['shadow_verdict']} | "
            f"{'是' if row['shadow_publishable'] else '否'} | "
            f"{'-' if row['annotation_correct'] is None else ('是' if row['annotation_correct'] else '否')} | "
            f"{'是' if row['increment'] else '否'} | "
            f"{'是' if row['false_release'] else '否'} |"
        )
    lines += [
        "",
        "## 3. 解读",
        "",
        "- **增量不是成绩，只是机会**：`正确增量` 必须与 `错误放行` 一起看；",
        "- **错误放行是硬性安全门**：只要大于 0，`safe` 即为否，覆盖率再高也不能抵消；",
        "- **未标注即未测量**：任何影子放行缺少独立标注时，报告不给准确率，也不判安全。",
        "",
        "## 4. 这份样本证明了什么、没证明什么",
        "",
        "- 证明：闸门能算出两个指标，并且会把「证据只说明同时发生、claim 却断言因果」"
        "以及「主客体互换」「否定句放行」判为错误放行；",
        "- 未证明：真实模型的 `supports` 判断准确率——verdict 在本样本中是人工给定的输入，"
        "这正是下一步需要用真实模型影子运行去测的部分。",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--json-out", type=Path, default=JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=MD_OUT)
    args = parser.parse_args(argv)

    cases, annotations = load_cases(args.cases)
    report = run_shadow(cases, annotations)
    rows = as_rows(report)
    args.json_out.write_text(
        json.dumps(
            {
                "literal_refused": report.literal_refused,
                "shadow_qualified": report.shadow_qualified,
                "correct_increment": report.correct_increment,
                "false_release": report.false_release,
                "unannotated": report.unannotated,
                "measured": report.measured,
                "safe": report.safe,
                "false_release_rate": report.false_release_rate,
                "rows": list(rows),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    args.md_out.write_text(_report(report, rows), encoding="utf-8")
    print(
        json.dumps(
            {
                "correct_increment": report.correct_increment,
                "false_release": report.false_release,
                "unannotated": report.unannotated,
                "measured": report.measured,
                "safe": report.safe,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
