from __future__ import annotations

from src.pedagogy.classifier import classify_knowledge
from src.pedagogy.direct import plan_direct
from src.pedagogy.feynman import plan_feynman
from src.pedagogy.project import plan_project
from src.pedagogy.socratic import plan_socratic
from src.pedagogy.types import LearningState, PedagogyTurnPlan


class PedagogyEngine:
    def plan(
        self, *, user_input: str, mode: str, state: LearningState,
    ) -> tuple[PedagogyTurnPlan, LearningState]:
        kind = classify_knowledge(user_input)
        if mode == "苏格拉底":
            return plan_socratic(user_input, kind, state)
        if mode == "费曼":
            return plan_feynman(user_input, kind, state)
        if mode == "项目":
            return plan_project(user_input, kind, state)
        return plan_direct(user_input, "direct_answer", kind, state)
