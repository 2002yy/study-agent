from __future__ import annotations

import pytest

from src.rag import build_rag_index
from src.rag.eval import RagEvalCase, evaluate_case, evaluate_rag_index, load_eval_cases


FIXTURE_DIR = "tests/fixtures/rag_eval"


def test_load_eval_cases_from_json():
    cases = load_eval_cases(f"{FIXTURE_DIR}/cases.json")

    assert len(cases) == 3
    assert cases[0].query == "requests sessions reuse connections"
    assert cases[0].expected_sources == ("python_requests.md",)
    assert cases[0].retrieval_mode == "hybrid"


def test_evaluate_rag_index_reports_quality_metrics():
    index = build_rag_index(
        [
            f"{FIXTURE_DIR}/python_requests.md",
            f"{FIXTURE_DIR}/memory_routing.md",
            f"{FIXTURE_DIR}/news_pipeline.md",
        ],
        max_chars=500,
        overlap_chars=0,
    )
    cases = load_eval_cases(f"{FIXTURE_DIR}/cases.json")

    summary = evaluate_rag_index(index, cases)

    assert summary.total_cases == 3
    assert summary.source_hit_rate == 1.0
    assert summary.mean_recall_at_k == 1.0
    assert summary.mean_reciprocal_rank == 1.0
    assert summary.empty_result_rate == 0.0
    assert all(result.hit for result in summary.results)


def test_evaluate_case_tracks_misses_and_empty_results():
    index = build_rag_index([f"{FIXTURE_DIR}/python_requests.md"], max_chars=500, overlap_chars=0)
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
    assert result.reciprocal_rank == 0.0
    assert result.recall_at_k == 0.0


def test_load_eval_cases_requires_expected_sources(tmp_path):
    path = tmp_path / "bad_cases.json"
    path.write_text('{"cases": [{"query": "missing source"}]}', encoding="utf-8")

    with pytest.raises(ValueError, match="expected_sources"):
        load_eval_cases(path)


def test_evaluate_case_rejects_unknown_retrieval_mode():
    index = build_rag_index([f"{FIXTURE_DIR}/python_requests.md"], max_chars=500, overlap_chars=0)
    case = RagEvalCase(
        query="requests",
        expected_sources=("python_requests.md",),
        retrieval_mode="semantic",
    )

    with pytest.raises(ValueError, match="Unsupported RAG retrieval mode"):
        evaluate_case(index, case)
