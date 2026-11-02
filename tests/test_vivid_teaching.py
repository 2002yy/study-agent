"""Offline prompt/turn contracts, not evidence of real model teaching quality."""

from __future__ import annotations

import pytest

from src.context_builder import build_messages
from src.mode_manager import RuntimeModes
from src.pedagogy.engine import PedagogyEngine
from src.pedagogy.types import LearningState
from src.role_manager import build_role_prompt
from src.router import route_request


@pytest.mark.parametrize(
    "role,voice",
    [
        ("nahida", "先看谁拥有这份状态"),
        ("march7", "这份数据到底算谁的"),
        ("firefly", "先停在这一行"),
        ("keqing", "final 锁的是这张地址条"),
    ],
)
@pytest.mark.parametrize("mode", ["普通", "苏格拉底", "费曼"])
def test_actual_message_compilation_keeps_voice_and_shared_teaching(role, voice, mode):
    question = "用游戏服务器带我学习 static，先让我预测结果"
    plan, state = PedagogyEngine().plan(
        user_input=question, mode=mode, state=LearningState()
    )
    messages = build_messages(
        user_input=question,
        role_prompt=build_role_prompt(role),
        mode=mode,
        memory_bundle={},
        runtime_modes=RuntimeModes(),
        pedagogy_plan=plan,
        learning_state=state,
    )
    prompt = messages[0]["content"]
    assert voice in prompt
    assert "第一性原理" in prompt
    assert "场景与问题" in prompt
    assert "代码当成运行中的故事" in prompt
    assert "无法再轻易简化的基础" in prompt
    assert "习惯、约定、历史选择" in prompt
    assert "自主发现" in prompt
    assert "不要求每节课全部使用" in prompt
    assert "推导出此前不知道的结论" in prompt
    for obsolete in (
        "2～3 次互动",
        "每轮只执行一个",
        "require re-explanation",
        "single cognitive move",
        "再请用户进行简短复述",
    ):
        assert obsolete not in prompt
    assert "不要在同一条回复里公布" in prompt
    assert "[Pedagogy turn plan]" in prompt
    assert (
        "## 3. 教学风格" not in prompt
    )  # Old role-specific turn order stays excluded.
    assert messages[-1] == {"role": "user", "content": question}


@pytest.mark.parametrize("mode", ["苏格拉底", "费曼"])
@pytest.mark.parametrize(
    "utterance", ["请完整讲解 final 引用", "直接给答案", "不要追问，直接回答"]
)
def test_direct_request_overrides_guided_turn_even_after_repair(mode, utterance):
    state = LearningState(
        objective="final 引用",
        phase="repair",
        turn_count=2,
        payload={"repair_given": "counterexample"},
    )
    plan, result = PedagogyEngine().plan(user_input=utterance, mode=mode, state=state)
    assert plan.move == "direct_explain"
    assert plan.disclosure_level == 5
    assert result.objective == state.objective
    assert not result.payload.get("transfer_passed")


@pytest.mark.parametrize("mode", ["苏格拉底", "费曼"])
@pytest.mark.parametrize(
    "utterance", ["不要直接回答，先让我猜", "别直接告诉我", "不要马上给答案"]
)
def test_request_to_wait_never_becomes_direct_disclosure(mode, utterance):
    plan, _ = PedagogyEngine().plan(
        user_input=utterance, mode=mode, state=LearningState()
    )
    assert plan.disclosure_level < 5
    assert plan.move != "direct_explain"


@pytest.mark.parametrize(
    "utterance,expected",
    [
        ("不要直接回答，先让我猜 final 引用", "苏格拉底"),
        ("不要直接告诉我，等我判断", "苏格拉底"),
        ("不要马上给答案", "苏格拉底"),
        ("现在请完整讲解 final 引用", "普通"),
        ("直接给答案", "普通"),
    ],
)
def test_automatic_route_and_turn_plan_agree_on_wait_or_answer(utterance, expected):
    route = route_request(
        user_input=utterance,
        selected_role="firefly",
        selected_mode="auto",
        selected_model="auto",
        runtime_modes=RuntimeModes(),
        previous_mode="费曼",
    )
    assert route["mode"] == expected
    assert route["role"] == "firefly"
    plan, _ = PedagogyEngine().plan(
        user_input=utterance, mode=route["mode"], state=LearningState()
    )
    assert (plan.disclosure_level == 5) == (expected == "普通")


@pytest.mark.parametrize(
    "phase", ["orientation", "repair", "re_explain", "transfer", "complete"]
)
@pytest.mark.parametrize("utterance", ["讲讲哈希表", "这里为什么需要再比较键？"])
def test_feynman_explains_without_forcing_a_recitation_or_exam(phase, utterance):
    plan, state = PedagogyEngine().plan(
        user_input=utterance,
        mode="费曼",
        state=LearningState(
            protocol="feynman_diagnosis",
            objective="哈希表",
            phase=phase,
            turn_count=0 if phase == "orientation" else 3,
            payload={"repair_given": "counterexample"},
        ),
    )
    assert plan.move == "reconstruct"
    assert plan.disclosure_level >= 3
    assert "require re-explanation" not in " ".join(plan.constraints)
    assert not state.payload.get("transfer_passed")


def test_connected_socratic_questions_are_not_a_failed_response_contract():
    engine = PedagogyEngine()
    before = LearningState(protocol="socratic_rediscovery", objective="哈希冲突")
    plan, planned = engine.plan(
        user_input="引导我从根本推导哈希冲突",
        mode="苏格拉底",
        state=before,
    )
    evaluation = engine.evaluate_response(
        "只有 10 个位置，却有 11 个键。能让它们各占一处吗？你的分配依据是什么？",
        plan=plan,
    )
    assert (
        evaluation.question_count == 2
    )  # Observation, not a teaching-quality verdict.
    assert evaluation.passed
    assert (
        engine.apply_transition(before=before, planned=planned, evaluation=evaluation)
        == planned
    )


@pytest.mark.parametrize(
    "utterance",
    [
        "所以我现在重新理解了，我认为自己已经完全明白，可以结束了。",
        "我还没有理解这里的机制，能继续讲为什么桶编号不足以区分键吗？",
    ],
)
def test_long_text_and_transition_words_do_not_prove_feynman_mastery(utterance):
    plan, state = PedagogyEngine().plan(
        user_input=utterance,
        mode="费曼",
        state=LearningState(
            protocol="feynman_diagnosis",
            phase="transfer",
            turn_count=4,
            payload={"repair_given": "boundary"},
        ),
    )
    assert plan.phase != "complete"
    assert not state.payload.get("transfer_passed")
    assert not state.payload.get("reexplanation_passed")


@pytest.mark.parametrize("mode", ["苏格拉底", "费曼"])
def test_explicit_prediction_still_withholds_the_answer_after_prior_dialogue(mode):
    plan, _ = PedagogyEngine().plan(
        user_input="先让我预测 final 引用这段代码的输出，等我回答",
        mode=mode,
        state=LearningState(turn_count=3, phase="repair"),
    )
    assert plan.move == "request_prediction"
    assert plan.disclosure_level == 1


@pytest.mark.parametrize(
    "mismatch", ["learner_input", "objective", "protocol", "final_decision"]
)
def test_old_or_rejected_evaluation_does_not_close_a_new_feynman_turn(mismatch):
    text = "所以只凭桶编号无法识别键，因为不同键可能落在同一位置。"
    receipt = {
        "final_decision": "accept",
        "learner_input": text,
        "objective": "哈希冲突",
        "protocol": "feynman_diagnosis",
    }
    receipt[mismatch] = "unrelated_or_rejected"
    plan, state = PedagogyEngine().plan(
        user_input=text,
        mode="费曼",
        state=LearningState(
            protocol="feynman_diagnosis",
            objective="哈希冲突",
            phase="transfer",
            payload={"pedagogy_evaluation": receipt},
        ),
    )
    assert plan.phase != "complete"
    assert not state.payload.get("transfer_passed")


@pytest.mark.parametrize(
    "utterance", ["不用等我回答，继续讲", "不要先让我猜，继续推导"]
)
def test_declining_an_interaction_does_not_create_a_prediction_gate(utterance):
    plan, _ = PedagogyEngine().plan(
        user_input=utterance,
        mode="费曼",
        state=LearningState(turn_count=2),
    )
    assert plan.disclosure_level >= 3
    assert plan.move != "request_prediction"


def test_early_disclosure_still_fails_when_the_learner_asked_to_think():
    engine = PedagogyEngine()
    before = LearningState(protocol="feynman_diagnosis", objective="哈希冲突")
    plan, planned = engine.plan(user_input="先让我猜", mode="费曼", state=before)
    evaluation = engine.evaluate_response(
        "完整答案是至少两个键落在同一位置。", plan=plan
    )
    assert not evaluation.passed
    assert evaluation.violations == ("premature_conclusion_disclosure",)
    committed = engine.apply_transition(
        before=before, planned=planned, evaluation=evaluation
    )
    assert committed.turn_count == before.turn_count
