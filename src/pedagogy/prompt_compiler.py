from __future__ import annotations

from src.pedagogy.types import LearningState, PedagogyTurnPlan


def format_turn_plan(plan: PedagogyTurnPlan, state: LearningState) -> str:
    constraints = "\n".join(f"- {item}" for item in plan.constraints) or "- None"
    return f"""[Pedagogy turn plan]
Protocol: {plan.mode}
Current phase: {plan.phase}
Knowledge kind: {plan.knowledge_kind}
This turn's single cognitive move: {plan.move}
Disclosure level: L{plan.disclosure_level}
Learning objective: {plan.target_understanding or state.objective or "(discover with learner)"}
Learner claim: {plan.learner_claim or state.learner_claim or "(not elicited yet)"}
Unresolved gap: {plan.unresolved_gap or state.unresolved_gap or "(not established yet)"}
Constraints:
{constraints}

Follow this plan over any role-level teaching habit. The role controls voice and emphasis only."""
