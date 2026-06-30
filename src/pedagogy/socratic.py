from __future__ import annotations

from dataclasses import replace

from src.pedagogy.types import LearningState, PedagogyTurnPlan

STUCK_MARKERS = ("不知道", "不会", "没思路", "想不出来", "卡住")
DIRECT_MARKERS = ("直接告诉我", "直接回答", "给我答案", "完整讲解", "停止引导")
REDISCOVERY_MARKERS = ("别直接告诉我", "不要直接告诉我", "不要马上给答案")
CONCLUSION_MARKERS = ("所以", "因此", "也就是说", "结论是", "我明白了")


def plan_socratic(
    user_input: str,
    knowledge_kind: str,
    state: LearningState,
) -> tuple[PedagogyTurnPlan, LearningState]:
    text = user_input.strip()
    next_count = state.turn_count + 1
    direct = (
        any(marker in text for marker in DIRECT_MARKERS)
        and not any(marker in text for marker in REDISCOVERY_MARKERS)
    )
    stuck = any(marker in text for marker in STUCK_MARKERS)
    concluded = state.turn_count > 0 and any(marker in text for marker in CONCLUSION_MARKERS)
    external = knowledge_kind in {"empirical", "conventional"}

    if direct:
        plan = PedagogyTurnPlan(
            mode="socratic_rediscovery", phase="direct_explanation",
            knowledge_kind=knowledge_kind, move="direct_explain", disclosure_level=5,
            learner_claim=text, target_understanding=state.objective,
            library_needed=external,
            constraints=("Respect the learner's explicit request for a direct answer.",),
        )
        return plan, replace(state, phase="direct_explanation", learner_claim=text, turn_count=next_count)

    if external:
        plan = PedagogyTurnPlan(
            mode="socratic_rediscovery", phase="library_fact",
            knowledge_kind=knowledge_kind, move="provide_library_fact", disclosure_level=3,
            learner_claim=text, unresolved_gap="This fact cannot be derived by introspection.",
            target_understanding=state.objective or text, library_needed=True,
            constraints=("State that the library supplies this external fact.",),
        )
        return plan, replace(
            state, objective=state.objective or text, phase="library_fact",
            learner_claim=text, unresolved_gap=plan.unresolved_gap, turn_count=next_count,
        )

    if stuck:
        hint_level = min(5, state.hint_level + 1)
        move = "test_example" if hint_level == 1 else "give_hint"
        plan = PedagogyTurnPlan(
            mode="socratic_rediscovery", phase="scaffold",
            knowledge_kind=knowledge_kind, move=move,
            disclosure_level=min(4, hint_level + 1),
            learner_claim=state.learner_claim,
            unresolved_gap=state.unresolved_gap or "The learner cannot continue the current inference.",
            target_understanding=state.objective,
            constraints=("Increase help by one step; do not jump straight to the full answer.",),
        )
        return plan, replace(state, phase="scaffold", hint_level=hint_level, turn_count=next_count)

    if concluded:
        plan = PedagogyTurnPlan(
            mode="socratic_rediscovery", phase="transfer",
            knowledge_kind=knowledge_kind, move="transfer", disclosure_level=2,
            learner_claim=text, target_understanding=state.objective,
            constraints=("Briefly summarize the reconstructed path, then test one new situation.",),
        )
        return plan, replace(
            state, phase="transfer", learner_claim=text,
            confirmed_points=(*state.confirmed_points, text), turn_count=next_count,
        )

    if state.turn_count == 0:
        move = "elicit_claim"
        phase = "orientation"
    elif state.phase in {"orientation", "scaffold"}:
        move = "test_example"
        phase = "test_assumption"
    else:
        move = "offer_counterexample"
        phase = "test_assumption"
    plan = PedagogyTurnPlan(
        mode="socratic_rediscovery", phase=phase,
        knowledge_kind=knowledge_kind, move=move, disclosure_level=1,
        learner_claim=text if state.turn_count else "",
        unresolved_gap=state.unresolved_gap,
        target_understanding=state.objective or text,
        constraints=("Use one concrete central question and one cognitive move only.",),
    )
    return plan, replace(
        state, objective=state.objective or text, phase=phase,
        learner_claim=text if state.turn_count else state.learner_claim, turn_count=next_count,
    )
