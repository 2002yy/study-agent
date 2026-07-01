from __future__ import annotations

from dataclasses import replace

from src.pedagogy.types import PedagogyTurnPlan

STAGES = (
    "define", "inspect", "diagnose", "decide",
    "implement", "verify", "stabilize", "deliver",
)


def plan_project(user_input, knowledge_kind, state):
    text = user_input.strip()
    payload = dict(state.payload)
    stage = str(payload.get("current_stage") or "define")
    if any(marker in text.lower() for marker in ("报错", "日志", "复现", "bug")):
        stage, move = "diagnose", "form_hypothesis"
        payload["known_facts"] = [text]
    elif any(marker in text for marker in ("开始改", "实现", "写代码", "应用补丁")):
        stage, move = "implement", "apply_patch"
    elif any(marker in text for marker in ("测试", "验证", "验收")):
        stage, move = "verify", "run_validation"
    elif any(marker in text for marker in ("完成", "交付", "收尾")):
        stage, move = "deliver", "close_stage"
    elif state.turn_count == 0:
        stage, move = "define", "define_acceptance"
    elif stage == "define":
        stage, move = "inspect", "inspect_artifact"
    elif stage == "diagnose":
        stage, move = "decide", "choose_solution"
    else:
        move = "inspect_artifact"
    payload["current_stage"] = stage
    payload["next_action"] = move
    if not payload.get("objective"):
        payload["objective"] = text
    plan = PedagogyTurnPlan(
        mode="project_execution",
        phase=stage,
        knowledge_kind=knowledge_kind,
        move=move,
        disclosure_level=5,
        learner_claim=text,
        target_understanding=str(payload.get("objective", text)),
        library_needed=knowledge_kind in {"diagnostic", "procedural"},
        constraints=(
            "Advance one verifiable project state change.",
            "Use real artifacts and include validation; do not replace action with generic advice.",
        ),
    )
    return plan, replace(
        state,
        phase=stage,
        objective=str(payload["objective"]),
        learner_claim=text,
        turn_count=state.turn_count + 1,
        payload=payload,
    )
