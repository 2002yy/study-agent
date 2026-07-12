from __future__ import annotations

from src.mode_manager import RuntimeModes
from src.pedagogy.types import AssistantResponseEvaluation, LearningState
from src.task_contract import (
    TaskAwarePedagogyEngine,
    TaskAwarePedagogyEvaluationService,
    classify_task_contract,
    route_request_with_task_contract,
)


def test_research_request_does_not_enter_learning_state():
    contract = classify_task_contract("联网看看gpt5.6sol")

    assert contract.task_intent == "research"
    assert contract.source_policy == "web_only"
    assert contract.closure_eligibility == "optional_note"
    assert contract.learning_state_enabled is False


def test_explicit_learning_and_execution_intents_are_distinct():
    learning = classify_task_contract("带我系统学习 GPT-5.6")
    explain_back = classify_task_contract("我来解释二分查找，你检查我的理解")
    project = classify_task_contract("帮我修改项目并跑测试")

    assert learning.task_intent == "learn"
    assert learning.learning_state_enabled is True
    assert learning.closure_eligibility == "learning_summary"

    assert explain_back.task_intent == "explain_back"
    assert explain_back.learning_state_enabled is True
    assert explain_back.closure_eligibility == "learning_summary"

    assert project.task_intent == "project_execution"
    assert project.learning_state_enabled is True
    assert project.closure_eligibility == "project_summary"


def test_safe_default_is_temporary_quick_answer():
    contract = classify_task_contract("数据库索引是什么？")

    assert contract.task_intent == "quick_answer"
    assert contract.learning_state_enabled is False
    assert contract.closure_eligibility == "not_applicable"


def test_ambiguous_follow_up_inherits_active_learning():
    contract = classify_task_contract("我不知道", active_learning=True)

    assert contract.task_intent == "learn"
    assert contract.learning_state_enabled is True
    assert contract.confidence == "medium"
    assert contract.reason == "continue_active_learning"


def test_explicit_research_overrides_active_learning_temporarily():
    contract = classify_task_contract(
        "联网看看gpt5.6sol",
        active_learning=True,
    )

    assert contract.task_intent == "research"
    assert contract.learning_state_enabled is False


def test_research_skips_semantic_mastery_evaluation():
    class FailingSemanticEvaluator:
        def evaluate(self, **kwargs):
            raise AssertionError("semantic evaluator must not run for research")

    service = TaskAwarePedagogyEvaluationService(FailingSemanticEvaluator())
    state = LearningState(
        protocol="socratic_rediscovery",
        objective="理解二分查找复杂度",
        phase="scaffold",
        confirmed_points=("每轮缩小一半",),
        unresolved_gap="从减半推到对数",
        turn_count=3,
    )

    result = service.evaluate_learner(
        learner_input="联网看看gpt5.6sol",
        state=state,
        expected_concepts=("对数",),
        evidence=("ev1",),
    )

    assert result.final_decision == "not_applicable"
    assert result.deterministic_result == {
        "skipped": True,
        "reason": "task_contract_not_learning",
    }
    assert result.reasons == ("task_intent:research",)


def test_research_plan_preserves_existing_learning_state():
    engine = TaskAwarePedagogyEngine()
    state = LearningState(
        protocol="socratic_rediscovery",
        objective="理解二分查找复杂度",
        phase="scaffold",
        confirmed_points=("每轮缩小一半",),
        unresolved_gap="从减半推到对数",
        turn_count=3,
    )

    plan, next_state = engine.plan(
        user_input="联网看看gpt5.6sol",
        mode="苏格拉底",
        state=state,
    )

    assert next_state == state
    assert plan.mode == "direct_answer"
    assert plan.phase == "answer"
    assert "do_not_update_learning_state" in plan.constraints
    assert "task_intent:research" in plan.constraints


def test_research_commit_removes_the_transient_evaluation_payload():
    engine = TaskAwarePedagogyEngine()
    original = LearningState(
        protocol="socratic_rediscovery",
        objective="理解二分查找复杂度",
        phase="scaffold",
        confirmed_points=("每轮缩小一半",),
        unresolved_gap="从减半推到对数",
        turn_count=3,
        payload={"stable": "keep"},
    )
    injected = LearningState.from_dict(
        {
            **original.to_dict(),
            "payload": {
                **original.payload,
                "pedagogy_evaluation": {
                    "final_decision": "not_applicable",
                    "reasons": ["task_intent:research"],
                },
            },
        }
    )

    plan, planned = engine.plan(
        user_input="联网看看gpt5.6sol",
        mode="苏格拉底",
        state=injected,
    )
    committed = engine.apply_transition(
        before=injected,
        planned=planned,
        evaluation=AssistantResponseEvaluation(passed=False, violations=("test",)),
    )

    assert plan.mode == "direct_answer"
    assert committed == original
    assert "pedagogy_evaluation" not in committed.payload


def test_learning_request_still_uses_the_pedagogy_engine():
    engine = TaskAwarePedagogyEngine()
    state = LearningState()

    plan, next_state = engine.plan(
        user_input="带我系统学习数据库索引",
        mode="普通",
        state=state,
    )

    assert plan.mode == "direct_answer"
    assert next_state.phase == "answer"
    assert next_state.turn_count == 1


def test_active_learning_follow_up_still_uses_the_pedagogy_engine():
    engine = TaskAwarePedagogyEngine()
    state = LearningState(
        protocol="socratic_rediscovery",
        objective="理解二分查找复杂度",
        phase="scaffold",
        turn_count=2,
    )

    _, next_state = engine.plan(
        user_input="我不知道",
        mode="苏格拉底",
        state=state,
    )

    assert next_state.turn_count == 3
    assert next_state.objective == state.objective


def test_route_snapshot_contains_task_contract():
    route = route_request_with_task_contract(
        user_input="联网看看gpt5.6sol",
        selected_role="auto",
        selected_mode="auto",
        selected_model="auto",
        runtime_modes=RuntimeModes(performance_mode="fast"),
        previous_role=None,
        previous_mode=None,
        keep_current_role=False,
    )

    task_contract = route["task_contract"]
    assert isinstance(task_contract, dict)
    assert task_contract["task_intent"] == "research"
    assert task_contract["learning_state_enabled"] is False


def test_route_snapshot_inherits_non_direct_learning_mode():
    route = route_request_with_task_contract(
        user_input="我不知道",
        selected_role="auto",
        selected_mode="auto",
        selected_model="auto",
        runtime_modes=RuntimeModes(performance_mode="fast"),
        previous_role="nahida",
        previous_mode="苏格拉底",
        keep_current_role=False,
    )

    task_contract = route["task_contract"]
    assert task_contract["task_intent"] == "learn"
    assert task_contract["reason"] == "continue_active_learning"
