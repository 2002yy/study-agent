"""A3: turn a verified passage plus a semantic verdict into support eligibility.

Stage B showed why this layer is the prerequisite: with only read rows, a
paraphrased answer cannot satisfy the binder's "cite a supporting row" rule, so
the model refuses the whole answer. Segmentation was never the bottleneck; the
missing piece is a server-owned qualification that says *this verified passage
was judged to support this claim*.

The split this module implements:

* **A1** proved the passage exists in a body the run read. That grants nothing.
* **here** a judgement is accepted only if it names a verified passage and its
  quoted evidence lies inside that passage. A contradiction outranks support,
  and support plus contradiction from verified passages is an unresolved
  conflict, not a conclusion.
* **the binder** still decides publication, from a row that carries no
  ``grounding_text`` - the trusted-upstream branch, reachable only for a claim
  that this module qualified.

Nothing here calls a model: verdicts arrive as data, and this module is the part
that decides what a verdict is allowed to buy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.web.research.claim_span_provenance import ClaimSpanVerification
from src.web.research.evidence_gate import STRONG_EVIDENCE_THRESHOLD

SUPPORTS = "supports"
CONTRADICTS = "contradicts"
INSUFFICIENT = "insufficient"
UNRESOLVED_CONFLICT = "unresolved_conflict"
VERDICTS = frozenset({SUPPORTS, CONTRADICTS, INSUFFICIENT})

#: Qualification reasons, so an audit can tell a missing judgement from a
#: judgement that quoted text the passage does not contain.
REASON_NO_VERIFIED_PASSAGE = "no_verified_passage"
REASON_NO_JUDGEMENT = "no_judgement"
REASON_UNKNOWN_PASSAGE = "unknown_passage"
REASON_EVIDENCE_OUTSIDE_PASSAGE = "evidence_outside_passage"
REASON_INVALID_VERDICT = "invalid_verdict"
REASON_OTHER_CLAIM = "other_claim"
REASON_LOW_WINDOW = "low_window"  # kept for callers that pre-filter

#: A qualified support is strong enough for publication, and deliberately not
#: maximal: the server verified a passage and a judgement, not the claim's truth.
QUALIFIED_STRENGTH = f"{STRONG_EVIDENCE_THRESHOLD:.1f}"


@dataclass(frozen=True)
class ClaimJudgement:
    """One model verdict about one verified passage (untrusted input)."""

    claim_id: str
    passage_key: str
    verdict: str
    evidence_span: str = ""
    reason: str = ""

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ClaimJudgement":
        return cls(
            claim_id=str(raw.get("claim_id") or "").strip(),
            passage_key=str(raw.get("passage_key") or raw.get("candidate_id") or "").strip(),
            verdict=str(raw.get("verdict") or "").strip().lower(),
            evidence_span=str(raw.get("evidence_span") or ""),
            reason=str(raw.get("reason") or "")[:300],
        )


@dataclass(frozen=True)
class QualifiedSupport:
    """A support the server is willing to hand to the binder."""

    claim_id: str
    evidence_id: str
    read_id: str
    url: str
    locator: str
    anchored_spans: tuple[str, ...]
    strength: str = QUALIFIED_STRENGTH
    verdict: str = SUPPORTS

    def as_binding_row(self, *, title: str = "") -> dict[str, Any]:
        """The row shape the binder's trusted-upstream branch expects.

        ``grounding_text`` is empty on purpose: this row's eligibility comes from
        the qualification record above, not from a literal sentence match.
        """

        return {
            "evidence_id": self.evidence_id,
            "claim_id": self.claim_id,
            "title": title,
            "url": self.url,
            "relation": SUPPORTS,
            "strength": self.strength,
            "locator": self.locator,
            "anchored_spans": list(self.anchored_spans),
            "grounding_text": "",
        }


@dataclass(frozen=True)
class ClaimSupportDecision:
    claim_id: str
    verdict: str
    publishable: bool
    qualified: tuple[QualifiedSupport, ...] = ()
    refused: tuple[dict[str, str], ...] = field(default_factory=tuple)
    reason: str = ""


def passage_key(candidate: ClaimSpanVerification) -> str:
    span = candidate.span
    return f"{span.read_id}:{span.span_start}-{span.span_end}"


def decide_claim_support(
    claim_id: str,
    *,
    candidates: Sequence[ClaimSpanVerification],
    judgements: Iterable[ClaimJudgement | Mapping[str, Any]],
) -> ClaimSupportDecision:
    """Decide what one claim's verified passages and verdicts are allowed to buy.

    Only ``supports`` verdicts whose quoted evidence lies inside a verified
    passage, and with no contradiction anywhere in the claim, produce a row.
    """

    verified = {
        passage_key(candidate): candidate
        for candidate in candidates
        if candidate.verified and candidate.locator
    }
    if not verified:
        return ClaimSupportDecision(
            claim_id=claim_id,
            verdict=INSUFFICIENT,
            publishable=False,
            reason=REASON_NO_VERIFIED_PASSAGE,
        )

    supports: dict[str, QualifiedSupport] = {}
    contradictions: list[dict[str, str]] = []
    refused: list[dict[str, str]] = []
    for raw in judgements:
        judgement = (
            raw if isinstance(raw, ClaimJudgement) else ClaimJudgement.from_mapping(raw)
        )
        if judgement.claim_id and judgement.claim_id != claim_id:
            refused.append(
                {
                    "passage": judgement.passage_key,
                    "verdict": judgement.verdict,
                    "reason": REASON_OTHER_CLAIM,
                }
            )
            continue
        candidate = verified.get(judgement.passage_key)
        if candidate is None:
            refused.append(
                {
                    "passage": judgement.passage_key,
                    "verdict": judgement.verdict,
                    "reason": REASON_UNKNOWN_PASSAGE,
                }
            )
            continue
        if judgement.verdict not in VERDICTS:
            refused.append(
                {
                    "passage": judgement.passage_key,
                    "verdict": judgement.verdict,
                    "reason": REASON_INVALID_VERDICT,
                }
            )
            continue
        if not _span_inside(judgement.evidence_span, candidate.span.span_text):
            refused.append(
                {
                    "passage": judgement.passage_key,
                    "verdict": judgement.verdict,
                    "reason": REASON_EVIDENCE_OUTSIDE_PASSAGE,
                }
            )
            continue
        if judgement.verdict == CONTRADICTS:
            contradictions.append(
                {
                    "passage": judgement.passage_key,
                    "evidence_id": candidate.span.evidence_id,
                    "text": _normalize(judgement.evidence_span),
                }
            )
            continue
        if judgement.verdict == SUPPORTS:
            support = _support(candidate, judgement.evidence_span)
            supports.setdefault(support.locator, support)

    if contradictions:
        # Contradiction outranks support: a verified denial blocks publication,
        # and support plus contradiction is an unresolved conflict rather than a
        # conclusion the answer may state.
        verdict = UNRESOLVED_CONFLICT if supports else CONTRADICTS
        return ClaimSupportDecision(
            claim_id=claim_id,
            verdict=verdict,
            publishable=False,
            refused=tuple(refused) + tuple(contradictions),
            reason="",
        )
    if not supports:
        return ClaimSupportDecision(
            claim_id=claim_id,
            verdict=INSUFFICIENT,
            publishable=False,
            refused=tuple(refused),
            reason=REASON_NO_JUDGEMENT if not refused else "",
        )
    return ClaimSupportDecision(
        claim_id=claim_id,
        verdict=SUPPORTS,
        publishable=True,
        qualified=tuple(supports.values()),
        refused=tuple(refused),
    )


def _support(
    candidate: ClaimSpanVerification, evidence_span: str
) -> QualifiedSupport:
    span = candidate.span
    return QualifiedSupport(
        claim_id=span.claim_id,
        evidence_id=span.evidence_id,
        read_id=span.read_id,
        url=span.url,
        locator=candidate.locator,
        anchored_spans=(_normalize(evidence_span),),
    )


def _span_inside(evidence_span: str, passage: str) -> bool:
    needle = _normalize(evidence_span)
    return bool(needle) and needle in _normalize(passage)


def _normalize(value: str) -> str:
    return " ".join(str(value or "").casefold().split())
