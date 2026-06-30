from src.pedagogy.direct import plan_direct


def plan_project(user_input, knowledge_kind, state):
    return plan_direct(user_input, "project_execution", knowledge_kind, state)
