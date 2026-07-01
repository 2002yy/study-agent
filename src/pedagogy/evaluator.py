from __future__ import annotations

import re

from src.pedagogy.types import (
    AssistantResponseEvaluation,
    LearnerResponseEvaluation,
    LearningState,
    PedagogyTurnPlan,
)

BARE_UNDERSTANDING = {"我明白了", "懂了", "知道了", "原来如此", "明白"}


def evaluate_learner_response(
    text: str,
    *,
    state: LearningState,
) -> LearnerResponseEvaluation:
    normalized = text.strip().rstrip("。！!")
    if normalized in BARE_UNDERSTANDING:
        return LearnerResponseEvaluation(
            passed=False, is_claim=False, reason="understanding_asserted_without_reasoning"
        )
    is_claim = any(marker in text for marker in ("所以", "因此", "也就是说", "结论是"))
    if not is_claim:
        return LearnerResponseEvaluation(
            passed=False, is_claim=False, reason="no_conclusion_claim"
        )
    misconceptions: list[str] = []
    objective = state.objective.lower()
    lowered = text.lower().replace(" ", "")
    if ("二分" in objective or "binary" in objective) and (
        "o(n)" in lowered or "线性复杂度" in text
    ):
        misconceptions.append("binary_search_linear_complexity")
    has_reasoning = (
        len(normalized) >= 18
        and any(marker in text for marker in ("因为", "由于", "每次", "当", "如果", "意味着"))
    )
    if misconceptions:
        return LearnerResponseEvaluation(
            passed=False,
            is_claim=True,
            reason="claim_conflicts_with_known_constraints",
            misconceptions=tuple(misconceptions),
        )
    return LearnerResponseEvaluation(
        passed=has_reasoning,
        is_claim=True,
        reason="reasoned_claim" if has_reasoning else "claim_lacks_reasoning",
    )


def evaluate_assistant_response(
    response: str,
    *,
    plan: PedagogyTurnPlan,
) -> AssistantResponseEvaluation:
    violations: list[str] = []
    question_count = len(re.findall(r"[?？]", response))
    if plan.mode == "socratic_rediscovery" and question_count > 1:
        violations.append("multiple_central_questions")
    if not response.strip():
        violations.append("empty_response")
    if plan.disclosure_level <= 1 and any(
        marker in response for marker in ("完整答案是", "最终结论是", "直接答案是")
    ):
        violations.append("premature_conclusion_disclosure")
    return AssistantResponseEvaluation(
        passed=not violations,
        violations=tuple(violations),
        question_count=question_count,
    )
