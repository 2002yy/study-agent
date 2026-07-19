from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Literal

from src.rag.index import _document_frequency, _tokenize
from src.rag.schema import RagIndex, RagSearchResult

EvidenceSufficiencyStatus = Literal["supported", "uncertain", "insufficient"]

_ENGLISH_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "before",
        "both",
        "by",
        "can",
        "current",
        "did",
        "do",
        "does",
        "during",
        "exact",
        "for",
        "from",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "later",
        "me",
        "of",
        "on",
        "or",
        "our",
        "should",
        "so",
        "still",
        "the",
        "their",
        "them",
        "then",
        "this",
        "to",
        "use",
        "used",
        "uses",
        "using",
        "what",
        "when",
        "where",
        "which",
        "why",
        "with",
        "without",
        "would",
        "you",
        "your",
        # Product name is usually routing context, not the fact being asked for.
        "study",
        "agent",
    }
)

_HARD_ANCHOR_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Z][A-Z0-9+_.-]{1,})(?![A-Za-z0-9])"
)


@dataclass(frozen=True)
class EvidenceSufficiencyDecision:
    status: EvidenceSufficiencyStatus
    reason: str
    query_terms: tuple[str, ...]
    covered_terms: tuple[str, ...]
    missing_terms: tuple[str, ...]
    absent_from_corpus_terms: tuple[str, ...]
    hard_anchor_terms: tuple[str, ...]
    missing_hard_anchor_terms: tuple[str, ...]
    weighted_coverage: float
    absent_weight_ratio: float
    distinctive_coverage: float
    result_count: int
    distinct_source_count: int
    top_score: float

    @property
    def allows_grounded_answer(self) -> bool:
        return self.status == "supported"

    def to_dict(self) -> dict:
        return asdict(self)


def _is_cjk(token: str) -> bool:
    return bool(re.fullmatch(r"[\u4e00-\u9fff]+", token))


def informative_query_terms(query: str) -> tuple[str, ...]:
    """Return stable, non-boilerplate terms used for evidence sufficiency checks.

    The base tokenizer emits both a full contiguous CJK span and its bigrams. The
    full sentence-like span would look absent from almost every document, so the
    sufficiency contract keeps CJK bigrams and discards longer duplicate spans.
    """
    terms: list[str] = []
    seen: set[str] = set()
    for token in _tokenize(query):
        normalized = token.casefold()
        if normalized in _ENGLISH_STOPWORDS:
            continue
        if _is_cjk(normalized) and len(normalized) > 2:
            continue
        if not _is_cjk(normalized) and len(normalized) < 2:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
    return tuple(terms)


def explicit_hard_anchor_terms(query: str) -> tuple[str, ...]:
    """Extract explicit acronym-like concepts whose absence is high-confidence evidence.

    Examples include GPU, OCR and CUDA. Ordinary title-case words and paraphrase
    verbs are intentionally not treated as hard blockers.
    """
    seen: set[str] = set()
    anchors: list[str] = []
    for match in _HARD_ANCHOR_RE.finditer(query):
        anchor = match.group(1).casefold()
        if anchor in seen:
            continue
        seen.add(anchor)
        anchors.append(anchor)
    return tuple(anchors)


def _idf(total_chunks: int, document_frequency: int) -> float:
    return math.log(
        1.0 + (total_chunks - document_frequency + 0.5) / (document_frequency + 0.5)
    )


def assess_evidence_sufficiency(
    index: RagIndex,
    query: str,
    results: list[RagSearchResult],
) -> EvidenceSufficiencyDecision:
    query_terms = informative_query_terms(query)
    hard_anchor_terms = explicit_hard_anchor_terms(query)
    distinct_sources = {
        result.chunk.document_id or result.chunk.source_path for result in results
    }
    top_score = max((result.score for result in results), default=0.0)
    if not results:
        return EvidenceSufficiencyDecision(
            status="insufficient",
            reason="no_retrieval_results",
            query_terms=query_terms,
            covered_terms=(),
            missing_terms=query_terms,
            absent_from_corpus_terms=(),
            hard_anchor_terms=hard_anchor_terms,
            missing_hard_anchor_terms=hard_anchor_terms,
            weighted_coverage=0.0,
            absent_weight_ratio=0.0,
            distinctive_coverage=0.0,
            result_count=0,
            distinct_source_count=0,
            top_score=0.0,
        )
    if not query_terms:
        return EvidenceSufficiencyDecision(
            status="uncertain",
            reason="no_informative_query_terms",
            query_terms=(),
            covered_terms=(),
            missing_terms=(),
            absent_from_corpus_terms=(),
            hard_anchor_terms=hard_anchor_terms,
            missing_hard_anchor_terms=hard_anchor_terms,
            weighted_coverage=0.0,
            absent_weight_ratio=0.0,
            distinctive_coverage=0.0,
            result_count=len(results),
            distinct_source_count=len(distinct_sources),
            top_score=round(top_score, 6),
        )

    document_frequency = _document_frequency(index.chunks)
    total_chunks = max(1, len(index.chunks))
    result_terms = {
        term
        for result in results
        for term in _tokenize(f"{result.chunk.title}\n{result.chunk.text}")
    }
    weights = {
        term: _idf(total_chunks, document_frequency.get(term, 0))
        for term in query_terms
    }
    total_weight = sum(weights.values()) or 1.0
    covered = tuple(term for term in query_terms if term in result_terms)
    missing = tuple(term for term in query_terms if term not in result_terms)
    absent = tuple(term for term in query_terms if document_frequency.get(term, 0) == 0)
    missing_hard_anchors = tuple(
        term for term in hard_anchor_terms if document_frequency.get(term, 0) == 0
    )
    weighted_coverage = sum(weights[term] for term in covered) / total_weight
    absent_weight_ratio = sum(weights[term] for term in absent) / total_weight

    distinctive_terms = tuple(
        term
        for term in query_terms
        if document_frequency.get(term, 0) <= max(1, total_chunks // 5)
    )
    distinctive_covered = sum(1 for term in distinctive_terms if term in result_terms)
    distinctive_coverage = (
        distinctive_covered / len(distinctive_terms) if distinctive_terms else weighted_coverage
    )

    # Refusal is intentionally high precision. Ordinary paraphrase words may be
    # absent even when the underlying fact is covered, so only explicit acronym-
    # like anchors and near-zero total concept coverage are hard blockers.
    all_multiple_hard_anchors_missing = (
        len(hard_anchor_terms) >= 2
        and len(missing_hard_anchors) == len(hard_anchor_terms)
    )
    one_hard_anchor_missing_with_weak_coverage = (
        bool(missing_hard_anchors) and weighted_coverage < 0.25
    )
    near_zero_concept_coverage = (
        weighted_coverage < 0.10 and absent_weight_ratio >= 0.60
    )

    if all_multiple_hard_anchors_missing:
        status: EvidenceSufficiencyStatus = "insufficient"
        reason = "missing_explicit_anchor_concepts"
    elif one_hard_anchor_missing_with_weak_coverage:
        status = "insufficient"
        reason = "missing_explicit_anchor_with_weak_coverage"
    elif near_zero_concept_coverage:
        status = "insufficient"
        reason = "near_zero_query_concept_coverage"
    elif weighted_coverage < 0.10:
        status = "uncertain"
        reason = "very_low_query_concept_coverage"
    else:
        status = "supported"
        reason = "no_high_confidence_insufficiency_signal"

    return EvidenceSufficiencyDecision(
        status=status,
        reason=reason,
        query_terms=query_terms,
        covered_terms=covered,
        missing_terms=missing,
        absent_from_corpus_terms=absent,
        hard_anchor_terms=hard_anchor_terms,
        missing_hard_anchor_terms=missing_hard_anchors,
        weighted_coverage=round(weighted_coverage, 6),
        absent_weight_ratio=round(absent_weight_ratio, 6),
        distinctive_coverage=round(distinctive_coverage, 6),
        result_count=len(results),
        distinct_source_count=len(distinct_sources),
        top_score=round(top_score, 6),
    )
