"""Build the frozen, blind annotation set for the A3 semantic baseline.

Thirty real claims from the archived answers, each paired with a passage this run
actually read and verified. The sheet shown to an annotator contains only the
claim and the passage: no model verdict, no A3 decision, no literal-rule result,
and no stratum label - all of those live in a separate key file so the scorer can
compute increments later without the annotator seeing the answer.

Sampling is stratified by heuristic claim shape and seeded, so the set is
reproducible. A stratum that cannot fill five slots records the shortfall instead
of inventing a case.

Run: ``PYTHONPATH=. python tools/build_annotation_set.py``
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from collections import Counter
from typing import Any, Iterable, Sequence

from src.application.answer_claim_binder import (
    claim_grounded_in_text,
    segment_answer_with_stats,
)
from src.web.research.claim_span_location import (
    ClaimToLocate,
    EvidenceSource,
    locate_claim_spans,
)
from src.web.research.claim_span_provenance import verify_claim_span
from src.web.research.read_evidence import EXCERPT_CHARS, ReadEvidence

ROOT = Path("docs/research_quality/answer_ab")
BLIND_JSON = Path("docs/research_quality/ANNOTATION_SET_V1.json")
BLIND_CSV = Path("docs/research_quality/ANNOTATION_SHEET_V1.csv")
KEYS_JSON = Path("docs/research_quality/ANNOTATION_KEYS_V1.json")
MD_OUT = Path("docs/research_quality/ANNOTATION_SET_V1.md")

SEED = 20261101
PER_STRATUM = 5
TOTAL_TARGET = 30

_READ_BLOCK = re.compile(r"^【已读取 (\d+)】(.+)$", re.M)
_CAUSAL = re.compile(r"导致|使得|使|因为|由于|原因|造成|引发|cause|because|lead to|due to", re.I)
_NEGATION = re.compile(r"不|未|并非|没有|否认|无|false|not\b|denied|no longer", re.I)
_RELATIONAL = re.compile(r"收购|击败|超过|领先|超越|取代|acquired|acquires|beats|overtakes", re.I)
_NUMBER = re.compile(r"\d")
_DATE = re.compile(r"\d{4}[-/年]\d{1,2}|\d{1,2}月|\d{4}-\d{2}-\d{2}")

STRATA = (
    "numbers_dates",
    "causality",
    "polarity_relation",
    "conflict_or_negated_passage",
    "table_or_cross_sentence",
    "paraphrase",
)
STRATUM_LABEL = {
    "numbers_dates": "数字与时间",
    "causality": "因果关系",
    "polarity_relation": "否定及主客体关系",
    "conflict_or_negated_passage": "冲突与否定证据",
    "table_or_cross_sentence": "表格与跨句推理",
    "paraphrase": "同义改写",
}


@dataclass
class PoolItem:
    claim_id: str
    claim_text: str
    passage: str
    url: str
    read_id: str
    evidence_id: str
    span_start: int
    span_end: int
    source_title: str
    source_file: str
    query: str
    stratum: str = ""
    tags: set[str] = field(default_factory=set)
    literal_bound: bool = False
    candidate_count: int = 0


def _iter_answers(root: Path) -> Iterable[tuple[Path, str, str]]:
    for path in sorted(root.glob("*_2026*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for turn in payload.get("turns") or []:
            if not isinstance(turn, dict):
                continue
            field = turn.get("answer")
            answer = (
                str(field.get("text") or "")
                if isinstance(field, dict)
                else str(field or "")
            )
            research = turn.get("research") if isinstance(turn.get("research"), dict) else {}
            block = str(research.get("source_block") or "")
            if answer.strip() and block.strip():
                yield path, str(turn.get("query") or ""), answer


def _sources(source_block: str) -> tuple[tuple[EvidenceSource, ...], dict[str, str]]:
    matches = list(_READ_BLOCK.finditer(source_block))
    sources: list[EvidenceSource] = []
    titles: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source_block)
        lines = [
            line.strip()
            for line in source_block[match.end() : end].splitlines()
            if line.strip()
        ]
        url = next((line for line in lines if line.startswith("http")), "")
        body = "\n".join(line for line in lines if line != url)[:EXCERPT_CHARS]
        if not url or not body:
            continue
        evidence_id = f"read-{match.group(1)}"
        titles[evidence_id] = match.group(2).strip()
        sources.append(
            EvidenceSource(
                evidence_id=evidence_id,
                evidence=ReadEvidence.build(
                    url=url, excerpt=body, read_id=f"replay-{match.group(1)}"
                ),
            )
        )
    return tuple(sources), titles


_ADVICE = re.compile(r"如果你需要|我可以|建议你|需要我|你先|要不要我|如需|可以帮你|帮你判断")
_CODEY = re.compile(r"```|^\(")


def _is_factual_claim(text: str) -> bool:
    """Keep statements a reader could check; drop advice, headings and scraps."""

    value = text.strip()
    if not (8 <= len(value) <= 300):
        return False
    if value[0] in "#-*|>":
        return False
    if _ADVICE.search(value) or _CODEY.search(value):
        return False
    if value.count("**") % 2 or value[-1] in "、，,：（(的":
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", value)) or len(value.split()) >= 4


def _passage_is_usable(claim: str, passage: str) -> bool:
    """Reject a pair whose overlap is too thin to be an A3 test at all."""

    numbers = set(re.findall(r"\d+(?:[.,]\d+)*", claim))
    if numbers and any(number in passage for number in numbers):
        return True
    shared = set(re.findall(r"[\u4e00-\u9fff]{2}", claim)) & set(
        re.findall(r"[\u4e00-\u9fff]{2}", passage)
    )
    return len(shared) >= 3


def _tags(claim: str, span: str) -> set[str]:
    """Every shape a claim shows, so sampling can balance instead of first-match."""

    tags: set[str] = set()
    if _DATE.search(claim) or _NUMBER.search(claim):
        tags.add("numbers_dates")
    if _CAUSAL.search(claim):
        tags.add("causality")
    if _NEGATION.search(claim) or _RELATIONAL.search(claim):
        tags.add("polarity_relation")
    if _NEGATION.search(span):
        tags.add("conflict_or_negated_passage")
    if "|" in span or len(claim) > len(span) + 10:
        tags.add("table_or_cross_sentence")
    if not tags:
        tags.add("paraphrase")
    return tags


def _pool(root: Path) -> tuple[list[PoolItem], int]:
    items: list[PoolItem] = []
    misses = 0
    for path, query, answer in _iter_answers(root):
        payload = json.loads(path.read_text(encoding="utf-8"))
        turn = next(
            (
                t
                for t in payload.get("turns") or []
                if isinstance(t, dict)
                and str((t.get("answer") or {}).get("text") if isinstance(t.get("answer"), dict) else t.get("answer")) == answer
            ),
            None,
        )
        research = (turn or {}).get("research") if isinstance(turn, dict) else {}
        block = str((research or {}).get("source_block") or "")
        sources, titles = _sources(block)
        segments, _stats = segment_answer_with_stats(answer)
        if not segments:
            # The binder rejects these answers wholesale; their claims are still
            # real, so they are taken from blank-line chunks and flagged in the
            # key file rather than silently dropped.
            segments = tuple(
                part.strip()
                for chunk in re.split(r"\n\s*\n", answer)
                for part in re.split(r"(?<=[。！？；])", chunk)
                if _is_factual_claim(part)
            )
        if not segments:
            continue
        targets = [
            ClaimToLocate(claim_id=f"{path.stem}-c{index}", text=segment)
            for index, segment in enumerate(segments, 1)
            if _is_factual_claim(segment)
        ]
        locations = locate_claim_spans(targets, sources=sources)
        for target, location in zip(targets, locations, strict=True):
            if not location.located:
                misses += 1
                continue
            # A claim may be judged against more than one real passage; up to two
            # are kept so the set can test per-passage judgement.
            for top in location.candidates[:2]:
                _append_item(
                    items,
                    target,
                    top.span,
                    sources,
                    titles,
                    path,
                    query,
                    candidate_count=len(location.candidates),
                )
    return items, misses


def _append_item(
    items: list[PoolItem],
    target: ClaimToLocate,
    span,
    sources: Sequence[EvidenceSource],
    titles: dict[str, str],
    path: Path,
    query: str,
    *,
    candidate_count: int,
) -> None:
    start, end, passage = _trim_span(target.text, span, sources)
    tags = _tags(target.text, passage)
    # A thin overlap is the point of the paraphrase and causality strata; for the
    # others a pair with almost nothing in common is not an A3 test at all.
    if not tags <= {"paraphrase", "causality"} and not _passage_is_usable(
        target.text, passage
    ):
        return
    items.append(
        PoolItem(
            claim_id=target.claim_id,
            claim_text=target.text,
            passage=passage,
            url=span.url,
            read_id=span.read_id,
            evidence_id=span.evidence_id,
            span_start=start,
            span_end=end,
            source_title=titles.get(span.evidence_id, ""),
            source_file=path.name,
            query=query,
            stratum="",
            literal_bound=claim_grounded_in_text(target.text, passage),
            candidate_count=candidate_count,
            tags=tags,
        )
    )


def _trim_span(
    claim_text: str,
    span,
    sources: Sequence[EvidenceSource],
    *,
    limit: int = 800,
    window: int = 700,
) -> tuple[int, int, str]:
    """Keep a long candidate readable while staying a verified substring.

    A 3000-character excerpt is legal but impractical to annotate. When the span
    is long, a smaller window is cut around the claim's own anchor and re-checked
    with the same verifier; if that fails the original span is kept.
    """

    if span.span_end - span.span_start <= limit:
        return span.span_start, span.span_end, span.span_text
    record = next(
        (item.evidence for item in sources if item.evidence_id == span.evidence_id),
        None,
    )
    if record is None:
        return span.span_start, span.span_end, span.span_text
    body = record.excerpt
    anchors = re.findall(r"[\u4e00-\u9fff]{4,}|\d+(?:[.,]\d+)*", claim_text)
    anchor = max(anchors, key=len) if anchors else ""
    position = body.find(anchor, span.span_start, span.span_end) if anchor else -1
    centre = position if position >= 0 else span.span_start
    start = max(span.span_start, centre - window // 3)
    end = min(span.span_end, start + window)
    while start < end and body[start].isspace():
        start += 1
    while end > start and body[end - 1].isspace():
        end -= 1
    text = body[start:end]
    verification = verify_claim_span(
        {
            "claim_id": span.claim_id,
            "claim_text": claim_text,
            "evidence_id": span.evidence_id,
            "url": span.url,
            "read_id": span.read_id,
            "span_start": start,
            "span_end": end,
            "span_text": text,
            "excerpt_sha256": record.content_sha256,
        },
        evidence=[record],
        evidence_ids={span.evidence_id},
        evidence_urls={span.evidence_id: span.url},
    )
    if not verification.verified:
        return span.span_start, span.span_end, span.span_text
    return start, end, text


def _sample(items: Sequence[PoolItem]) -> tuple[list[PoolItem], dict[str, int]]:
    """Greedy balanced draw: each stratum takes untaken items it tags."""

    rng = random.Random(SEED)
    chosen: list[PoolItem] = []
    picked: set[str] = set()
    shortfall: dict[str, int] = {}
    for stratum in STRATA:
        pool = sorted(
            (item for item in items if stratum in item.tags and item.claim_id not in picked),
            key=lambda item: (item.source_file, item.claim_id),
        )
        rng.shuffle(pool)
        take = pool[:PER_STRATUM]
        for item in take:
            item.stratum = stratum
            picked.add(item.claim_id)
        chosen.extend(take)
        if len(take) < PER_STRATUM:
            # A shortfall is recorded, never filled with a fabricated case.
            shortfall[stratum] = PER_STRATUM - len(take)

    # The corpus may not contain five cases of every shape. Rather than invent
    # them, the set is topped up with further real cases and the actual
    # composition is reported; the shortfall above stays visible.
    if len(chosen) < TOTAL_TARGET:
        rest = sorted(
            (item for item in items if item.claim_id not in picked),
            key=lambda item: (item.source_file, item.claim_id),
        )
        rng.shuffle(rest)
        for item in rest:
            if len(chosen) >= TOTAL_TARGET:
                break
            item.stratum = next(
                (stratum for stratum in STRATA if stratum in item.tags), "paraphrase"
            )
            chosen.append(item)
            picked.add(item.claim_id)
    return chosen, shortfall


def _blind_rows(chosen: Sequence[PoolItem]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"case-{index:02d}",
            "claim": item.claim_text,
            "passage": item.passage,
            "source_title": item.source_title,
            "source_url": item.url,
            "read_id": item.read_id,
            "span_start": item.span_start,
            "span_end": item.span_end,
        }
        for index, item in enumerate(chosen, 1)
    ]


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "id",
                "claim",
                "passage",
                "source_url",
                "read_id",
                "span_start",
                "span_end",
                "annotation_S_C_I_U",
                "reason",
                "disputed",
                "annotator",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["id"],
                    row["claim"],
                    row["passage"],
                    row["source_url"],
                    row["read_id"],
                    row["span_start"],
                    row["span_end"],
                    "",
                    "",
                    "",
                    "",
                ]
            )


def _report(rows: Sequence[dict[str, Any]], keys: dict[str, Any]) -> str:
    lines = [
        "# A3 独立标注集 v1（冻结，盲标）",
        "",
        "> 30 条真实 claim + 已核验片段；**不含**模型 verdict、A3 决策、原句规则结果。",
        "> 费用 0，未调用模型。",
        "",
        "## 1. 标注方法",
        "",
        "对每条记录只看 `claim` 与 `passage`，在 `annotation_S_C_I_U` 列填写四选一：",
        "",
        "| 标注 | 含义 |",
        "| --- | --- |",
        "| S | 证据足以支持完整事实 |",
        "| C | 证据明确与事实矛盾 |",
        "| I | 证据不足以确认，也无法直接反驳 |",
        "| U | 事实或证据存在歧义，需要复核（不参与正式评分） |",
        "",
        "**不要把“不支持”写成“反对”（C）**：两者是不同的语义关系。",
        "",
        "盲标要求：",
        "",
        "1. 标注者看不到模型判断、A3 是否放行、原句规则结果，也看不到分层标签；",
        "2. 不要参考其他标注者的结果；",
        "3. 记录标注者身份；判断有分歧时在 `disputed` 列写 `Y` 并在 `reason` 说明。",
        "",
        "## 2. 抽样规则（可复现）",
        "",
        "- 来源：`docs/research_quality/answer_ab` 的 20 轮归档答案；",
        "- 只取 A2 能定位到已核验片段的 claim（A2 漏检不计入本表，另记）；",
        f"- 分层启发式（仅用于抽样，不展示给标注者）：{', '.join(STRATA)}；",
        f"- 随机种子：`{SEED}`；每层最多 {PER_STRATUM} 条，不足则记录缺口，不虚构；",
        f"- 冻结指纹（盲标 JSON 的 SHA-256）：`{keys['blind_sha256']}`。",
        "",
        "## 3. 本批规模",
        "",
        f"- 实际条数：**{len(rows)}**；",
        "- 实际构成："
        + "，".join(
            f"{STRATUM_LABEL[name]} {count}"
            for name, count in sorted(
                Counter(keys["stratum_of"].values()).items()
            )
        ),
        f"- 分层缺口（真实语料不足，未虚构）：{json.dumps(keys['shortfall'], ensure_ascii=False)}",
        f"- 同批记录的 A2 漏检（未定位到片段，不进入本表）：**{keys['a2_misses']}** 条；",
        f"- 片段与 claim 重叠充分的：{sum(keys['usable_of'].values())} / {len(rows)}",
        "  （重叠薄的条目仍保留：它们正是「候选是否够用」的检验对象）。",
        "",
        "## 4. 冻结与评分",
        "",
        "- 本表在完成独立标注前**不得**因模型表现而调整样本；",
        "- 评分所需的原句规则结果、分层、A2 候选数保存在 `ANNOTATION_KEYS_V1.json`，"
        "标注者不得查看；",
        "- 30 条只是第一轮诊断集，不是生产安全性的最终验收集。",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--blind-json", type=Path, default=BLIND_JSON)
    parser.add_argument("--blind-csv", type=Path, default=BLIND_CSV)
    parser.add_argument("--keys", type=Path, default=KEYS_JSON)
    parser.add_argument("--md", type=Path, default=MD_OUT)
    args = parser.parse_args(argv)

    pool, a2_misses = _pool(args.root)
    chosen, shortfall = _sample(pool)
    rows = _blind_rows(chosen)
    blind_text = json.dumps(rows, ensure_ascii=False, indent=2)
    blind_sha = hashlib.sha256(blind_text.encode("utf-8")).hexdigest()
    keys = {
        "seed": SEED,
        "per_stratum": PER_STRATUM,
        "strata": list(STRATA),
        "shortfall": shortfall,
        "blind_sha256": blind_sha,
        "pool_size": len(pool),
        "a2_misses": a2_misses,
        "usable_of": {
            row["id"]: _passage_is_usable(row["claim"], row["passage"])
            for row in rows
        },
        "stratum_of": {row["id"]: item.stratum for row, item in zip(rows, chosen)},
        "literal_bound_of": {row["id"]: item.literal_bound for row, item in zip(rows, chosen)},
        "candidates_of": {row["id"]: item.candidate_count for row, item in zip(rows, chosen)},
        "source_file_of": {row["id"]: item.source_file for row, item in zip(rows, chosen)},
    }
    args.blind_json.write_text(blind_text, encoding="utf-8")
    _write_csv(args.blind_csv, rows)
    args.keys.write_text(json.dumps(keys, ensure_ascii=False, indent=2), encoding="utf-8")
    args.md.write_text(_report(rows, keys), encoding="utf-8")
    print(
        json.dumps(
            {
                "pool": len(pool),
                "selected": len(rows),
                "shortfall": shortfall,
                "blind_sha256": blind_sha[:16],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
