from __future__ import annotations

from dataclasses import replace

from src.pedagogy.types import LearningState, PedagogyTurnPlan


def plan_direct(user_input: str, mode: str, knowledge_kind: str, state: LearningState):
    plan = PedagogyTurnPlan(
        mode=mode, phase="answer", knowledge_kind=knowledge_kind,
        move="direct_explain", disclosure_level=5,
        target_understanding=user_input,
        library_needed=knowledge_kind in {"empirical", "conventional", "diagnostic"},
    )
    return plan, replace(state, phase="answer", turn_count=state.turn_count + 1)
