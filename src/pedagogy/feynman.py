from __future__ import annotations

from dataclasses import replace

from src.pedagogy.types import PedagogyTurnPlan


def plan_feynman(user_input, knowledge_kind, state):
    text = user_input.strip()
    payload = dict(state.payload)
    count = state.turn_count + 1
    re_explanation = bool(payload.get("repair_given"))
    transfer_passed = bool(payload.get("transfer_passed"))
    if transfer_passed:
        phase, move, level = "complete", "close_stage", 2
    elif state.phase == "transfer" and len(text) >= 18:
        phase, move, level = "complete", "close_stage", 2
        payload["transfer_passed"] = True
        payload["transfer_evidence"] = text
    elif re_explanation and any(marker in text for marker in ("现在", "重新", "也就是说", "所以")):
        phase, move, level = "transfer", "transfer_test", 2
        payload["latest_explanation"] = text
        payload["reexplanation_passed"] = True
    elif state.phase == "repair":
        phase, move, level = "re_explain", "request_reexplanation", 3
    elif state.turn_count == 0 and len(text) < 18:
        phase, move, level = "elicit", "invite_explanation", 0
    else:
        phase, move, level = "diagnose", "identify_main_gap", 2
        payload["latest_explanation"] = text
        payload["explanation_version"] = int(payload.get("explanation_version", 0)) + 1
        payload["current_gap"] = "Identify the single most important unexplained term, causal break, or missing boundary."

    if phase == "diagnose" and any(marker in text for marker in ("所有", "一定", "总是", "任何")):
        phase, move, level = "repair", "minimal_repair", 2
        payload["current_gap"] = "The explanation uses an unconditional claim without testing its boundary."
        payload["repair_given"] = "counterexample"
    plan = PedagogyTurnPlan(
        mode="feynman_diagnosis",
        phase=phase,
        knowledge_kind=knowledge_kind,
        move=move,
        disclosure_level=level,
        learner_claim=text,
        unresolved_gap=str(payload.get("current_gap", "")),
        target_understanding=state.objective or text,
        constraints=(
            "Acknowledge one valid point, address one main gap, and require re-explanation.",
            "Do not score or list every flaw.",
        ),
    )
    return plan, replace(
        state,
        phase=phase,
        objective=state.objective or text,
        learner_claim=text,
        unresolved_gap=str(payload.get("current_gap", "")),
        turn_count=count,
        payload=payload,
    )
