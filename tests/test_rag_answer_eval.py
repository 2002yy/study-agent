from __future__ import annotations

import pytest

from src.rag.answer_eval import (
    RagAnswerAssertion,
    RagAnswerCandidate,
    evaluate_answer_case,
    evaluate_answer_suite,
    load_answer_eval_fixture,
)


FIXTURE_PATH = "tests/fixtures/rag_eval/answer_cases.json"


def _case(case_id: str):
    cases, _ = load_answer_eval_fixture(FIXTURE_PATH)
    return next(case for case in cases if case.case_id == case_id)


def test_load_answer_eval_fixture_exposes_gold_cases_without_fake_model_outputs():
    cases, candidates = load_answer_eval_fixture(FIXTURE_PATH)

    assert len(cases) == 10
    assert candidates == ()
    assert sum(1 for case in cases if not case.answerable) == 2


def test_answer_eval_scores_supported_claims_and_citations():
    case = _case("clean_requests_session")
    candidate = RagAnswerCandidate(
        case_id=case.case_id,
        answer=(
            "A requests Session keeps a connection pool for reuse, while explicit timeout "
            "settings are still required."
        ),
        cited_sources=("python_requests.md",),
        assertions=(
            RagAnswerAssertion(
                text="A requests Session keeps a connection pool for reuse.",
                cited_sources=("python_requests.md",),
            ),
            RagAnswerAssertion(
                text="Explicit timeout settings are still required.",
                cited_sources=("python_requests.md",),
            ),
        ),
    )

    result = evaluate_answer_case(case, candidate)

    assert result.answerability_correct is True
    assert result.citation_precision == 1.0
    assert result.citation_recall == 1.0
    assert result.claim_coverage == 1.0
    assert result.claim_support_rate == 1.0
    assert result.groundedness == 1.0
    assert result.stale_revision_leakage is False


def test_answer_eval_penalizes_unsupported_assertions_without_hiding_supported_claims():
    case = _case("clean_requests_session")
    candidate = RagAnswerCandidate(
        case_id=case.case_id,
        answer="Session pooling helps reuse connections. A specific GPU is mandatory.",
        cited_sources=("python_requests.md",),
        assertions=(
            RagAnswerAssertion(
                text="A Session uses a connection pool.",
                cited_sources=("python_requests.md",),
            ),
            RagAnswerAssertion(
                text="A specific GPU is mandatory.",
                cited_sources=("python_requests.md",),
            ),
        ),
    )

    result = evaluate_answer_case(case, candidate)

    assert result.claim_coverage == 0.5
    assert result.claim_support_rate == 1.0
    assert result.groundedness == 0.5
    assert result.unsupported_assertions == ("A specific GPU is mandatory.",)


def test_answer_eval_detects_stale_revision_source_leakage():
    case = _case("stale_task_selector")
    candidate = RagAnswerCandidate(
        case_id=case.case_id,
        answer="The current UI stays automatic and uses an on-demand task chip.",
        cited_sources=("frontend_workspace.md", "frontend_legacy_sidebar.md"),
        assertions=(
            RagAnswerAssertion(
                text="The current task intent stays automatic.",
                cited_sources=("frontend_workspace.md",),
            ),
            RagAnswerAssertion(
                text="The learner can use an on-demand task chip.",
                cited_sources=("memory_routing.md",),
            ),
        ),
    )

    result = evaluate_answer_case(case, candidate)

    assert result.answerability_correct is True
    assert result.claim_coverage == 1.0
    assert result.stale_revision_leakage is True
    assert result.citation_precision < 1.0


def test_answer_eval_rewards_refusal_when_sources_cannot_establish_the_answer():
    case = _case("unanswerable_gpu")
    candidate = RagAnswerCandidate(
        case_id=case.case_id,
        answer="",
        refused=True,
    )

    result = evaluate_answer_case(case, candidate)

    assert result.answerability_correct is True
    assert result.citation_precision == 1.0
    assert result.citation_recall == 1.0
    assert result.claim_coverage == 1.0
    assert result.groundedness == 1.0


def test_answer_eval_suite_requires_one_candidate_per_case():
    cases, _ = load_answer_eval_fixture(FIXTURE_PATH)

    with pytest.raises(ValueError, match="Missing RAG answer candidates"):
        evaluate_answer_suite(cases, ())
