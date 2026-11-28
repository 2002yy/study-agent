"""Degraded delivery for research turns whose verification did not finish.

The publication gate runs *after* the expensive part of a research turn: pages
were fetched and read, and an answer was generated. A quality, budget, or
runtime failure in the gate must not erase that work. This module composes the
learner-facing degraded surface and the structured record that explains it.

It never widens a safety decision. Private, credentialed, or malformed URLs are
filtered before they reach this module; the caller keeps ownership of that
policy.

Three labels are used, deliberately distinct:

* ``【部分结论尚未核实】`` -- some text is published, some is not verified.
* ``【未完整核实的研究草稿】`` -- the whole candidate is an unverified draft.
* ``【研究未完成，已保留已读来源】`` -- no usable candidate; only read sources.

A degraded answer is never presented as a verified one: the structured
``research_delivery`` record carries ``verified: False`` and the reason class.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Mapping, Sequence

PARTIAL_HEADING = "【部分结论尚未核实】"
DRAFT_HEADING = "【未完整核实的研究草稿】"
NO_ANSWER_HEADING = "【研究未完成，已保留已读来源】"

DELIVERY_SCHEMA = "research-delivery-v1"

#: reason code -> (class, learner-facing sentence)
_REASON_COPY: dict[str, tuple[str, str]] = {
    "budget_exhausted": ("budget", "本轮可用于核验的模型调用次数已用尽"),
    "answer_verification_budget_exceeded": ("budget", "答案超出逐条核验的预算"),
    "missing_evidence_brief": ("runtime", "程序未能整理出本轮可核验的证据清单"),
    "candidate_unavailable": ("runtime", "模型没有返回可用的回答正文"),
    "producer_unavailable": ("runtime", "核验模型本次不可用"),
    "producer_failed": ("runtime", "核验模型调用失败"),
    "malformed_structured_output": ("runtime", "核验结果格式异常，无法解析"),
    "answer_not_segmentable": ("quality", "答案无法切分为可核验的段落"),
    "answer_fully_withheld": ("quality", "没有任何表述通过逐条核验"),
    "unbound_factual_claim": ("quality", "部分事实表述缺少可核实的依据"),
    "consistency_failed": ("quality", "答案与证据记录之间存在不一致"),
    "citation_outside_evidence": ("quality", "答案引用了本轮没有读取的页面"),
    "output_limit": ("truncation", "回答达到输出上限，结尾可能不完整"),
    "provider_blocked": ("truncation", "回答被服务方内容策略截断，可能不完整"),
    "generation_interrupted": ("runtime", "回答生成中断，可能不完整"),
}

_HEADINGS = (PARTIAL_HEADING, DRAFT_HEADING, NO_ANSWER_HEADING)


def reason_copy(code: str) -> tuple[str, str]:
    """Classify a gate reason without exposing internal identifiers.

    Binder reasons look like ``producer_failed:TimeoutError`` and consistency
    reasons like ``consistency_failed:unknown_evidence_ids``. Only the prefix is
    a known class; the suffix stays in the audit record.
    """

    prefix = str(code or "").split(":", 1)[0].strip()
    return _REASON_COPY.get(prefix, ("runtime", "后续核验未完成"))


def _strip_known_heading(text: str) -> str:
    body = str(text or "").lstrip()
    for heading in _HEADINGS:
        if body.startswith(heading):
            return body[len(heading):].lstrip("\n ")
    return body


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def withhold_blocks(text: str, needles: Iterable[str]) -> tuple[str, int]:
    """Drop Markdown blocks that contain an explicitly named bad statement.

    Used when the gate *can* locate the unsupported or contradictory statements
    (claim text, denial phrase, or an unremovable link). The rest of the answer
    survives. If nothing can be located, the caller keeps the whole draft and
    labels it unverified instead of guessing.
    """

    normalized = [
        _normalize_for_match(item) for item in needles if _normalize_for_match(item)
    ]
    if not normalized:
        return str(text or "").strip(), 0
    blocks = re.split(r"\n\s*\n", str(text or ""))
    kept: list[str] = []
    removed = 0
    for block in blocks:
        haystack = _normalize_for_match(block)
        if any(needle in haystack for needle in normalized):
            removed += 1
            continue
        kept.append(block)
    return "\n\n".join(part for part in kept if part.strip()).strip(), removed


def _source_lines(
    sources: Sequence[Mapping[str, str]], *, already_in: str = ""
) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for source in sources:
        url = str(source.get("url") or "").strip()
        title = str(source.get("title") or "").strip() or url
        if not url or url in seen or (already_in and url in already_in):
            continue
        seen.add(url)
        lines.append(f"- [{title}]({url})")
        if len(lines) >= 8:
            break
    return "\n".join(lines)


def compose_degraded_delivery(
    candidate: str,
    *,
    reason_code: str,
    sources: Sequence[Mapping[str, str]] = (),
    heading: str | None = None,
    extra_note: str = "",
    verified_subset: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Build the learner-facing degraded answer and its truthful record."""

    reason_class, reason_sentence = reason_copy(reason_code)
    body = _strip_known_heading(candidate)
    source_block = _source_lines(sources, already_in=body)
    delivered: list[dict[str, str]] = []
    seen_sources: set[str] = set()
    for item in sources:
        url = str(item.get("url") or "").strip()
        if not url or url in seen_sources:
            continue
        seen_sources.add(url)
        delivered.append(
            {"title": str(item.get("title") or ""), "url": url}
        )
        if len(delivered) >= 8:
            break

    if body.strip():
        label = heading or (PARTIAL_HEADING if verified_subset else DRAFT_HEADING)
        if verified_subset:
            note = (
                f"> 交付说明：{reason_sentence}。以上是本轮通过逐条核验的部分；"
                "其余内容未通过核验，未发布。"
            )
        else:
            note = (
                f"> 交付说明：{reason_sentence}。以上是模型生成的草稿，未通过完整核验；"
                "请把它当作待核实的材料，而不是已确认的事实。"
            )
        if extra_note:
            note += f" {extra_note}"
        parts = [label, "", body.rstrip()]
        if source_block:
            parts += ["", "**本轮实际读取的来源**", "", source_block]
        parts += ["", note]
        text = "\n".join(parts).strip()
        outcome = "verified_subset" if verified_subset else "draft"
    else:
        parts = [NO_ANSWER_HEADING, "", f"{reason_sentence}。"]
        if source_block:
            parts += [
                "",
                "本轮已经完成的检索和读取没有丢失，以下是实际读取的来源：",
                "",
                source_block,
                "",
                "你可以重试生成回答，或基于上面这些来源继续提问。",
            ]
        else:
            parts += [
                "",
                "本轮没有成功读取可引用的公开来源，因此没有可交付的研究内容。"
                "请重试，或换一种问法。",
            ]
        if extra_note:
            parts += ["", extra_note]
        text = "\n".join(parts).strip()
        outcome = "no_answer"

    record = {
        "schema_version": DELIVERY_SCHEMA,
        "outcome": outcome,
        "verified": False,
        "reason_code": str(reason_code or ""),
        "reason_class": reason_class,
        "reason_text": reason_sentence,
        "heading": text.splitlines()[0] if text else "",
        "source_count": len(delivered),
        "sources": delivered,
        "candidate_chars": len(str(candidate or "")),
        "candidate_sha256": hashlib.sha256(
            str(candidate or "").encode("utf-8")
        ).hexdigest(),
    }
    return text, record


def compose_generation_notice(
    text: str, *, reason_code: str
) -> tuple[str, dict[str, Any]]:
    """Keep a usable answer but disclose that generation stopped early."""

    reason_class, reason_sentence = reason_copy(reason_code)
    body = str(text or "").rstrip()
    note = f"> 生成状态：{reason_sentence}。可以要求继续补全。"
    published = f"{body}\n\n{note}" if body else note
    record = {
        "schema_version": DELIVERY_SCHEMA,
        "outcome": "partial",
        "verified": False,
        "reason_code": reason_code,
        "reason_class": reason_class,
        "reason_text": reason_sentence,
        "heading": "",
        "source_count": 0,
        "sources": [],
        "candidate_chars": len(body),
        "candidate_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    return published, record
