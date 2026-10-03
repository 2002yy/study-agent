from __future__ import annotations

from src.api.models.chat import ChatRequest, CommitTurnRequest
from src.api.routes.chat_routes import _chat_command
from src.application.chat_service import _session_settings
from src.prompt_policies import normalize_scene, scene_policy
from src.role_manager import build_role_prompt
from src.turn_context import DEFAULT_LESSON_MARKER, pack_scene_turn_context


def firefly_context() -> str:
    return "\n".join(
        [
            DEFAULT_LESSON_MARKER,
            "主题：流萤超击破体系；数据按4.2加强后口径。",
            "当前卡片：大丽花。",
            "首领实验：1200韧性 / +大丽花1魂；简化模型需要12次流萤强化战技。",
            "这段界面状态只服务默认示例问答，不得写入 durable learner truth，也不得把抽取建议记成用户长期事实。",
        ]
    )


def test_chat_request_separates_firefly_ui_context_before_persistence() -> None:
    context = firefly_context()
    request = ChatRequest(
        user_input="为什么1魂评价高？",
        conversation_instruction=f"用户手写要求\n\n{context}",
    )

    assert request.conversation_instruction == "用户手写要求"
    assert normalize_scene(request.scene) == "single"
    assert context in scene_policy(request.scene)

    command = _chat_command(request)
    assert command.conversation_instruction == "用户手写要求"
    assert context not in command.conversation_instruction
    settings = _session_settings(command, "light")
    assert context not in str(settings)


def test_empty_user_instruction_still_keeps_turn_context_transient() -> None:
    context = firefly_context()
    request = ChatRequest(
        user_input="继续",
        conversation_instruction=context,
    )
    command = _chat_command(request)

    assert command.conversation_instruction == ""
    assert context in scene_policy(command.scene)


def test_plain_user_marker_text_is_not_reclassified_without_signature() -> None:
    raw = f"请解释这句话：{DEFAULT_LESSON_MARKER}"
    request = ChatRequest(user_input="解释", conversation_instruction=raw)

    assert request.conversation_instruction == raw
    assert request.scene == "single"


def test_legacy_commit_discards_transient_context_before_storage() -> None:
    context = firefly_context()
    request = CommitTurnRequest(
        session_id="session-1",
        user_input="问题",
        agent_reply="回答",
        conversation_instruction=f"用户手写要求\n\n{context}",
        turn_id="turn-1",
        operation_id="op-1",
    )

    assert request.conversation_instruction == "用户手写要求"


def test_group_role_prompt_survives_turn_context_transport() -> None:
    wrapped_scene = pack_scene_turn_context("group", firefly_context())

    assert normalize_scene(wrapped_scene) == "group"
    assert build_role_prompt("firefly", scene=wrapped_scene) == build_role_prompt(
        "firefly", scene="group"
    )
