from src.pedagogy.evaluation import (
    LLMSemanticEvaluator,
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


def test_available_evidence_requires_an_explicit_grounded_reference():
    semantic = FakeSemanticEvaluator(
        SemanticEvaluation(
            reasoning_complete=True,
            transfer_ready=True,
            confidence=0.95,
        )
    )
    run = PedagogyEvaluationService(semantic).evaluate_learner(
        learner_input="所以该结论成立，因为实验报告显示效应为正。",
        state=LearningState(objective="interpret result", protocol="socratic_rediscovery"),
        evidence=("study-1",),
    )

    assert run.final_decision == "reject"
    assert "missing_evidence_reference" in run.reasons


def test_semantic_provider_failure_is_recorded_as_review_not_acceptance():
    class FailingSemanticEvaluator:
        def evaluate(self, **_kwargs):
            raise TimeoutError("provider unavailable")

    run = PedagogyEvaluationService(FailingSemanticEvaluator()).evaluate_learner(
        learner_input="所以范围每轮减半，因为剩余规模变成之前的一半。",
        state=LearningState(objective="binary search", protocol="socratic_rediscovery"),
    )

    assert run.final_decision == "needs_semantic_review"
    assert run.confidence == 0.0
    assert run.reasons == ("semantic_evaluator_failed:TimeoutError",)


def test_llm_semantic_adapter_uses_versioned_strict_json_contract():
    calls = []

    def complete(messages, **kwargs):
        calls.append((messages, kwargs))
        return """{
            "claims": ["range halves"],
            "correct_points": ["geometric reduction"],
            "gaps": [],
            "misconceptions": [],
            "reasoning_complete": true,
            "transfer_ready": true,
            "confidence": 0.9,
            "evidence_refs": ["e-1"]
        }"""

    result = LLMSemanticEvaluator(complete).evaluate(
        learner_input="reasoned answer",
        objective="binary search",
        protocol="socratic_rediscovery",
        expected_concepts=("halving",),
        evidence=("e-1",),
    )

    assert result.reasoning_complete is True
    assert result.evidence_refs == ("e-1",)
    assert calls[0][1]["response_format"] == {"type": "json_object"}
    assert calls[0][1]["task_name"] == "pedagogy_evaluation"
