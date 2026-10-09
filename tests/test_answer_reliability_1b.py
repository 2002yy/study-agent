"""Slice 1b: reasoning-licence schema, formula-origin provenance, auditor wiring."""

from __future__ import annotations

from src.application.answer_verification import (
    AnswerVerificationInputs,
    BoundaryProposal,
    CalculationProposal,
    observe_answer_verification,
    resolve_formula_origin,
)
from src.domain.answer_claims import answer_content_hash
from src.web.research.final_answer_auditor import tool_consistency
from tools.research_ability_ab import ANSWER_PROMPT_V2, citation_checks_v2


def test_prompt_v2_is_domain_general() -> None:
    lowered = ANSWER_PROMPT_V2.lower()
    assert "derivation" in lowered and "verbatim" in lowered
    assert "go" not in lowered.split("google")[0]  # no per-domain exemption keyword
    for key in ("calculations", "boundaries", "derivations", "claims", "unknowns", "answer"):
        assert key in ANSWER_PROMPT_V2


def test_origin_model_recall_never_verified() -> None:
    check = resolve_formula_origin(("model_recall", ""), "20+0.9*x")
    assert check.status == "unverified"
    assert check.reason == "model_recall_is_not_a_source"


def test_origin_user_given_requires_premise_in_question() -> None:
    hit = resolve_formula_origin(
        ("user_given", ""), "20+0.9*x", original_question="用 20 和 0.9 计算"
    )
    assert hit.status == "user_given_verified"
    miss = resolve_formula_origin(
        ("user_given", ""), "20+0.9*x", original_question="没有这些数字"
    )
    assert miss.status == "unverified"


def test_origin_evidence_quote_requires_owned_ref_and_premise() -> None:
    ok = resolve_formula_origin(
        ("evidence_quote", "E1"),
        "20+0.9*x",
        evidence_ids=frozenset({"E1"}),
        evidence_text="A: 20 plus 0.90 per million",
    )
    assert ok.status == "evidence_verified"
    bad_ref = resolve_formula_origin(
        ("evidence_quote", "E9"),
        "20+0.9*x",
        evidence_ids=frozenset({"E1"}),
        evidence_text="A: 20 plus 0.90 per million",
    )
    assert bad_ref.status == "unverified"


def _report(origin, result="30.8"):
    candidate = "final answer text"
    inputs = AnswerVerificationInputs(
        answer_hash=answer_content_hash(candidate),
        original_question="",
        evidence_texts=(("E1", "A: 20 plus 0.90 per million, free 5 million"),),
        calculations=(
            CalculationProposal(
                expression="20+0.9*x",
                result=result,
                variables=(("x", "12"),),
                formula_origin=origin,
            ),
        ),
    )
    return observe_answer_verification(candidate, inputs)


def test_arithmetic_pass_with_unverified_formula_is_not_verified_support() -> None:
    report = _report(("model_recall", ""))
    row = report["calculations"][0]
    assert row["status"] == "PASS"
    assert row["verified_support"] is False
    assert report["status"] == "UNKNOWN"  # PASS arithmetic must not read as a fact


def test_arithmetic_pass_with_verified_origin_is_pass() -> None:
    report = _report(("evidence_quote", "E1"))
    assert report["calculations"][0]["verified_support"] is True
    assert report["status"] == "PASS"


def test_arithmetic_mismatch_fails() -> None:
    report = _report(("evidence_quote", "E1"), result="17.5")
    assert report["calculations"][0]["status"] == "FAIL"
    assert report["status"] == "FAIL"


def test_boundary_verified_support_tracks_origin() -> None:
    candidate = "answer"
    inputs = AnswerVerificationInputs(
        answer_hash=answer_content_hash(candidate),
        evidence_texts=(("E1", "A: 20 plus 0.90; B: 2.50, free 5 per million"),),
        boundaries=(
            BoundaryProposal(
                left="20+0.9*x",
                right="2.5*(x-5)",
                variable="x",
                result="20.3125",
                below="12",
                above="30",
                below_relation=">",
                above_relation="<",
                formula_origin=("evidence_quote", "E1"),
            ),
        ),
    )
    report = observe_answer_verification(candidate, inputs)
    assert report["boundaries"][0]["status"] == "PASS"
    assert report["boundaries"][0]["verified_support"] is True


def test_auditor_tool_consistency_dimensions() -> None:
    assert tool_consistency(None) == ("unverified", ())
    fail_dim, fail_issues = tool_consistency(
        {"calculations": [{"status": "FAIL", "label": "threshold"}]}
    )
    assert fail_dim == "partial" and fail_issues[0].issue_type == "tool_result_mismatch"
    covered, issues = tool_consistency(
        {"calculations": [{"status": "PASS", "verified_support": True}]}
    )
    assert covered == "covered" and issues == ()
    unverified, _ = tool_consistency(
        {"calculations": [{"status": "PASS", "verified_support": False}]}
    )
    assert unverified == "unverified"


def test_citation_checks_v2_schema() -> None:
    sources = [{"id": "S1", "text": "hello world from evidence"}]
    good = {
        "claims": [{"text": "x", "citations": [{"source_id": "S1", "quote": "hello world"}]}],
        "calculations": [],
        "boundaries": [],
        "derivations": [],
        "unknowns": [],
        "answer": "answer text",
    }
    assert citation_checks_v2(good, sources)["structural_errors"] == []
    bad = {key: value for key, value in good.items() if key != "calculations"}
    assert citation_checks_v2(bad, sources)["structural_errors"] == ["answer_schema"]
