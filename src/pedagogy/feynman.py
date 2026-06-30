from src.pedagogy.direct import plan_direct


def plan_feynman(user_input, knowledge_kind, state):
    plan, next_state = plan_direct(user_input, "feynman_diagnosis", knowledge_kind, state)
    return plan.__class__(**{**plan.to_dict(), "phase": "diagnose", "move": "reconstruct", "disclosure_level": 2}), next_state
