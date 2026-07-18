from __future__ import annotations

import pytest

from src.rag import build_rag_index
from src.rag.eval import (
    RagEvalCase,
    evaluate_case,
    evaluate_rag_index,
    evaluate_retrieval_profiles,
    load_eval_cases,
)


FIXTURE_DIR = "tests/fixtures/rag_eval"
FIXTURE_DOCS = (
    "python_requests.md",
    "memory_routing.md",
    "news_pipeline.md",
    "fastapi_rag_runs.md",
    "frontend_workspace.md",
    "chinese_vector.md",
    "http_client_pooling.md",
    "memory_routing_legacy.md",
    "rag_upload_rebuild.md",
    "frontend_legacy_sidebar.md",
    "citation_policy.md",
    "learning_recovery.md",
)


def _build_quality_index():
    return build_rag_index(
        [f"{FIXTURE_DIR}/{name}" for name in FIXTURE_DOCS],
        max_chars=700,
        overlap_chars=80,
    )


def test_load_eval_cases_from_json():
    cases = load_eval_cases(f"{FIXTURE_DIR}/cases.json")

    assert len(cases) == 30
    assert cases[0].case_id == "clean_requests_session"
    assert cases[0].expected_sources == ("python_requests.md",)
    assert cases[0].retrieval_mode == "hybrid"
    assert {case.scenario for case in cases} == {
        "clean",
        "paraphrase",
        "multi_source",
        "ambiguous_overlap",
        "stale_revision",
        "unanswerable",
    }
    assert sum(1 for case in cases if not case.answerable) == 4


def test_evaluate_rag_index_reports_quality_metrics_without_forcing_a_perfect_baseline():
    index = _build_quality_index()
    cases = load_eval_cases(f"{FIXTURE_DIR}/cases.json")

    summary = evaluate_rag_index(index, cases)

    assert summary.total_cases == 30
    assert summary.answerable_cases == 26
    assert summary.unanswerable_cases == 4
    assert len(summary.results) == 30
    assert set(summary.scenario_summaries) == {
        "clean",
        "paraphrase",
        "multi_source",
        "ambiguous_overlap",
        "stale_revision",
        "unanswerable",
    }
    for value in (
        summary.source_hit_rate,
        summary.mean_precision_at_k,
        summary.mean_recall_at_k,
        summary.mean_reciprocal_rank,
        summary.mean_ndcg_at_k,
        summary.empty_result_rate,
        summary.unanswerable_nonempty_rate,
        summary.forbidden_source_leakage_rate,
    ):
        assert 0.0 <= value <= 1.0
    assert summary.to_dict()["total_cases"] == 30


def test_evaluate_case_tracks_misses_and_empty_results():
    index = build_rag_index(
        [f"{FIXTURE_DIR}/python_requests.md"],
        max_chars=500,
        overlap_chars=0,
    )
    case = RagEvalCase(
        query="quantum banana vocabulary",
        expected_sources=("memory_routing.md",),
        expected_terms=("routing",),
        retrieval_mode="lexical",
        top_k=2,
    )

    result = evaluate_case(index, case)

    assert result.hit is False
    assert result.first_relevant_rank is None
    assert result.precision_at_k == 0.0
    assert result.reciprocal_rank == 0.0
    assert result.recall_at_k == 0.0
    assert result.ndcg_at_k == 0.0


def test_evaluate_case_reports_forbidden_source_leakage():
    index = build_rag_index(
        [
            f"{FIXTURE_DIR}/python_requests.md",
            f"{FIXTURE_DIR}/http_client_pooling.md",
        ],
        max_chars=1000,
        overlap_chars=0,
    )
    case = RagEvalCase(
        query="requests Session connection pool HTTP/2 DNS TLS",
        expected_sources=("python_requests.md",),
        forbidden_sources=("http_client_pooling.md",),
        retrieval_mode="lexical",
        top_k=2,
    )

    result = evaluate_case(index, case)

    assert result.hit is True
    assert result.forbidden_source_leakage is True
    assert any(source.endswith("http_client_pooling.md") for source in result.retrieved_forbidden_sources)
    assert result.precision_at_k == 0.5


def test_load_eval_cases_requires_expected_sources_for_answerable_cases(tmp_path):
    path = tmp_path / "bad_cases.json"
    path.write_text('{"cases": [{"query": "missing source"}]}', encoding="utf-8")

    with pytest.raises(ValueError, match="expected_sources"):
        load_eval_cases(path)


def test_load_eval_cases_allows_unanswerable_cases_without_expected_sources(tmp_path):
    path = tmp_path / "unanswerable.json"
    path.write_text(
        '{"cases": [{"id": "u1", "query": "unknown", "answerable": false}]}',
        encoding="utf-8",
    )

    cases = load_eval_cases(path)

    assert cases[0].case_id == "u1"
    assert cases[0].answerable is False
    assert cases[0].expected_sources == ()


def test_evaluate_case_rejects_unknown_retrieval_mode():
    index = build_rag_index(
        [f"{FIXTURE_DIR}/python_requests.md"],
        max_chars=500,
        overlap_chars=0,
    )
    case = RagEvalCase(
        query="requests",
        expected_sources=("python_requests.md",),
        retrieval_mode="semantic",
    )

    with pytest.raises(ValueError, match="Unsupported RAG retrieval mode"):
        evaluate_case(index, case)


def test_evaluate_retrieval_profiles_compares_same_quality_corpus():
    index = _build_quality_index()
    cases = load_eval_cases(f"{FIXTURE_DIR}/cases.json")

    summaries = evaluate_retrieval_profiles(index, cases)

    assert set(summaries) == {"lexical", "vector", "hybrid", "hybrid_reranked"}
    assert all(summary.total_cases == 30 for summary in summaries.values())
    assert all(summary.answerable_cases == 26 for summary in summaries.values())
    assert all("stale_revision" in summary.scenario_summaries for summary in summaries.values())
    assert summaries["hybrid"].to_dict()["mean_ndcg_at_k"] == summaries["hybrid"].mean_ndcg_at_k
