"""Trusted opt-in answer adapter; generated text remains provisional."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.application.conversation_answer_input import AnswerInput
from src.application.conversation_answer_runner import (
    AnswerLimits,
    AnswerResult,
    AnswerTransport,
    generate_conversation_answer,
)
from src.application.conversation_decision import DecisionContext
from src.application.conversation_decision_runner import DecisionAdmission


class AnswerGenerationError(RuntimeError):
    """Sanitized runner receipt for a trusted caller; no provider exception."""

    def __init__(self, result: AnswerResult) -> None:
        self.result = result
        super().__init__(f"answer generation stopped: {result.status}")


@dataclass(frozen=True)
class BoundedAnswerGenerator:
    transport: AnswerTransport
    budget: DecisionAdmission
    limits: AnswerLimits = AnswerLimits()

    def __post_init__(self) -> None:
        if (
            not callable(self.transport)
            or not callable(getattr(self.budget, "reserve", None))
            or not isinstance(self.limits, AnswerLimits)
        ):
            raise ValueError("invalid answer generator")

    async def generate(
        self,
        value: AnswerInput,
        *,
        current_context: Callable[[], DecisionContext],
    ) -> str:
        """Generate or stop; never turn a failed receipt into answer content.

        The loop supplies its own projected fresh-context reader. The original
        dispatch still controls the total stage deadline and outer cancellation.
        Deployment adapters own real spend and evidence/publication checks.
        """
        result = await generate_conversation_answer(
            value,
            current_context=current_context,
            transport=self.transport,
            budget=self.budget,
            limits=self.limits,
        )
        if result.status != "completed":
            raise AnswerGenerationError(result)
        return result.answer
