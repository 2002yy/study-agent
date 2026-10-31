"""Zero-cost replay: how often can A2 locate a claim in the text the answer saw?

The archived answer A/B runs (``docs/research_quality/answer_ab``) store, for each
turn, the rendered ``source_block`` that was given to the answer model and the
answer it produced. Replaying A2 over that pair answers a narrow, checkable
question without any model call:

    for the claims this answer made, does the locator find a passage in the
    context the answer actually had?

Two segmentations are measured, because they answer different questions:

* **as-produced** - ``segment_answer_with_stats`` exactly as the binder calls it.
  Answers over its segment budget yield no claims at all, which is a real
  constraint on what A2 can ever receive.
* **chunked** - the same segmentation applied to blank-line blocks of the answer.
  This isolates the locator's capability from that ceiling.

What this is not:

* not support accuracy - a located passage is a candidate, and A3 must judge it;
* not recall against full pages - the body is the rendered block the writer saw;
* not a benchmark of the product - it is one slice measured on frozen data.

Run: ``PYTHONPATH=. python tools/a2_location_replay.py`` (writes JSON + Markdown).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.application.answer_claim_binder import segment_answer_with_stats
from src.web.research.claim_span_location import (
    MAX_CANDIDATES_PER_CLAIM,
    REASON_TOTAL_CAP,
    ClaimToLocate,
    EvidenceSource,
    locate_claim_spans,
)
from src.web.research.read_evidence import EXCERPT_CHARS, ReadEvidence

ROOT = Path("docs/research_quality/answer_ab")
JSON_OUT = Path("docs/research_quality/A2_LOCATION_REPLAY.json")
MD_OUT = Path("docs/research_quality/A2_LOCATION_REPLAY.md")

_READ_BLOCK = re.compile(r"^【已读取 (\d+)】(.+)$", re.M)
_CITATION = re.compile(r"\[web-\d+\]")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_MIN_CLAIM_CHARS = 8
_MAX_CHUNK_SEGMENTS = 16


@dataclass(frozen=True)
class ReadBlock:
    ordinal: int
    title: str
    url: str
    body: str


@dataclass
class TurnResult:
    file: str
    arm: str
    query: str
    claims: int = 0
    filtered: int = 0
    overflow: bool = False
    located: int = 0
    candidates: int = 0
    cap_hits: int = 0
    starved: int = 0
    numeric_claims: int = 0
    numeric_located: int = 0
    numeric_span_has_number: int = 0
    reasons: dict[str, int] = field(default_factory=dict)
    samples: list[dict[str, Any]] = field(default_factory=list)


def _read_blocks(source_block: str) -> tuple[ReadBlock, ...]:
    """Read-source bodies from the rendered block, in their published order."""

    matches = list(_READ_BLOCK.finditer(source_block))
    blocks: list[ReadBlock] = []
    for index, match in enumerate(matches):
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(source_block)
        )
        chunk = source_block[match.end() : end]
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        url = next((line for line in lines if line.startswith("http")), "")
        body = "\n".join(line for line in lines if line != url)
        if not url or not body:
            continue
        blocks.append(
            ReadBlock(
                ordinal=int(match.group(1)),
                title=match.group(2).strip(),
                url=url,
                body=body[:EXCERPT_CHARS],
            )
        )
    return tuple(blocks)


def _sources(blocks: Sequence[ReadBlock]) -> tuple[EvidenceSource, ...]:
    return tuple(
        EvidenceSource(
            evidence_id=f"read-{block.ordinal}",
            evidence=ReadEvidence.build(
                url=block.url,
                excerpt=block.body,
                read_id=f"replay-{block.ordinal}",
            ),
        )
        for block in blocks
    )


def _keep(segment: str) -> bool:
    text = _CITATION.sub("", segment).strip()
    if len(text) < _MIN_CLAIM_CHARS:
        return False
    if text.startswith("#") or text.startswith("|"):
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", text))


def _segments_of(chunk: str) -> tuple[tuple[str, ...], bool]:
    segments, stats = segment_answer_with_stats(chunk)
    return tuple(segments), bool(stats.get("segment_overflow"))


def _chunks(answer: str) -> tuple[str, ...]:
    """Blank-line blocks, split further when one block still overflows."""

    blocks = [block for block in re.split(r"\n\s*\n", answer) if block.strip()]
    bounded: list[str] = []
    for block in blocks:
        segments, overflow = _segments_of(block)
        if not overflow:
            bounded.append(block)
            continue
        lines = [line for line in block.splitlines() if line.strip()]
        bounded.extend("\n".join(lines[index : index + 8]) for index in range(0, len(lines), 8))
    return tuple(bounded)


def _claim_texts(answer: str, *, chunked: bool) -> tuple[tuple[str, ...], int, bool]:
    kept: list[str] = []
    filtered = 0
    overflow = False
    chunks = _chunks(answer) if chunked else (answer,)
    for chunk in chunks:
        segments, chunk_overflow = _segments_of(chunk)
        overflow = overflow or chunk_overflow
        for segment in segments:
            if _keep(segment):
                kept.append(_CITATION.sub("", segment).strip())
            else:
                filtered += 1
    return tuple(kept), filtered, overflow and not kept


def _play_turn(
    path: Path,
    arm: str,
    turn: dict[str, Any],
    *,
    chunked: bool,
) -> TurnResult | None:
    research = turn.get("research")
    research = research if isinstance(research, dict) else {}
    answer_field = turn.get("answer")
    answer = (
        str(answer_field.get("text") or "")
        if isinstance(answer_field, dict)
        else str(answer_field or "")
    )
    source_block = research.get("source_block") or ""
    if not answer or not source_block:
        return None
    blocks = _read_blocks(source_block)
    if not blocks:
        return None
    claims, filtered, overflow = _claim_texts(answer, chunked=chunked)
    result = TurnResult(
        file=path.name,
        arm=arm,
        query=str(turn.get("query") or ""),
        filtered=filtered,
        overflow=overflow,
    )
    if not claims:
        return result

    sources = _sources(blocks)
    targets = [
        ClaimToLocate(claim_id=f"c{index}", text=text)
        for index, text in enumerate(claims, 1)
    ]
    # Capability is measured per claim, so the per-claim limit applies and the
    # batch budget cannot starve the tail of a long answer.
    locations = tuple(
        locate_claim_spans(
            [target], sources=sources, max_total=MAX_CANDIDATES_PER_CLAIM
        )[0]
        for target in targets
    )
    # The production-style single batch is measured too: it shows how much of a
    # real answer a 12-candidate budget leaves unattempted.
    batch = locate_claim_spans(targets, sources=sources)
    result.starved = sum(
        1 for location in batch if location.reason == REASON_TOTAL_CAP
    )

    by_ordinal = {block.ordinal: block for block in blocks}
    for claim, location in zip(targets, locations, strict=True):
        result.claims += 1
        numbers = _NUMBER.findall(claim.text)
        if numbers:
            result.numeric_claims += 1
        if not location.located:
            result.reasons[location.reason] = result.reasons.get(location.reason, 0) + 1
            continue
        result.located += 1
        result.candidates += len(location.candidates)
        if len(location.candidates) >= MAX_CANDIDATES_PER_CLAIM:
            result.cap_hits += 1
        top = location.candidates[0]
        ordinal = int(top.span.evidence_id.split("-")[-1])
        block = by_ordinal.get(ordinal)
        if numbers:
            result.numeric_located += 1
            if all(number in top.span.span_text for number in numbers):
                result.numeric_span_has_number += 1
        if len(result.samples) < 2:
            result.samples.append(
                {
                    "claim": claim.text,
                    "span": top.span.span_text,
                    "source_title": block.title if block else "",
                    "candidate_count": len(location.candidates),
                }
            )
    return result


def _iter_turns(root: Path) -> Iterable[tuple[Path, str, dict[str, Any]]]:
    for path in sorted(root.glob("*_2026*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        arm = str(payload.get("arm") or payload.get("strategy") or "")
        for turn in payload.get("turns") or []:
            if isinstance(turn, dict):
                yield path, arm, turn


def _aggregate(results: Sequence[TurnResult]) -> dict[str, Any]:
    total: dict[str, Any] = {
        "turns": len(results),
        "answers_without_claims": sum(1 for r in results if not r.claims),
        "claims": sum(r.claims for r in results),
        "located": sum(r.located for r in results),
        "candidates": sum(r.candidates for r in results),
        "cap_hits": sum(r.cap_hits for r in results),
        "starved": sum(r.starved for r in results),
        "numeric_claims": sum(r.numeric_claims for r in results),
        "numeric_located": sum(r.numeric_located for r in results),
        "numeric_span_has_number": sum(r.numeric_span_has_number for r in results),
        "filtered": sum(r.filtered for r in results),
        "reasons": dict(
            sum((Counter(r.reasons) for r in results), Counter()).most_common()
        ),
    }
    claims = total["claims"] or 1
    located = total["located"] or 1
    numeric = total["numeric_claims"] or 1
    total["locatable_rate"] = round(total["located"] / claims, 3)
    total["numeric_located_rate"] = round(total["numeric_located"] / numeric, 3)
    total["numeric_number_in_span_rate"] = round(
        total["numeric_span_has_number"] / numeric, 3
    )
    total["candidates_per_located_claim"] = round(total["candidates"] / located, 2)
    return total


def _by_arm(results: Sequence[TurnResult]) -> dict[str, Any]:
    arms = sorted({r.arm for r in results})
    return {arm: _aggregate([r for r in results if r.arm == arm]) for arm in arms}


def _report(
    produced: Sequence[TurnResult],
    chunked: Sequence[TurnResult],
    overall: dict[str, Any],
    chunked_overall: dict[str, Any],
    arms: dict[str, Any],
) -> str:
    lines = [
        "# A2 定位回放（零成本）",
        "",
        "> 数据：`docs/research_quality/answer_ab` 已归档的真实 A/B 运行"
        "（20 轮、两臂）；",
        "> 对象：答案实际看到的 `source_block` 正文 + 该答案本身；",
        "> 费用：0（无任何模型调用）；",
        "> 重现：`PYTHONPATH=. python tools/a2_location_replay.py`。",
        "",
        "## 1. 这个数字是什么，不是什么",
        "",
        "- 是：**答案自己陈述的 claim，能否在它当时看到的上下文里定位到一段原文。**",
        "- 不是：支持判断准确率（A3 才做），也不是对整页正文的召回（块是展示口径）。",
        "- 因此它是 A2 的**下限**：定位不到的 claim，A3 连判断的机会都没有。",
        "",
        "## 2. 生产分段（binder 真实调用方式）",
        "",
        "| 指标 | 值 |",
        "| --- | ---: |",
        f"| 回放轮次 | {overall['turns']} |",
        f"| **整段无 claim 的答案**（分段预算溢出） | **{overall['answers_without_claims']}** |",
        f"| 参与定位的 claim | {overall['claims']} |",
        f"| 至少定位到 1 段 | {overall['located']}"
        f"（{overall['locatable_rate']:.1%}） |",
        f"| 候选总数 / 每条已定位平均 | {overall['candidates']} / "
        f"{overall['candidates_per_located_claim']} |",
        f"| 含数字 claim / 已定位 | {overall['numeric_claims']} / "
        f"{overall['numeric_located']}（{overall['numeric_located_rate']:.1%}） |",
        f"| 其中候选含全部数字 | {overall['numeric_span_has_number']}"
        f"（{overall['numeric_number_in_span_rate']:.1%}） |",
        f"| 默认单批预算下被饿死的 claim | {overall['starved']} |",
        "",
        "## 3. 分块回放（去掉 16 段上限，测定位器本身）",
        "",
        "| 指标 | 值 |",
        "| --- | ---: |",
        f"| 有 claim 的轮次 | {chunked_overall['turns'] - chunked_overall['answers_without_claims']}"
        f" / {chunked_overall['turns']} |",
        f"| claim 总数 | {chunked_overall['claims']} |",
        f"| 至少定位到 1 段 | {chunked_overall['located']}"
        f"（{chunked_overall['locatable_rate']:.1%}） |",
        f"| 候选总数 / 每条已定位平均 | {chunked_overall['candidates']} / "
        f"{chunked_overall['candidates_per_located_claim']} |",
        f"| 含数字 claim / 已定位 | {chunked_overall['numeric_claims']} / "
        f"{chunked_overall['numeric_located']}"
        f"（{chunked_overall['numeric_located_rate']:.1%}） |",
        f"| 其中候选含全部数字 | {chunked_overall['numeric_span_has_number']}"
        f"（{chunked_overall['numeric_number_in_span_rate']:.1%}） |",
        f"| 默认单批预算下被饿死的 claim | {chunked_overall['starved']} |",
        "",
        "漏检原因（分块口径）："
        + (
            "，".join(
                f"`{name}` {count}"
                for name, count in chunked_overall["reasons"].items()
            )
            or "无"
        ),
        "",
        "## 4. 分臂（分块口径）",
        "",
        "| 臂 | claim | 已定位 | 可定位率 | 候选/已定位 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for arm, stats in arms.items():
        lines.append(
            f"| {arm or '-'} | {stats['claims']} | {stats['located']} | "
            f"{stats['locatable_rate']:.1%} | {stats['candidates_per_located_claim']} |"
        )
    lines += [
        "",
        "## 5. 逐轮（分块口径）",
        "",
        "| 文件 | 臂 | 查询 | claim | 已定位 | 候选 | 漏检原因 |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for result in chunked:
        reasons = "，".join(f"{k}:{v}" for k, v in sorted(result.reasons.items()))
        lines.append(
            f"| {result.file} | {result.arm} | {result.query[:26]} | {result.claims} | "
            f"{result.located} | {result.candidates} | {reasons or '-'} |"
        )
    lines += [
        "",
        "## 6. 抽样（人工判断用）",
        "",
        "| claim | 定位到的原文片段 | 来源 | 候选数 |",
        "| --- | --- | --- | ---: |",
    ]
    for result in chunked:
        for sample in result.samples[:1]:
            lines.append(
                f"| {_cell(sample['claim'])} | {_cell(sample['span'])} | "
                f"{_cell(sample['source_title'])} | {sample['candidate_count']} |"
            )
    lines += [
        "",
        "## 7. 本轮测出的两个结构性问题",
        "",
        f"1. **分段上限吞掉整段答案**：{overall['answers_without_claims']}"
        f" / {overall['turns']} 轮答案的原始分段数超过 binder 的 16 段上限，"
        "`accepted=false`，因此这些回答在现有链路上拿不到任何 claim 级绑定；"
        "A2/A3 对它们完全没有输入。这是既有 binder 行为，不是 A2 的缺陷。",
        "2. **单批预算必须随 claim 数走**：把上限固定在 12 时，同一份回放里"
        "生产口径 20 / 64 条、分块口径 283 / 488 条 claim 因 `total_cap_reached` "
        "从未被尝试——长答案的尾部等于没做分析。默认值已改为 `16 x 3 = 48`"
        f"（binder 分段上限 × 每事实候选数），改后生产口径被饿死 "
        f"{overall['starved']} 条；分块口径仍有 {chunked_overall['starved']} 条，"
        "属于超出 binder 上限的场景，不是生产路径。",
        "",
        "## 8. 已知局限",
        "",
        "1. 正文是渲染后的 `source_block`（展示口径），比读取记录短，数字偏保守；",
        "2. claim 来自答案分段，不是人工标注的事实清单，长段落算一条；",
        "3. 候选“相关”不等于“支持”，本表不做任何支持判断；",
        "4. 抽样里可见噪声（如诺贝尔奖 claim 命中日历页），这正是 A3 必须存在的理由；",
        "5. 同义改写与跨语言 claim 的漏检如实计入 `no_overlap` / `weak_overlap`。",
        "",
    ]
    return "\n".join(lines)


def _cell(value: Any, limit: int = 58) -> str:
    text = " ".join(str(value or "").split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json-out", type=Path, default=JSON_OUT)
    parser.add_argument("--md-out", type=Path, default=MD_OUT)
    args = parser.parse_args(argv)

    produced = [
        result
        for path, arm, turn in _iter_turns(args.root)
        if (result := _play_turn(path, arm, turn, chunked=False)) is not None
    ]
    chunked = [
        result
        for path, arm, turn in _iter_turns(args.root)
        if (result := _play_turn(path, arm, turn, chunked=True)) is not None
    ]
    overall = _aggregate(produced)
    chunked_overall = _aggregate(chunked)

    args.json_out.write_text(
        json.dumps(
            {
                "produced": overall,
                "chunked": chunked_overall,
                "by_arm_chunked": _by_arm(chunked),
                "turns_chunked": [asdict(result) for result in chunked],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    args.md_out.write_text(
        _report(produced, chunked, overall, chunked_overall, _by_arm(chunked)),
        encoding="utf-8",
    )
    print(json.dumps({"produced": overall, "chunked": chunked_overall}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
