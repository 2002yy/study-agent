"""DeepSeek chat-completions adapter for the opt-in conversation runners.

The injected client belongs to the host. This module reads no environment,
creates no clients and grants no spend or publication authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from src.application.conversation_answer_runner import ModelAnswerRequest
from src.application.conversation_decision_runner import ModelDecisionRequest


@dataclass(frozen=True)
class DeepSeekConversationTransport:
    client: Any = field(repr=False)
    model: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.model, str)
            or not self.model.strip()
            or len(self.model) > 200
            or not callable(getattr(self.client, "with_options", None))
        ):
            raise ValueError("invalid DeepSeek transport")

    async def __call__(self, request: ModelDecisionRequest | ModelAnswerRequest) -> str:
        if not isinstance(request, (ModelDecisionRequest, ModelAnswerRequest)):
            raise ValueError("invalid conversation model request")
        token_cap = 2000 if isinstance(request, ModelDecisionRequest) else 4000
        if (
            type(request.max_attempts) is not int
            or request.max_attempts != 1
            or type(request.max_output_tokens) is not int
            or not 1 <= request.max_output_tokens <= token_cap
            or isinstance(request.timeout_seconds, bool)
            or not isinstance(request.timeout_seconds, (int, float))
            or not math.isfinite(request.timeout_seconds)
            or not 0 < request.timeout_seconds <= 30
            or not isinstance(request.call_id, str)
            or not request.call_id.strip()
            or len(request.call_id) > 240
            or not isinstance(request.messages, tuple)
            or not 1 <= len(request.messages) <= 8
        ):
            raise ValueError("invalid bounded conversation request")
        messages = []
        for pair in request.messages:
            if (
                not isinstance(pair, tuple)
                or len(pair) != 2
                or pair[0] not in {"system", "user", "assistant"}
                or not isinstance(pair[1], str)
                or not pair[1].strip()
            ):
                raise ValueError("invalid conversation messages")
            messages.append({"role": pair[0], "content": pair[1]})
        if sum(len(item["content"]) for item in messages) > 128000:
            raise ValueError("conversation transport input limit")
        scoped = self.client.with_options(
            max_retries=0, timeout=request.timeout_seconds
        )
        if getattr(scoped, "max_retries", None) != 0:
            raise ValueError("client cannot disable hidden retries")
        options: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_output_tokens,
            "timeout": request.timeout_seconds,
            "stream": False,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if isinstance(request, ModelDecisionRequest):
            options["response_format"] = {"type": "json_object"}
        # No local retry, repair request, tools, or provider fallback.
        response = await scoped.chat.completions.create(**options)
        choices = getattr(response, "choices", None)
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError("invalid DeepSeek response")
        choice = choices[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None)
        cap = 32000 if isinstance(request, ModelDecisionRequest) else 8000
        if (
            getattr(choice, "finish_reason", None) != "stop"
            or getattr(message, "refusal", None)
            or getattr(message, "tool_calls", None)
            or not isinstance(content, str)
            or not 0 < len(content) <= cap
            or not content.strip()
        ):
            raise ValueError("incomplete or invalid DeepSeek response")
        return content
