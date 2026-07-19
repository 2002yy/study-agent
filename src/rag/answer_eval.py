from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.rag.eval import _source_matches


@dataclass(frozen=True)
class RagExpectedClaim:
    claim_id: str
    match_terms: tuple[str, ...]
    support_sources: tuple[str, ...]


@dataclass(frozen=True)
class RagAnswerEvalCase:
    case_id: str
    query: str
    answerable: bool
    expected_sources: tuple[str, ...]
    expected_claims: tuple[RagExpectedClaim, ...]
    forbidden_terms: tuple[str, ...] = ()
    forbidden_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class RagAnswerAssertion:
    text: str
    cited_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class RagAnswerCandidate:
    case_id: str
    answer: str
    cited_sources: tuple[str, ...] = ()
    refused: bool = False
    assertions: tuple[RagAnswerAssertion, ...] = ()


@dataclass(frozen=True)
class RagAnswerEvalResult:
    case: RagAnswerEvalCase
    candidate: RagAnswerCandidate
    answerability_correct: bool
    citation_precision: float
    citation_recall: float
    claim_coverage: float
    claim_support_rate: float
    groundedness: float
    source_diversity: float
    stale_revision_leakage: bool
    matched_claim_ids: tuple[str, ...]
    supported_claim_ids: tuple[str, ...]
    unsupported_assertions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case.case_id,
            "query": self.case.query,
            "answerable": self.case.answerable,
            "refused": self.candidate.refused,
            "answerability_correct": self.answerability_correct,
            "citation_precision": self.citation_precision,
            "citation_recall": self.citation_recall,
            "claim_coverage": self.claim_coverage,
            "claim_support_rate": self.claim_support_rate,
            "groundedness": self.groundedness,
            "source_diversity": self.source_diversity,
            "stale_revision_leakage": self.stale_revision_leakage,
            "matched_claim_ids": list(self.matched_claim_ids),
            "supported_claim_ids": list(self.supported_claim_ids),
            "unsupported_assertions": list(self.unsupported_assertions),
        }


@dataclass(frozen=True)
class RagAnswerEvalSummary:
    total_cases: int
    answerable_cases: int
    unanswerable_cases: int
    answerability_accuracy: float
    mean_citation_precision: float
    mean_citation_recall: float
    mean_claim_coverage: float
    mean_claim_support_rate: float
    mean_groundedness: float
    mean_source_diversity: float
    stale_revision_leakage_rate: float
    results: tuple[RagAnswerEvalResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "answerable_cases": self.answerable_cases,
            "unanswerable_cases": self.unanswerable_cases,
            "answerability_accuracy": self.answerability_accuracy,
            "mean_citation_precision": self.mean_citation_precision,
            "mean_citation_recall": self.mean_citation_recall,
            "mean_claim_coverage": self.mean_claim_coverage,
            "mean_claim_support_rate": self.mean_claim_support_rate,
            "mean_groundedness": self.mean_groundedness,
            "mean_source_diversity": self.mean_source_diversity,
            "stale_revision_leakage_rate": self.stale_revision_leakage_rate,
            "results": [result.to_dict() for result in self.results],
        }


def load_answer_eval_fixture(
    path: str | Path,
) -> tuple[tuple[RagAnswerEvalCase, ...], tuple[RagAnswerCandidate, ...]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_cases = data.get("cases")
    raw_candidates = data.get("candidates")
    if not isinstance(raw_cases, list) or not isinstance(raw_candidates, list):
        raise ValueError("RAG answer eval fixture requires 'cases' and 'candidates' lists")

    cases: list[RagAnswerEvalCase] = []
    for item in raw_cases:
        claims = tuple(
            RagExpectedClaim(
                claim_id=str(claim["id"]),
                match_terms=tuple(str(term) for term in claim.get("match_terms", ())),
                support_sources=tuple(
                    str(source) for source in claim.get("support_sources", ())
                ),
            )
            for claim in item.get("expected_claims", ())
        )
        cases.append(
            RagAnswerEvalCase(
                case_id=str(item["id"]),
                query=str(item["query"]),
                answerable=bool(item.get("answerable", True)),
                expected_sources=tuple(
                    str(source) for source in item.get("expected_sources", ())
                ),
                expected_claims=claims,
                forbidden_terms=tuple(
                    str(term) for term in item.get("forbidden_terms", ())
                ),
                forbidden_sources=tuple(
                    str(source) for source in item.get("forbidden_sources", ())
                ),
            )
        )

    candidates: list[RagAnswerCandidate] = []
    for item in raw_candidates:
        candidates.append(
            RagAnswerCandidate(
                case_id=str(item["case_id"]),
                answer=str(item.get("answer", "")),
                cited_sources=tuple(
                    str(source) for source in item.get("cited_sources", ())
                ),
                refused=bool(item.get("refused", False)),
                assertions=tuple(
                    RagAnswerAssertion(
                        text=str(assertion["text"]),
                        cited_sources=tuple(
                            str(source)
                            for source in assertion.get("cited_sources", ())
                        ),
                    )
                    for assertion in item.get("assertions", ())
                ),
            )
        )
    return tuple(cases), tuple(candidates)


def evaluate_answer_case(
    case: RagAnswerEvalCase,
    candidate: RagAnswerCandidate,
) -> RagAnswerEvalResult:
    if candidate.case_id != case.case_id:
        raise ValueError(
            f"Answer candidate {candidate.case_id!r} does not match case {case.case_id!r}"
        )

    cited_sources = _unique_sources(
        candidate.cited_sources
        + tuple(
            source
            for assertion in candidate.assertions
            for source in assertion.cited_sources
        )
    )
    relevant_citations = tuple(
        source
        for source in cited_sources
        if _matches_any_source(source, case.expected_sources)
    )
    matched_expected_sources = tuple(
        expected
        for expected in case.expected_sources
        if _matches_any_source(expected, cited_sources)
    )
    citation_precision = (
        len(relevant_citations) / len(cited_sources)
        if cited_sources
        else (1.0 if not case.expected_sources else 0.0)
    )
    citation_recall = (
        len(matched_expected_sources) / len(case.expected_sources)
        if case.expected_sources
        else 1.0
    )

    assertions = candidate.assertions or (
        (RagAnswerAssertion(text=candidate.answer, cited_sources=cited_sources),)
        if candidate.answer.strip()
        else ()
    )
    matched_claim_ids: set[str] = set()
    supported_claim_ids: set[str] = set()
    unsupported_assertions: list[str] = []

    for assertion in assertions:
        matched_claims = tuple(
            claim for claim in case.expected_claims if _claim_matches(assertion.text, claim)
        )
        if not matched_claims:
            if assertion.text.strip():
                unsupported_assertions.append(assertion.text)
            continue
        assertion_supported = False
        assertion_sources = assertion.cited_sources or cited_sources
        for claim in matched_claims:
            matched_claim_ids.add(claim.claim_id)
            if _sources_intersect(assertion_sources, claim.support_sources):
                supported_claim_ids.add(claim.claim_id)
                assertion_supported = True
        if not assertion_supported:
            unsupported_assertions.append(assertion.text)

    claim_coverage = (
        len(matched_claim_ids) / len(case.expected_claims)
        if case.expected_claims
        else 1.0
    )
    claim_support_rate = (
        len(supported_claim_ids) / len(matched_claim_ids)
        if matched_claim_ids
        else (1.0 if not case.expected_claims else 0.0)
    )
    supported_assertion_count = sum(
        1
        for assertion in assertions
        if _assertion_is_supported(assertion, case, cited_sources)
    )
    groundedness = (
        supported_assertion_count / len(assertions)
        if assertions
        else (1.0 if candidate.refused and not case.answerable else 0.0)
    )
    source_diversity = (
        len(matched_expected_sources) / len(case.expected_sources)
        if case.expected_sources
        else 1.0
    )
    stale_revision_leakage = _has_stale_leakage(case, candidate, cited_sources)
    answerability_correct = (
        (case.answerable and not candidate.refused)
        or (not case.answerable and candidate.refused)
    )

    return RagAnswerEvalResult(
        case=case,
        candidate=candidate,
        answerability_correct=answerability_correct,
        citation_precision=round(citation_precision, 6),
        citation_recall=round(citation_recall, 6),
        claim_coverage=round(claim_coverage, 6),
        claim_support_rate=round(claim_support_rate, 6),
        groundedness=round(groundedness, 6),
        source_diversity=round(source_diversity, 6),
        stale_revision_leakage=stale_revision_leakage,
        matched_claim_ids=tuple(sorted(matched_claim_ids)),
        supported_claim_ids=tuple(sorted(supported_claim_ids)),
        unsupported_assertions=tuple(unsupported_assertions),
    )


def evaluate_answer_suite(
    cases: tuple[RagAnswerEvalCase, ...],
    candidates: tuple[RagAnswerCandidate, ...],
) -> RagAnswerEvalSummary:
    candidate_by_id = {candidate.case_id: candidate for candidate in candidates}
    missing = [case.case_id for case in cases if case.case_id not in candidate_by_id]
    if missing:
        raise ValueError(f"Missing RAG answer candidates for: {', '.join(missing)}")
    results = tuple(
        evaluate_answer_case(case, candidate_by_id[case.case_id]) for case in cases
    )
    answerable_cases = sum(1 for case in cases if case.answerable)
    return RagAnswerEvalSummary(
        total_cases=len(results),
        answerable_cases=answerable_cases,
        unanswerable_cases=len(results) - answerable_cases,
        answerability_accuracy=_mean_bool(
            result.answerability_correct for result in results
        ),
        mean_citation_precision=_mean(
            result.citation_precision for result in results
        ),
        mean_citation_recall=_mean(result.citation_recall for result in results),
        mean_claim_coverage=_mean(result.claim_coverage for result in results),
        mean_claim_support_rate=_mean(
            result.claim_support_rate for result in results
        ),
        mean_groundedness=_mean(result.groundedness for result in results),
        mean_source_diversity=_mean(
            result.source_diversity for result in results
        ),
        stale_revision_leakage_rate=_mean_bool(
            result.stale_revision_leakage for result in results
        ),
        results=results,
    )


def _claim_matches(text: str, claim: RagExpectedClaim) -> bool:
    normalized = _normalize_text(text)
    return bool(claim.match_terms) and all(
        _normalize_text(term) in normalized for term in claim.match_terms
    )


def _assertion_is_supported(
    assertion: RagAnswerAssertion,
    case: RagAnswerEvalCase,
    fallback_sources: tuple[str, ...],
) -> bool:
    matched_claims = tuple(
        claim for claim in case.expected_claims if _claim_matches(assertion.text, claim)
    )
    if not matched_claims:
        return False
    sources = assertion.cited_sources or fallback_sources
    return any(
        _sources_intersect(sources, claim.support_sources) for claim in matched_claims
    )


def _has_stale_leakage(
    case: RagAnswerEvalCase,
    candidate: RagAnswerCandidate,
    cited_sources: tuple[str, ...],
) -> bool:
    normalized_answer = _normalize_text(candidate.answer)
    if any(_normalize_text(term) in normalized_answer for term in case.forbidden_terms):
        return True
    return any(
        _matches_any_source(source, case.forbidden_sources) for source in cited_sources
    )


def _sources_intersect(
    actual_sources: tuple[str, ...],
    expected_sources: tuple[str, ...],
) -> bool:
    return any(
        _source_matches(actual, expected)
        for actual in actual_sources
        for expected in expected_sources
    )


def _matches_any_source(source: str, expected_sources: tuple[str, ...]) -> bool:
    return any(_source_matches(source, expected) for expected in expected_sources)


def _unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for source in sources:
        normalized = source.replace("\\", "/")
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(source)
    return tuple(unique)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _mean(values: Iterable[float]) -> float:
    resolved = list(values)
    if not resolved:
        return 0.0
    return round(sum(resolved) / len(resolved), 6)


def _mean_bool(values: Iterable[bool]) -> float:
    resolved = list(values)
    if not resolved:
        return 0.0
    return round(sum(1 for value in resolved if value) / len(resolved), 6)
