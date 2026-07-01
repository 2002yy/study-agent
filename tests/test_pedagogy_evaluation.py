from src.pedagogy.evaluation import (
    PedagogyEvaluationService,
    SemanticEvaluation,
)
from src.pedagogy.types import LearningState


class FakeSemanticEvaluator:
    def __init__(self, result: SemanticEvaluation):
        self.result = result
        self.calls = 0

    def evaluate(self, **_kwargs) -> SemanticEvaluation:
        self.calls += 1
        return self.result


def test_known_misconception_is_rejected_without_semantic_cost():
    semantic = FakeSemanticEvaluator(SemanticEvaluation(transfer_ready=True))
    run = PedagogyEvaluationService(semantic).evaluate_learner(
        learner_input=(
            "所以二分查找是 O(n)，因为每次只检查一个元素，我明白了。"
        ),
        state=LearningState(
            objective="理解二分查找复杂度",
            protocol="socratic_rediscovery",
        ),
    )
    assert run.final_decision == "reject"
    assert semantic.calls == 0
    assert run.deterministic_result["misconceptions"]


def test_ambiguous_claim_requires_semantic_review_when_provider_is_absent():
    run = PedagogyEvaluationService().evaluate_learner(
        learner_input="所以每次范围减半，因为剩余规模变成之前的一半。",
        state=LearningState(
            objective="理解二分查找复杂度",
            protocol="socratic_rediscovery",
        ),
    )
    assert run.final_decision == "needs_semantic_review"
    assert run.confidence == 0.0


def test_semantic_result_must_be_confident_complete_and_evidence_grounded():
    semantic = FakeSemanticEvaluator(
        SemanticEvaluation(
            claims=("范围每轮减半",),
            correct_points=("规模形成等比数列",),
            reasoning_complete=True,
            transfer_ready=True,
            confidence=0.91,
            evidence_refs=("evidence-1",),
        )
    )
    run = PedagogyEvaluationService(semantic).evaluate_learner(
        learner_input="所以每次范围减半，因为剩余规模变成之前的一半。",
        state=LearningState(
            objective="理解二分查找复杂度",
            protocol="socratic_rediscovery",
        ),
        expected_concepts=("halving", "logarithm"),
        evidence=("evidence-1",),
    )
    assert run.final_decision == "accept"
    assert run.semantic_result is not None
    assert run.semantic_result.correct_points == ("规模形成等比数列",)


def test_unknown_evidence_reference_blocks_state_progression():
    semantic = FakeSemanticEvaluator(
        SemanticEvaluation(
            reasoning_complete=True,
            transfer_ready=True,
            confidence=0.95,
            evidence_refs=("invented-source",),
        )
    )
    run = PedagogyEvaluationService(semantic).evaluate_learner(
        learner_input="所以每次范围减半，因为剩余规模变成之前的一半。",
        state=LearningState(objective="binary search", protocol="socratic_rediscovery"),
        evidence=("trusted-source",),
    )
    assert run.final_decision == "reject"
    assert "unknown_evidence_reference" in run.reasons
