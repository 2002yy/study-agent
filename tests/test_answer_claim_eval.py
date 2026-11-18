from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.domain.answer_claims import answer_content_hash, deterministic_claim_id
from src.rag.answer_claim_eval import (
    AnswerClaimEvalCase,
    AnswerClaimExpectedClaim,
    AnswerClaimProducerInput,
    deterministic_gold_payload,
    evaluate_answer_claim_case,
    evaluate_answer_claim_suite,
    load_answer_claim_eval_cases,
    parse_answer_claim_producer_output,
    run_answer_claim_producer,
)


FIXTURE = Path("tests/fixtures/rag_eval/answer_cases.json")


def _two_claim_case() -> AnswerClaimEvalCase:
    return AnswerClaimEvalCase(
        case_id="two-claim-case",
        question="Explain alpha and beta.",
        answerable=True,
        expected_claims=(
            AnswerClaimExpectedClaim(
                claim_id="alpha",
                match_terms=("alpha",),
                kind="factual",
                support_evidence_ids=("a.md",),
            ),
            AnswerClaimExpectedClaim(
                claim_id="beta",
                match_terms=("beta",),
                kind="factual",
                support_evidence_ids=("b.md",),
            ),
        ),
        known_evidence_ids=("a.md", "b.md"),
        forbidden_claim_terms=("legacy",),
    )


def _claim_payload(
    *,
    final_answer: str,
    claims: list[tuple[str, str]],
    links: list[tuple[str, str]],
    refused: bool = False,
) -> dict:
    answer_hash = answer_content_hash(final_answer)
    claim_rows = []
    claim_ids: dict[str, str] = {}
    for key, text in claims:
        claim_id = deterministic_claim_id(answer_hash=answer_hash, claim_text=text)
        claim_ids[key] = claim_id
        claim_rows.append(
            {
                "id": claim_id,
                "text": text,
                "kind": "factual",
                "status": "asserted",
                "source": "application_supplied",
            }
        )
    return {
        "refused": refused,
        "claims": claim_rows,
        "claim_links": [
            {
                "claim_id": claim_ids[key],
                "evidence_id": evidence_id,
                "support_type": "direct_support",
                "confidence": 1.0,
            }
            for key, evidence_id in links
        ],
    }


def test_k1_answer_cases_project_into_versioned_claim_eval_cases():
    cases = load_answer_claim_eval_cases(FIXTURE)

    assert len(cases) == 10
    assert sum(1 for case in cases if case.answerable) == 8
    assert sum(1 for case in cases if not case.answerable) == 2
    assert cases[0].case_id == "clean_requests_session"
    assert cases[0].known_evidence_ids == ("python_requests.md",)
    assert all(claim.kind == "factual" for case in cases for claim in case.expected_claims)


def test_deterministic_gold_producer_proves_evaluator_can_score_perfect_contract():
    cases = load_answer_claim_eval_cases(FIXTURE)
    answers = {case.case_id: deterministic_gold_payload(case)[0] for case in cases}
    case_by_id = {case.case_id: case for case in cases}

    def produce_gold(request: AnswerClaimProducerInput) -> dict:
        expected_answer, payload = deterministic_gold_payload(case_by_id[request.case_id])
        assert request.final_answer == expected_answer
        return payload.to_dict()

    candidates = run_answer_claim_producer(
        cases=cases,
        answers=answers,
        producer=SimpleNamespace(
            producer_id="deterministic-gold-test",
            producer_version="v1",
            produce=produce_gold,
        ),
    )
    summary = evaluate_answer_claim_suite(cases, candidates)

    assert summary.total_cases == 10
    assert summary.schema_valid_cases == 10
    assert summary.schema_parse_rate == 1.0
    assert summary.answerability_accuracy == 1.0
    assert summary.mean_claim_precision == 1.0
    assert summary.mean_claim_recall == 1.0
    assert summary.mean_claim_f1 == 1.0
    assert summary.mean_kind_accuracy == 1.0
    assert summary.mean_claim_coverage == 1.0
    assert summary.mean_unsupported_claim_rate == 0.0
    assert summary.mean_link_precision == 1.0
    assert summary.mean_link_recall == 1.0
    assert summary.mean_link_f1 == 1.0
    assert summary.refusal_leakage_rate == 0.0
    assert summary.forbidden_claim_leakage_rate == 0.0
    assert summary.invalid_case_ids == ()


def test_malformed_output_is_invalid_and_receives_no_fabricated_quality_scores():
    case = _two_claim_case()
    candidate = parse_answer_claim_producer_output(
        case=case,
        final_answer="alpha beta",
        payload={"refused": False},
        producer_id="malformed-producer",
    )
    result = evaluate_answer_claim_case(case, candidate)

    assert result.schema_valid is False
    assert "claims" in result.parse_error
    assert result.answerability_correct is None
    assert result.claim_precision is None
    assert result.claim_recall is None
    assert result.link_precision is None
    assert result.refusal_leakage is None


def test_hallucinated_claim_reduces_precision_and_increases_unsupported_rate():
    case = _two_claim_case()
    final_answer = "alpha hallucinated"
    candidate = parse_answer_claim_producer_output(
        case=case,
        final_answer=final_answer,
        payload=_claim_payload(
            final_answer=final_answer,
            claims=[("alpha", "alpha"), ("hallucinated", "hallucinated")],
            links=[("alpha", "a.md")],
        ),
        producer_id="negative-fixture",
    )
    result = evaluate_answer_claim_case(case, candidate)

    assert result.schema_valid is True
    assert result.claim_precision == 0.5
    assert result.claim_recall == 0.5
    assert result.claim_f1 == 0.5
    assert result.claim_coverage == 0.5
    assert result.unsupported_claim_rate == 0.5
    assert result.unsupported_claim_texts == ("hallucinated",)
    assert result.missing_claim_ids == ("beta",)


def test_missing_claim_reduces_recall_without_penalizing_precision():
    case = _two_claim_case()
    final_answer = "alpha"
    candidate = parse_answer_claim_producer_output(
        case=case,
        final_answer=final_answer,
        payload=_claim_payload(
            final_answer=final_answer,
            claims=[("alpha", "alpha")],
            links=[("alpha", "a.md")],
        ),
        producer_id="negative-fixture",
    )
    result = evaluate_answer_claim_case(case, candidate)

    assert result.claim_precision == 1.0
    assert result.claim_recall == 0.5
    assert result.claim_f1 == 0.666667
    assert result.missing_claim_ids == ("beta",)


def test_wrong_but_known_evidence_link_reduces_link_precision_and_recall():
    case = _two_claim_case()
    final_answer = "alpha. beta"
    candidate = parse_answer_claim_producer_output(
        case=case,
        final_answer=final_answer,
        payload=_claim_payload(
            final_answer=final_answer,
            claims=[("alpha", "alpha"), ("beta", "beta")],
            links=[("alpha", "b.md"), ("beta", "b.md")],
        ),
        producer_id="negative-fixture",
    )
    result = evaluate_answer_claim_case(case, candidate)

    assert result.claim_recall == 1.0
    assert result.link_precision == 0.5
    assert result.link_recall == 0.5
    assert result.link_f1 == 0.5


def test_unknown_evidence_link_is_schema_invalid_instead_of_scored_as_complete():
    case = _two_claim_case()
    final_answer = "alpha"
    candidate = parse_answer_claim_producer_output(
        case=case,
        final_answer=final_answer,
        payload=_claim_payload(
            final_answer=final_answer,
            claims=[("alpha", "alpha")],
            links=[("alpha", "unknown.md")],
        ),
        producer_id="negative-fixture",
    )
    result = evaluate_answer_claim_case(case, candidate)

    assert result.schema_valid is False
    assert "unknown evidence id" in result.parse_error
    assert result.claim_f1 is None
    assert result.link_f1 is None


def test_unanswerable_case_flags_refusal_leakage_when_claims_are_emitted():
    case = AnswerClaimEvalCase(
        case_id="unanswerable",
        question="Unknown exact GPU?",
        answerable=False,
        expected_claims=(),
        known_evidence_ids=(),
    )
    final_answer = "The required GPU is Model X."
    candidate = parse_answer_claim_producer_output(
        case=case,
        final_answer=final_answer,
        payload=_claim_payload(
            final_answer=final_answer,
            claims=[("gpu", "The required GPU is Model X")],
            links=[],
            refused=False,
        ),
        producer_id="negative-fixture",
    )
    result = evaluate_answer_claim_case(case, candidate)

    assert result.answerability_correct is False
    assert result.refusal_leakage is True
    assert result.unsupported_claim_rate == 1.0


def test_forbidden_claim_terms_are_reported_separately_from_schema_validity():
    case = _two_claim_case()
    final_answer = "alpha legacy"
    candidate = parse_answer_claim_producer_output(
        case=case,
        final_answer=final_answer,
        payload=_claim_payload(
            final_answer=final_answer,
            claims=[("alpha", "alpha legacy")],
            links=[("alpha", "a.md")],
        ),
        producer_id="negative-fixture",
    )
    result = evaluate_answer_claim_case(case, candidate)

    assert result.schema_valid is True
    assert result.forbidden_claim_leakage is True


def test_producer_failure_is_recorded_without_candidate_scores():
    class FailingProducer:
        producer_id = "failing"
        producer_version = "v1"

        def produce(self, request: AnswerClaimProducerInput) -> dict:
            raise RuntimeError(request.case_id)

    case = _two_claim_case()
    candidates = run_answer_claim_producer(
        cases=(case,),
        answers={case.case_id: "alpha beta"},
        producer=FailingProducer(),
    )
    summary = evaluate_answer_claim_suite((case,), candidates)

    assert summary.schema_parse_rate == 0.0
    assert summary.invalid_case_ids == (case.case_id,)
    assert summary.mean_claim_f1 is None
    assert summary.mean_link_f1 is None
    assert summary.results[0].parse_error == "producer_failed:RuntimeError"
