from __future__ import annotations

import json
from typing import Any

TURN_CONTEXT_PREFIX = "__STUDY_AGENT_TURN_CONTEXT_V1__"
SCENE_CONTEXT_PREFIX = "__STUDY_AGENT_SCENE_CONTEXT_V1__"
DEFAULT_LESSON_MARKER = "【当前默认示例界面状态】"
_DEFAULT_LESSON_SIGNATURE = "主题：流萤超击破体系；数据按4.2加强后口径。"
_DEFAULT_LESSON_NON_DURABLE_NOTE = "不得写入 durable learner truth"
_MAX_TURN_CONTEXT_CHARS = 12_000


def unpack_conversation_instruction(value: str) -> tuple[str, str]:
    """Split durable user instruction from turn-only UI context.

    The JSON envelope is the explicit transport contract.  The marker split is
    supported for the current Firefly bounded slice, whose frontend already
    appends a signed default-lesson block to the user instruction.  Unframed or
    malformed values remain ordinary user-authored instructions.
    """

    if value.startswith(TURN_CONTEXT_PREFIX):
        raw = value[len(TURN_CONTEXT_PREFIX) :]
        try:
            payload: Any = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return value, ""
        if not isinstance(payload, dict):
            return value, ""
        instruction = payload.get("conversation_instruction")
        context = payload.get("turn_context")
        if not isinstance(instruction, str) or not isinstance(context, str):
            return value, ""
        return instruction, context[:_MAX_TURN_CONTEXT_CHARS]

    marker_index = value.find(DEFAULT_LESSON_MARKER)
    if marker_index < 0:
        return value, ""
    context = value[marker_index:]
    if (
        _DEFAULT_LESSON_SIGNATURE not in context
        or _DEFAULT_LESSON_NON_DURABLE_NOTE not in context
    ):
        return value, ""
    prefix = value[:marker_index]
    # The runtime joins user instruction and the UI block with two newlines.
    # Strip only that transport separator; user-authored whitespace otherwise
    # remains untouched.
    if prefix.endswith("\n\n"):
        prefix = prefix[:-2]
    return prefix, context[:_MAX_TURN_CONTEXT_CHARS]


def pack_scene_turn_context(scene: str, turn_context: str) -> str:
    """Carry turn-only context through the existing non-durable scene command field."""

    context = turn_context.strip()[:_MAX_TURN_CONTEXT_CHARS]
    if not context:
        return scene
    return SCENE_CONTEXT_PREFIX + json.dumps(
        {"scene": scene, "turn_context": context},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def unpack_scene_turn_context(value: str | None) -> tuple[str, str]:
    scene = str(value or "single")
    if not scene.startswith(SCENE_CONTEXT_PREFIX):
        return scene, ""
    raw = scene[len(SCENE_CONTEXT_PREFIX) :]
    try:
        payload: Any = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return scene, ""
    if not isinstance(payload, dict):
        return scene, ""
    actual_scene = payload.get("scene")
    context = payload.get("turn_context")
    if not isinstance(actual_scene, str) or not isinstance(context, str):
        return scene, ""
    return actual_scene, context[:_MAX_TURN_CONTEXT_CHARS]
