"""A2: locate candidate passages for each factual claim, inside saved reads.

A1 answers "does this passage exist?". This slice answers the prior question:
"which passage in what this run read is worth checking against this claim?".

It is deliberately recall-leaning but bounded. A deterministic locator cannot
know whether a passage actually answers the question - "revenue" and "R&D" both
appearing in a paragraph is a candidate, not support - so the floor below only
filters obvious noise, and every returned candidate is still handed to A3 for a
semantic verdict. Missing a paraphrase is recorded as a miss (``weak_overlap``
or ``no_overlap``) instead of being papered over with more keyword rules; the
miss rate is the metric this slice is judged by.

Nothing here carries authority:

* a candidate is built from one server-owned ``(evidence_id, ReadEvidence)``
  pair, so an id for page A can never be spliced onto page B's body;
* every candidate is re-checked by :func:`verify_claim_span` before it is
  returned, so an offset that drifted is dropped rather than published;
* the result has no ``supports``/``strength`` field and no way to grant it.

Zero model calls: the whole slice is deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from src.web.research.claim_span_provenance import (
    ClaimSpanVerification,
    verify_claim_span,
)
from src.web.research.read_evidence import ReadEvidence

#: Hard bounds. A claim gets a handful of candidates, and one batch cannot grow
#: without limit just because the answer has many segments.
MAX_CANDIDATES_PER_CLAIM = 3

#: The binder never hands over more than its own segment limit (16), so one
#: answer can produce at most 16 x 3 candidates. A smaller batch budget starves
#: the tail of a real answer: replaying the archived A/B answers showed 20 of 64
#: claims never even attempted at a budget of 12 (see
#: ``docs/research_quality/A2_LOCATION_REPLAY.md``).
MAX_TOTAL_CANDIDATES = MAX_CANDIDATES_PER_CLAIM * 16

#: A single 2-character CJK bigram is a topic mention ("利润" appears on most
#: earnings pages), not a locating signal. One anchor only counts when it is
#: this long (a Latin word, a number, or a longer phrase).
MIN_STRONG_ANCHOR_CHARS = 4

#: A very short sentence gives A3 nothing to judge, so it borrows its neighbour.
MIN_WINDOW_CHARS = 8

# Locating outcomes, recorded so misses are measurable rather than invisible.
REASON_EMPTY_CLAIM = "empty_claim"
REASON_NO_EVIDENCE = "no_evidence"
REASON_NO_OVERLAP = "no_overlap"
REASON_WEAK_OVERLAP = "weak_overlap"
REASON_TOTAL_CAP = "total_cap_reached"
REASON_REFUSED = "all_candidates_refused"

_BOUNDARY = re.compile(r"[。！？!?；;\n]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#._-]*")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "which",
        "why",
        "while",
        "with",
    }
)


@dataclass(frozen=True)
class ClaimToLocate:
    """One fact the answer states, produced upstream by answer segmentation."""

    claim_id: str
    text: str


@dataclass(frozen=True)
class EvidenceSource:
    """One server-owned source: the id the run published and the body it read.

    Binding them in a single value is the point: a locator that only knows an id
    set can attribute a genuine read of page B to page A's id.
    """

    evidence_id: str
    evidence: ReadEvidence


@dataclass(frozen=True)
class ClaimSpanLocation:
    """Where a claim was located, or why nothing was found."""

    claim_id: str
    claim_text: str
    candidates: tuple[ClaimSpanVerification, ...] = ()
    reason: str = ""
    anchor_count: int = 0

    @property
    def located(self) -> bool:
        return bool(self.candidates)


def locate_claim_spans(
    claims: Sequence[ClaimToLocate],
    *,
    sources: Sequence[EvidenceSource],
    max_candidates: int = MAX_CANDIDATES_PER_CLAIM,
    max_total: int = MAX_TOTAL_CANDIDATES,
) -> tuple[ClaimSpanLocation, ...]:
    """Return verified candidate passages for each claim, bounded and ordered."""

    per_claim = max(1, min(int(max_candidates), MAX_CANDIDATES_PER_CLAIM))
    total_cap = max(0, min(int(max_total), MAX_TOTAL_CANDIDATES))
    used = 0
    results: list[ClaimSpanLocation] = []
    for claim in claims:
        remaining = total_cap - used
        anchors = _anchors(claim.text)
        if not str(claim.text or "").strip():
            results.append(_empty(claim, len(anchors), REASON_EMPTY_CLAIM))
            continue
        if not sources:
            results.append(_empty(claim, len(anchors), REASON_NO_EVIDENCE))
            continue
        if remaining <= 0:
            results.append(_empty(claim, len(anchors), REASON_TOTAL_CAP))
            continue
        candidates, reason = _locate(
            claim,
            sources,
            anchors=anchors,
            limit=min(per_claim, remaining),
        )
        used += len(candidates)
        results.append(
            ClaimSpanLocation(
                claim_id=claim.claim_id,
                claim_text=claim.text,
                candidates=candidates,
                reason=reason,
                anchor_count=len(anchors),
            )
        )
    return tuple(results)


def _empty(
    claim: ClaimToLocate, anchor_count: int, reason: str
) -> ClaimSpanLocation:
    return ClaimSpanLocation(
        claim_id=claim.claim_id,
        claim_text=claim.text,
        candidates=(),
        reason=reason,
        anchor_count=anchor_count,
    )


def _locate(
    claim: ClaimToLocate,
    sources: Sequence[EvidenceSource],
    *,
    anchors: set[str],
    limit: int,
) -> tuple[tuple[ClaimSpanVerification, ...], str]:
    if not anchors:
        return (), REASON_EMPTY_CLAIM

    scored: list[tuple[float, int, EvidenceSource, int, int]] = []
    best_partial = 0
    for source in sources:
        excerpt = source.evidence.excerpt
        exact = _exact_span(claim.text, excerpt)
        if exact is not None:
            scored.append((float("inf"), len(claim.text), source, *exact))
            continue
        for start, end in _windows(excerpt):
            passage = excerpt[start:end]
            score, longest = _score(passage, anchors)
            if not score:
                continue
            best_partial = max(best_partial, score)
            if not _passes_floor(score, longest):
                continue
            scored.append((float(score), longest, source, start, end))

    if not scored:
        return (), (REASON_WEAK_OVERLAP if best_partial else REASON_NO_OVERLAP)

    scored.sort(
        key=lambda item: (-item[0], -item[1], item[3], item[2].evidence_id)
    )
    candidates: list[ClaimSpanVerification] = []
    texts: set[str] = set()
    for _score_value, _longest, source, start, end in scored:
        if len(candidates) >= limit:
            break
        passage = source.evidence.excerpt[start:end]
        key = _text_key(passage)
        if key in texts:
            continue
        verification = _verify(claim, source, start, end, passage)
        if not verification.verified:
            continue
        texts.add(key)
        candidates.append(verification)
    if not candidates:
        return (), REASON_REFUSED
    return tuple(candidates), ""


def _exact_span(claim_text: str, excerpt: str) -> tuple[int, int] | None:
    """A verbatim claim wins outright: no scoring can beat the source sentence."""

    needle = str(claim_text or "").strip()
    if len(needle) < 4:
        return None
    position = excerpt.find(needle)
    if position < 0:
        return None
    return position, position + len(needle)


def _windows(text: str) -> tuple[tuple[int, int], ...]:
    """Sentence spans, trimmed, with very short sentences widened."""

    raw: list[tuple[int, int]] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        raw.append((start, match.end()))
        start = match.end()
    if start < len(text):
        raw.append((start, len(text)))

    windows: list[tuple[int, int]] = []
    for index, (begin, end) in enumerate(raw):
        begin, end = _trim(text, begin, end)
        if not end > begin:
            continue
        if end - begin < MIN_WINDOW_CHARS:
            if index + 1 < len(raw):
                end = _trim(text, raw[index + 1][0], raw[index + 1][1])[1]
            elif index:
                begin = _trim(text, raw[index - 1][0], raw[index - 1][1])[0]
        windows.append((begin, end))
    return tuple(windows)


def _trim(text: str, begin: int, end: int) -> tuple[int, int]:
    while begin < end and text[begin].isspace():
        begin += 1
    while end > begin and text[end - 1].isspace():
        end -= 1
    return begin, end


def _anchors(claim_text: str) -> set[str]:
    """Claim content as CJK bigrams, Latin words and numbers."""

    found: set[str] = set()
    for match in _CJK_RUN.finditer(claim_text):
        run = match.group(0)
        if len(run) == 1:
            found.add(run)
        else:
            found.update(run[i : i + 2] for i in range(len(run) - 1))
    for match in _LATIN_WORD.finditer(claim_text):
        word = match.group(0).casefold()
        if len(word) >= 2 and word not in _STOPWORDS:
            found.add(word)
    for match in _NUMBER.finditer(claim_text):
        found.add(match.group(0))
    return found


def _score(passage: str, anchors: set[str]) -> tuple[int, int]:
    lowered = passage.casefold()
    matched = [anchor for anchor in anchors if anchor in lowered]
    longest = max((len(anchor) for anchor in matched), default=0)
    return len(matched), longest


def _passes_floor(score: int, longest: int) -> bool:
    if score >= 2:
        return True
    return score == 1 and longest >= MIN_STRONG_ANCHOR_CHARS


def _text_key(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _verify(
    claim: ClaimToLocate,
    source: EvidenceSource,
    start: int,
    end: int,
    passage: str,
) -> ClaimSpanVerification:
    record = source.evidence
    candidate = {
        "claim_id": claim.claim_id,
        "claim_text": claim.text,
        "evidence_id": source.evidence_id,
        "url": record.url,
        "read_id": record.read_id,
        "span_start": start,
        "span_end": end,
        "span_text": passage,
        "excerpt_sha256": record.content_sha256,
    }
    return verify_claim_span(
        candidate,
        evidence=[record],
        evidence_ids={source.evidence_id},
        evidence_urls={source.evidence_id: record.url},
    )

