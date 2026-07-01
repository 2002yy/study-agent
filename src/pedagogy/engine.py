from __future__ import annotations

from src.pedagogy.classifier import classify_knowledge
from src.pedagogy.direct import plan_direct
from src.pedagogy.feynman import plan_feynman
from src.pedagogy.project import plan_project
from src.pedagogy.socratic import plan_socratic
from src.pedagogy.evaluator import (
    evaluate_assistant_response,
    evaluate_learner_response,
)
from src.pedagogy.transition_policy import ModeTransitionPolicy
from src.pedagogy.types import (
    AssistantResponseEvaluation,
    LearningState,
    PedagogyTurnPlan,
)


class PedagogyEngine:
    def __init__(self):
        self.transitions = ModeTransitionPolicy()

    def plan(
        self, *, user_input: str, mode: str, state: LearningState,
    ) -> tuple[PedagogyTurnPlan, LearningState]:
        state = self.transitions.prepare(state, mode)
        kind = classify_knowledge(user_input)
        if mode == "苏格拉底":
            learner_evaluation = evaluate_learner_response(
                user_input, state=state
            )
            state = LearningState.from_dict(
                {
                    **state.to_dict(),
                    "payload": {
                        **state.payload,
                        "learner_response_evaluation": {
                            "passed": learner_evaluation.passed,
                            "is_claim": learner_evaluation.is_claim,
                            "reason": learner_evaluation.reason,
                            "misconceptions": list(learner_evaluation.misconceptions),
                        },
                    },
                }
            )
            return plan_socratic(user_input, kind, state)
        if mode == "费曼":
            return plan_feynman(user_input, kind, state)
        if mode == "项目":
            return plan_project(user_input, kind, state)
        return plan_direct(user_input, "direct_answer", kind, state)

    def evaluate_response(
        self,
        response: str,
        *,
        plan: PedagogyTurnPlan,
    ) -> AssistantResponseEvaluation:
        return evaluate_assistant_response(response, plan=plan)

    def apply_transition(
        self,
        *,
        before: LearningState,
        planned: LearningState,
        evaluation: AssistantResponseEvaluation,
    ) -> LearningState:
        if evaluation.passed:
            return planned
        return LearningState.from_dict(
            {
                **before.to_dict(),
                "payload": {
                    **before.payload,
                    "last_response_violations": list(evaluation.violations),
                },
            }
        )
