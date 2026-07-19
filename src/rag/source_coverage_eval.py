from __future__ import annotations

from src.rag.eval import (
    RagEvalCase,
    RagEvalResult,
    RagEvalSummary,
    _matched_expected_terms,
    _matches_expected_source,
    _ndcg_at_k,
    _source_matches,
    _summarize_results,
    _unique_sources,
)
from src.rag.schema import RagIndex
from src.rag.source_coverage import search_documents_with_adaptive_source_coverage


def evaluate_adaptive_source_coverage_case(
    index: RagIndex,
    case: RagEvalCase,
    *,
    min_score: float = 0.01,
) -> RagEvalResult:
    diagnostics = search_documents_with_adaptive_source_coverage(
        index,
        case.query,
        top_k=case.top_k,
        min_score=min_score,
        retrieval_mode=case.retrieval_mode,
        configured_max_chunks_per_source=case.max_chunks_per_source,
        reranker=case.reranker,
    )
    results = diagnostics.results
    retrieved_sources = tuple(result.chunk.source_path for result in results)
    matching_ranks = [
        rank
        for rank, source in enumerate(retrieved_sources, start=1)
        if _matches_expected_source(source, case.expected_sources)
    ]
    unique_retrieved = _unique_sources(retrieved_sources)
    matched_expected = {
        expected
        for expected in case.expected_sources
        if any(_source_matches(source, expected) for source in unique_retrieved)
    }
    matched_retrieved = {
        source
        for source in unique_retrieved
        if _matches_expected_source(source, case.expected_sources)
    }
    forbidden_retrieved = tuple(
        source
        for source in unique_retrieved
        if _matches_expected_source(source, case.forbidden_sources)
    )
    precision = (
        len(matched_retrieved) / len(unique_retrieved)
        if unique_retrieved and case.expected_sources
        else 0.0
    )
    recall = (
        len(matched_expected) / len(case.expected_sources)
        if case.expected_sources
        else 0.0
    )
    first_rank = min(matching_ranks) if matching_ranks else None
    reciprocal_rank = 1.0 / first_rank if first_rank else 0.0
    ndcg = _ndcg_at_k(retrieved_sources, case.expected_sources, case.top_k)

    return RagEvalResult(
        case=case,
        result_count=len(results),
        retrieved_sources=retrieved_sources,
        first_relevant_rank=first_rank,
        precision_at_k=round(precision, 6),
        recall_at_k=round(recall, 6),
        reciprocal_rank=round(reciprocal_rank, 6),
        ndcg_at_k=round(ndcg, 6),
        matched_expected_terms=_matched_expected_terms(results, case.expected_terms),
        retrieved_forbidden_sources=forbidden_retrieved,
    )


def evaluate_adaptive_source_coverage(
    index: RagIndex,
    cases: tuple[RagEvalCase, ...],
    *,
    min_score: float = 0.01,
) -> RagEvalSummary:
    return _summarize_results(
        tuple(
            evaluate_adaptive_source_coverage_case(index, case, min_score=min_score)
            for case in cases
        )
    )
