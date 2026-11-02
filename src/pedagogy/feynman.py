from __future__ import annotations

from dataclasses import replace

from src.pedagogy.intent import requests_direct_answer, requests_thinking_time
from src.pedagogy.types import (
    KnowledgeKind,
    LearningState,
    PedagogicalMove,
    PedagogyTurnPlan,
)


def plan_feynman(
    user_input: str,
    knowledge_kind: KnowledgeKind,
    state: LearningState,
) -> tuple[PedagogyTurnPlan, LearningState]:
    text = user_input.strip()
    payload = dict(state.payload)
    count = state.turn_count + 1
    if requests_direct_answer(text):
        return PedagogyTurnPlan(
            mode="feynman_diagnosis",
            phase="direct_explanation",
            knowledge_kind=knowledge_kind,
            move="direct_explain",
            disclosure_level=5,
            target_understanding=state.objective or text,
            constraints=(
                "Respect the request for a complete explanation; do not require re-explanation this turn.",
            ),
        ), replace(state, phase="direct_explanation", turn_count=count)
    # ChatService supplies the existing evaluator's receipt for this input.
    # A phase, text length, or transition word is not evidence of understanding.
    evaluation = payload.get("pedagogy_evaluation", {})
    accepted = (
        evaluation.get("final_decision") == "accept"
        and evaluation.get("learner_input") == user_input
        and evaluation.get("objective") == state.objective
        and evaluation.get("protocol") == state.protocol
    )
    move: PedagogicalMove
    if requests_thinking_time(text):
        phase, move, level = "test_assumption", "request_prediction", 1
    elif accepted:
        phase, move, level = "complete", "close_stage", 4
        payload["transfer_passed"] = True
        payload["transfer_evidence"] = text
    else:
        phase, move, level = "answer", "reconstruct", 4
    plan = PedagogyTurnPlan(
        mode="feynman_diagnosis",
        phase=phase,
        knowledge_kind=knowledge_kind,
        move=move,
        disclosure_level=level,
        target_understanding=state.objective or text,
        constraints=(
            "Build intuition, explain causal mechanisms simply, then add precise terms and boundaries as needed.",
            "If the learner offers an explanation, examine its actual reasoning; do not presume a gap or require recitation.",
            "Invite exploration or re-explanation only when useful. Honor an explicit request to think before revealing the answer.",
        ),
    )
    return plan, replace(
        state,
        phase=phase,
        objective=state.objective or text,
        turn_count=count,
        payload=payload,
    )
