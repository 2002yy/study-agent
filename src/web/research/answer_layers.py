"""Layered answer contract: publish each statement at the strength its evidence allows.

The research pipeline used to decide the whole answer with one switch: if the
evidence gate was not satisfied, the model's reply was replaced by an abstention
sentence. That is honest but unhelpful - a reader gets nothing, even when a stable
part of the question could be answered.

This module is the per-statement version of that decision:

* ``knowledge``     - stable explanations and general advice. Allowed without a
                      source, but it may not be presented as verified or current.
* ``evidence``      - claims tied to a real read, with the existing field refs.
* ``conditional``   - "if A then B"; the premise is stated with the claim.
* ``unverified``    - specific facts we could not check. Never rendered as a
                      conclusion; listed in a closing gap section instead.

The important guard is :func:`claims_need_evidence`: a draft sentence that makes a
specific factual claim (a number, a version, a price, a date, "officially
confirmed", a screenshot value) can never be relabelled as knowledge. It either
has evidence or it is withheld - relabelling would be exactly the loophole this
contract exists to close.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

KNOWLEDGE = "knowledge"
EVIDENCE = "evidence"
CONDITIONAL = "conditional"
UNVERIFIED = "unverified"

PUBLISHED = "published"
WITHHELD = "withheld"

#: A closing gap section is only rendered when it has something to say.
GAP_HEADING = "本次未能核实"
KNOWLEDGE_PREFIX = "以下为一般性说明（未使用本次检索结果核实）："

_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%|百分之[一二三四五六七八九十百零\d]+")
_PRICE = re.compile(r"[¥￥$]\s*\d|\d+(?:\.\d+)?\s*(?:元|美元|CNY|USD)", re.IGNORECASE)
_VERSION = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b|最新版本|当前版本|版本号")
_DATE = re.compile(r"\b20\d{2}\s*年|\b20\d{2}-\d{1,2}(?:-\d{1,2})?\b")
_OFFICIAL_CLAIM = re.compile(
    r"官方(?:已|已经)?(?:确认|公布|宣布|声明)|据官方|官方数据|官方售价|官方定价"
)
_COMPARISON = re.compile(r"快了?\s*\d|比[^，。；]{0,12}(?:快|慢|高|低)\s*\d")
_SCREENSHOT_CLAIM = re.compile(r"图中|截图(?:中|里|显示)|画面中(?:显示|可见)")
_CONDITIONAL = re.compile(r"^(?:如果|若|假如|假设|一旦)[^，。]{0,40}(?:，|,|则|那么)")
#: Saying "we could not verify the current version" is an honest gap statement,
#: not an unsupported claim: the uncertainty is explicit in the sentence itself.
_UNCERTAINTY = re.compile(
    r"尚未核实|未核实|无法核实|无法确认|尚未确认|不能确认|不确定|未见确切|暂无(?:可靠)?(?:来源|数据)"
)

#: A knowledge statement may not be longer than this: it is an opening
#: orientation, not a second research report.
MAX_KNOWLEDGE_CHARS = 700

SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])\s*")


@dataclass(frozen=True)
class AnswerSegment:
    kind: str
    text: str
    decision: str
    reason: str = ""
    condition: str = ""
    source_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "decision": self.decision,
            "reason": self.reason,
            "condition": self.condition,
            "source_refs": list(self.source_refs),
        }


@dataclass(frozen=True)
class LayeredAnswer:
    text: str
    segments: tuple[AnswerSegment, ...] = ()
    withheld: tuple[AnswerSegment, ...] = ()
    gaps: tuple[str, ...] = ()
    knowledge_published: bool = False

    def audit(self) -> dict[str, Any]:
        return {
            "schema_version": "layered-answer-v1",
            "segments": [segment.to_dict() for segment in self.segments],
            "withheld": [segment.to_dict() for segment in self.withheld],
            "gaps": list(self.gaps),
            "knowledge_published": self.knowledge_published,
        }


def claims_need_evidence(text: str) -> str:
    """Return the reason a sentence may not be published as knowledge.

    An empty string means the sentence only states a stable idea. Everything else
    is a specific factual claim: it needs a real read, or it is withheld.
    """

    body = str(text or "").strip()
    if not body:
        return "empty"
    if _UNCERTAINTY.search(body):
        # The statement is about the gap itself, so it is publishable as-is.
        return ""
    if _PERCENT.search(body):
        return "specific_number"
    if _PRICE.search(body):
        return "specific_price"
    if _DATE.search(body):
        return "specific_date"
    if _VERSION.search(body):
        return "specific_version"
    if _COMPARISON.search(body):
        return "specific_comparison"
    if _OFFICIAL_CLAIM.search(body):
        return "official_claim"
    if _SCREENSHOT_CLAIM.search(body):
        return "screenshot_claim"
    return ""


def split_sentences(draft: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT.split(str(draft or "")) if part.strip()]


def classify_draft(
    draft: str,
    *,
    attachment_present: bool = False,
    screenshot_read: bool = True,
) -> tuple[list[AnswerSegment], list[AnswerSegment]]:
    """Split a free-text draft into publishable and withheld segments.

    ``attachment_present`` with ``screenshot_read=False`` means the reader gave us
    an image we never decoded: no statement may imply we saw it.
    """

    published: list[AnswerSegment] = []
    withheld: list[AnswerSegment] = []
    for sentence in split_sentences(draft):
        reason = claims_need_evidence(sentence)
        if attachment_present and not screenshot_read:
            if reason == "screenshot_claim" or _SCREENSHOT_CLAIM.search(sentence):
                withheld.append(
                    AnswerSegment(
                        kind=UNVERIFIED,
                        text=sentence,
                        decision=WITHHELD,
                        reason="attachment_not_read",
                    )
                )
                continue
        if reason:
            withheld.append(
                AnswerSegment(kind=UNVERIFIED, text=sentence, decision=WITHHELD, reason=reason)
            )
            continue
        if _CONDITIONAL.search(sentence):
            premise = sentence.split("，")[0].split(",")[0]
            published.append(
                AnswerSegment(
                    kind=CONDITIONAL,
                    text=sentence,
                    decision=PUBLISHED,
                    condition=premise[:80],
                )
            )
            continue
        published.append(AnswerSegment(kind=KNOWLEDGE, text=sentence, decision=PUBLISHED))
    return published, withheld


def compose(
    published: Sequence[AnswerSegment],
    withheld: Sequence[AnswerSegment],
    *,
    gaps: Iterable[str] = (),
    evidence_lines: Sequence[str] = (),
) -> LayeredAnswer:
    """Render the user-facing text: knowledge, evidence, then the gaps."""

    knowledge_text = "".join(segment.text for segment in published).strip()
    if len(knowledge_text) > MAX_KNOWLEDGE_CHARS:
        knowledge_text = knowledge_text[:MAX_KNOWLEDGE_CHARS].rstrip() + "…"
    blocks: list[str] = []
    if evidence_lines:
        blocks.append("\n".join(evidence_lines))
    if knowledge_text:
        blocks.append(f"{KNOWLEDGE_PREFIX}\n{knowledge_text}")
    gap_items = [str(item).strip() for item in gaps if str(item).strip()]
    if gap_items:
        blocks.append(GAP_HEADING + "：\n" + "\n".join(f"- {item}" for item in gap_items))
    return LayeredAnswer(
        text="\n\n".join(blocks).strip(),
        segments=tuple(published),
        withheld=tuple(withheld),
        gaps=tuple(gap_items),
        knowledge_published=bool(knowledge_text),
    )


def strict_publication_requested(user_message: str) -> bool:
    """The reader asked for verified statements only.

    The wording is intentionally narrow: this is the one case where the old
    all-or-nothing behaviour is the correct behaviour.
    """

    body = str(user_message or "")
    markers = (
        "只给已证实",
        "只要已证实",
        "只提供已证实",
        "只要证实过",
        "必须有官方来源",
        "必须注明来源",
        "不要推测",
        "不要猜测",
        "只依据来源",
        "只引用来源",
    )
    return any(marker in body for marker in markers)
