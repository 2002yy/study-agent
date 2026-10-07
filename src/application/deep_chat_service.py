"""Deep-3: the ChatService variant that signals the Deep trigger.

This is a drop-in subclass of StandardContinuationChatService. Its only added behaviour is to
signal the background runner after the turn is durably complete - it never runs Deep work, never
waits for the worker and never touches the answer.

That is what keeps the Deep tier's 180 second window out of the chat response path. If the wake
is lost, the runner's startup and periodic scans rediscover the same durable work, so signalling
is an optimisation rather than a correctness requirement.
"""

from __future__ import annotations

from typing import Any

from src.application.standard_chat_service import StandardContinuationChatService
from src.domain.runtime_entities import ChatTurn


class DeepContinuationChatService(StandardContinuationChatService):
    def __init__(self, *args: Any, deep_runner: Any = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._deep_runner = deep_runner

    def complete_turn(self, prepared: Any, suffix: str) -> ChatTurn:
        completed = super().complete_turn(prepared, suffix)
        runner = self._deep_runner
        if runner is None:
            return completed
        try:
            runner.wake()
        except Exception:
            # Signalling is infrastructure; a failure here must never affect the answer.
            return completed
        return completed
