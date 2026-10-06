"""Standard-4: the ChatService variant that continues a pending Standard handoff.

This is a drop-in subclass. The base class is untouched, and the only added behaviour runs
*after* the parent turn is durably completed - which is what Standard admission requires, so
the order cannot be swapped.

Two guarantees are deliberate.

The answer is already safe. If continuation raises, the completed turn is returned unchanged:
evidence fails closed, chat delivery fails safe. The assistant message is never rewritten,
pedagogy and learning state are untouched, and no answer-generation call is added.

Activation is a composition decision, not this module's. It is constructed with the service
that will be wired in at the final Standard candidate, and does nothing when none is supplied.
"""

from __future__ import annotations

from typing import Any

from src.application.chat_service import PreparedChatTurn
from src.application.policy_chat_service import ExternalDataPolicyChatService
from src.domain.runtime_entities import ChatTurn


class StandardContinuationChatService(ExternalDataPolicyChatService):
    def __init__(self, *args: Any, standard_continuation: Any = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._standard_continuation = standard_continuation

    def complete_turn(self, prepared: PreparedChatTurn, suffix: str) -> ChatTurn:
        completed = super().complete_turn(prepared, suffix)
        service = self._standard_continuation
        if service is None:
            return completed
        try:
            service.continue_pending(
                parent_turn_id=completed.id,
                thread_id=completed.thread_id,
            )
        except Exception:
            # The turn is already complete and delivered; a Standard failure must not turn a
            # safe answer into an error.
            return completed
        return self._refreshed(completed)

    def _refreshed(self, completed: ChatTurn) -> ChatTurn:
        service = self._standard_continuation
        repository = getattr(service, "repository", None)
        if repository is None:
            return completed
        try:
            refreshed = repository.get_chat_turn(completed.id)
        except Exception:
            return completed
        return refreshed or completed
