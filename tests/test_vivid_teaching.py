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
    assert "2～3 次互动" in prompt
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
