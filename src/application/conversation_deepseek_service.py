"""Opt-in application entrypoint; no production chat or publication cutover."""

from __future__ import annotations

from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Mapping

from src.application.conversation_action_dispatch import ActionBudget, ActionHandler
from src.application.conversation_answer_runner import AnswerLimits
from src.application.conversation_bounded_loop import (
    LoopEvent,
    LoopLimits,
    run_conversation_loop,
)
from src.application.conversation_decision import ConversationAction, DecisionContext
from src.application.conversation_decision_runner import DecisionAdmission
from src.application.conversation_deepseek_session import (
    DeepSeekConversationSession,
    DeepSeekConversationSettings,
)
from src.application.conversation_loop_session import ConversationLoopSession


@dataclass(frozen=True)
class DeepSeekConversationService:
    settings: DeepSeekConversationSettings
    client_factory: Callable[..., Any] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.settings, DeepSeekConversationSettings) or (
            self.client_factory is not None and not callable(self.client_factory)
        ):
            raise ValueError("invalid DeepSeek conversation service")

    def start(
        self,
        context: DecisionContext,
        *,
        current_context: Callable[[], DecisionContext],
        model_budget: DecisionAdmission,
        action_budget: ActionBudget,
        handlers: Mapping[ConversationAction, ActionHandler],
        loop_limits: LoopLimits = LoopLimits(),
        answer_limits: AnswerLimits = AnswerLimits(),
    ) -> ConversationLoopSession:
        """Create a lazy single-consumer run using one shared model admission.

        The host supplies owned snapshots, tool permissions and durable/real
        spend authority. Creating/claiming/closing an unread run makes no SDK
        client or model request. Read with aclosing(run.events()) so disconnect
        and cancellation close the nested loop before its owned SDK session.
        """
        if (
            not isinstance(context, DecisionContext)
            or not callable(current_context)
            or not isinstance(action_budget, ActionBudget)
            or not isinstance(loop_limits, LoopLimits)
            or not isinstance(answer_limits, AnswerLimits)
        ):
            raise ValueError("invalid conversation service request")
        bound_handlers = dict(handlers)

        async def events() -> AsyncGenerator[LoopEvent, None]:
            async with DeepSeekConversationSession(
                self.settings, client_factory=self.client_factory
            ) as models:
                async with aclosing(
                    run_conversation_loop(
                        context,
                        current_context=current_context,
                        transport=models.transport,
                        decision_budget=model_budget,
                        action_budget=action_budget,
                        handlers=bound_handlers,
                        limits=loop_limits,
                        answer_generator=models.answer_generator(
                            model_budget, answer_limits
                        ),
                    )
                ) as stream:
                    async for event in stream:
                        yield event

        return ConversationLoopSession(context.request_id, events())
