from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.models.chat import ChatRequest
from src.api.routes.chat_routes import _chat_command


def test_chat_request_forwards_explicit_task_intent():
    request = ChatRequest(
        user_input="联网看看最新消息",
        task_intent="quick_answer",
    )

    command = _chat_command(request)

    assert command.task_intent == "quick_answer"


def test_chat_request_rejects_unknown_task_intent():
    with pytest.raises(ValidationError):
        ChatRequest(
            user_input="test",
            task_intent="unknown",  # type: ignore[arg-type]
        )
