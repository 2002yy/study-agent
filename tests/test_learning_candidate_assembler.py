"""§164-B: the assembler translates turn facts and never becomes an authority."""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from src.application.learning_candidate_assembler import assemble_closure_candidate
from src.domain.learning_closure_candidate import (
    ABSTAIN_CONFLICTING_EVIDENCE,
    ABSTAIN_EVALUATOR_UNCERTAIN,
    ABSTAIN_INSUFFICIENT_RESPONSE,
    ABSTAIN_NO_AUTHORITATIVE_EVIDENCE,
    ABSTAIN_OUTSIDE_OBJECTIVE,
    ABSTAIN_REASONS,
    ABSTAIN_ROUTING,
    AUTHORITY_REQUIRED_CLOSURE_REVIEW,
    CandidateAbstention,
    FORBIDDEN_CANDIDATE_FIELDS,
    LearningClosureCandidate,
    ProposedMisconception,
    ProposedNextStep,
    ProposedUnderstanding,
    find_forbidden_fields,
)
from src.pedagogy.evaluation import PedagogyEvalRun, SemanticEvaluation

ROOT = Path(__file__).resolve().parents[1]
ASSEMBLER = ROOT / "src/application/learning_candidate_assembler.py"

OBJECTIVE = "explain why the sky is blue"


def _run(
    *,
    final_decision: str,
    semantic: SemanticEvaluation | None = None,
    status: str = "completed",
    learner_input: str = "Rayleigh scattering dominates at short wavelengths.",
    misconceptions: tuple[str, ...] = (),
    is_claim: bool = True,
    evidence: tuple[str, ...] = ("src-1",),
    objective: str = OBJECTIVE,
    reasons: tuple[str, ...] = (),
) -> PedagogyEvalRun:
    return PedagogyEvalRun(
        id="ped_eval_test",
        learner_input=learner_input,
        objective=objective,
        protocol="socratic_rediscovery",
        expected_concepts=("scattering",),
        evidence=evidence,
        deterministic_result={"misconceptions": list(misconceptions), "is_claim": is_claim},
        semantic_result=semantic,
        confidence=0.9,
        final_decision=final_decision,
        semantic_review_status=status,
        reasons=reasons,
    )


def _assemble(**kwargs) -> LearningClosureCandidate:
    return assemble_closure_candidate(source_turn_id="turn-1", **kwargs)


# 1-3: proposals mirror the evaluation without becoming truth

def test_accepted_evaluation_proposes_pass_but_never_commits() -> None:
    candidate = _assemble(pedagogy_eval=_run(
        final_decision="accept",
        semantic=SemanticEvaluation(reasoning_complete=True, transfer_ready=True,
                                    confidence=0.9, evidence_refs=("src-1",)),
    ))
    understanding = candidate.understanding_proposals()
    assert len(understanding) == 1
    assert understanding[0].proposed_result == "pass"
    assert understanding[0].authority_required == AUTHORITY_REQUIRED_CLOSURE_REVIEW
    assert understanding[0].pedagogy_eval_ref == "ped_eval_test"
    assert candidate.abstentions == ()
    payload = candidate.to_dict()
    assert find_forbidden_fields(payload) == frozenset()
    assert payload["proposals"][0]["kind"] == "understanding"


def test_partial_evaluation_proposes_partial() -> None:
    candidate = _assemble(pedagogy_eval=_run(
        final_decision="reject", semantic=SemanticEvaluation(confidence=0.4),
    ))
    assert candidate.understanding_proposals()[0].proposed_result == "fail"


def test_failed_evaluation_with_misconception_proposes_both() -> None:
    candidate = _assemble(pedagogy_eval=_run(
        final_decision="reject",
        misconceptions=("confuses scattering with reflection",),
        semantic=SemanticEvaluation(misconceptions=("claims blue light is absorbed",)),
    ))
    labels = [item.description for item in candidate.misconception_proposals()]
    assert labels == [
        "confuses scattering with reflection",
        "claims blue light is absorbed",
    ]
    assert candidate.understanding_proposals()[0].proposed_result == "fail"
    # 168 owns the lifecycle; here a misconception is only ever proposed.
    assert all(
        isinstance(item, ProposedMisconception) for item in candidate.misconception_proposals()
    )


# 4-7: abstention taxonomy is reachable and routable

def test_missing_authoritative_evidence_abstains_and_proposes_research() -> None:
    candidate = _assemble(pedagogy_eval=_run(
        final_decision="needs_semantic_review",
        status="blocked_by_policy",
        semantic=None,
    ))
    assert candidate.understanding_proposals() == ()
    abstention = candidate.abstentions_for("understanding")[0]
    assert abstention.reason == ABSTAIN_NO_AUTHORITATIVE_EVIDENCE
    assert abstention.route == "research"
    # The abstention does not void the candidate: a next step is still proposed.
    assert [item.action for item in candidate.next_step_proposals()] == ["research"]


def test_insufficient_response_abstains() -> None:
    candidate = _assemble(pedagogy_eval=_run(
        final_decision="reject", learner_input="   ",
    ))
    assert candidate.abstentions_for("understanding")[0].reason == (
        ABSTAIN_INSUFFICIENT_RESPONSE
    )


def test_non_claim_response_abstains_rather_than_failing() -> None:
    candidate = _assemble(pedagogy_eval=_run(
        final_decision="reject", is_claim=False,
    ))
    assert candidate.abstentions_for("understanding")[0].reason == (
        ABSTAIN_INSUFFICIENT_RESPONSE
    )
    assert candidate.understanding_proposals() == ()


def test_outside_objective_abstains_and_updates_nothing() -> None:
    candidate = _assemble(pedagogy_eval=_run(
        final_decision="accept", objective="",
    ))
    abstention = candidate.abstentions_for("understanding")[0]
    assert abstention.reason == ABSTAIN_OUTSIDE_OBJECTIVE
    assert abstention.route == "no_learner_truth_update"
    assert candidate.understanding_proposals() == ()
    assert candidate.next_step_proposals() == ()


def test_evaluator_uncertainty_abstains_with_a_retry_route() -> None:
    candidate = _assemble(pedagogy_eval=_run(
        final_decision="needs_semantic_review", status="unavailable",
    ))
    abstention = candidate.abstentions_for("understanding")[0]
    assert abstention.reason == ABSTAIN_EVALUATOR_UNCERTAIN
    assert abstention.route == "bounded_evaluator_retry_or_human"


def test_conflicting_evidence_abstains_with_a_review_route() -> None:
    candidate = _assemble(
        pedagogy_eval=_run(final_decision="accept"),
        conflicting_evidence_refs=("src-2",),
    )
    abstention = candidate.abstentions_for("understanding")[0]
    assert abstention.reason == ABSTAIN_CONFLICTING_EVIDENCE
    assert abstention.route == "research_or_manual_review"


def test_unknown_evidence_reference_abstains() -> None:
    candidate = _assemble(pedagogy_eval=_run(
        final_decision="accept",
        semantic=SemanticEvaluation(confidence=0.9, evidence_refs=("not-allowed",)),
    ))
    assert candidate.abstentions_for("understanding")[0].reason == (
        ABSTAIN_NO_AUTHORITATIVE_EVIDENCE
    )


def test_every_abstain_reason_has_a_route() -> None:
    assert set(ABSTAIN_ROUTING) == set(ABSTAIN_REASONS)


# 8: idempotence

def test_same_inputs_produce_the_same_semantic_fingerprint() -> None:
    run = _run(final_decision="accept", semantic=SemanticEvaluation(confidence=0.9))
    first = _assemble(pedagogy_eval=run)
    second = _assemble(pedagogy_eval=run)
    assert first.candidate_id != second.candidate_id
    assert first.semantic_fingerprint == second.semantic_fingerprint
    assert first.to_dict()["proposals"] == second.to_dict()["proposals"]


def test_different_inputs_produce_different_fingerprints() -> None:
    accept = _assemble(pedagogy_eval=_run(final_decision="accept"))
    reject = _assemble(pedagogy_eval=_run(final_decision="reject"))
    assert accept.semantic_fingerprint != reject.semantic_fingerprint


# 9: schema carries no authority-shaped field

def test_candidate_schema_has_no_authority_field() -> None:
    classes = (
        ProposedUnderstanding, ProposedMisconception, ProposedNextStep,
        CandidateAbstention, LearningClosureCandidate,
    )
    for cls in classes:
        names = {field.name for field in dataclasses.fields(cls)}
        assert names & FORBIDDEN_CANDIDATE_FIELDS == set(), cls.__name__


def test_candidate_payload_never_exposes_mastery_or_commitment() -> None:
    candidate = _assemble(pedagogy_eval=_run(
        final_decision="accept",
        semantic=SemanticEvaluation(reasoning_complete=True, transfer_ready=True,
                                    confidence=0.95),
    ))
    blob = str(candidate.to_dict()).lower()
    for forbidden in ("committed", "mastery", "mastered", "qualified",
                      "durable_id", "semantic_label"):
        assert forbidden not in blob


def test_candidate_id_is_not_a_truth_identity() -> None:
    candidate = _assemble(pedagogy_eval=_run(final_decision="accept"))
    assert candidate.candidate_id.startswith("lcc_")
    assert candidate.candidate_id != candidate.pedagogy_eval_refs[0]
    assert candidate.candidate_id != candidate.objective_ref


# 10: dependency-level proof that the bridge stops at the closure boundary

def test_assembler_cannot_reach_the_truth_writer() -> None:
    tree = ast.parse(ASSEMBLER.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden_modules = (
        "repositories", "sqlite", "learning_truth_repository",
        "learning_closure_truth", "learning_closure_service",
        "learning_semantic_closure", "runtime_repository",
    )
    for module in imported:
        assert not any(token in module for token in forbidden_modules), module


def test_assembler_does_not_commit_or_write_durable_truth() -> None:
    source = ASSEMBLER.read_text(encoding="utf-8").lower()
    for forbidden in ("commit(", "create_understanding_evidence", "create_next_step",
                      "create_goal", "focus_goal", "add_prerequisite",
                      "complete(", "chat("):
        assert forbidden not in source, forbidden


def test_assembler_is_a_pure_projection() -> None:
    run = _run(final_decision="accept", semantic=SemanticEvaluation(confidence=0.9))
    before = run.to_dict()
    _assemble(pedagogy_eval=run)
    assert run.to_dict() == before


@pytest.mark.parametrize("reason", ABSTAIN_REASONS)
def test_abstention_carries_dimension_reason_and_route(reason: str) -> None:
    abstention = CandidateAbstention(dimension="understanding", reason=reason)
    payload = abstention.to_dict()
    assert payload["reason"] == reason
    assert payload["route"] == ABSTAIN_ROUTING[reason]
    assert payload["dimension"] == "understanding"
