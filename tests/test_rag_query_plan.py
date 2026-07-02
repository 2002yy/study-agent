from src.pedagogy.types import LearningState, PedagogyTurnPlan
from src.rag.query_plan import build_retrieval_query_plan


def test_weak_turn_uses_learning_objective_and_gap_for_private_query():
    plan = build_retrieval_query_plan(
        "不知道",
        state=LearningState(
            protocol="socratic_rediscovery",
            objective="理解二分查找复杂度",
            unresolved_gap="每次减半与对数次数的关系",
        ),
        plan=PedagogyTurnPlan(
            mode="socratic_rediscovery",
            phase="test_assumption",
            knowledge_kind="derivable",
            move="give_hint",
            disclosure_level=1,
            target_understanding="理解二分查找复杂度",
            unresolved_gap="每次减半与对数次数的关系",
        ),
    )

    assert plan.force_retrieval is True
    assert "二分查找" in plan.private_query
    assert "每次减半" in plan.private_query
    assert "不知道" not in plan.private_query


def test_specific_user_input_is_kept_with_pedagogy_context():
    plan = build_retrieval_query_plan(
        "为什么循环条件是 left <= right",
        state=LearningState(protocol="socratic_rediscovery"),
        plan=PedagogyTurnPlan(
            mode="socratic_rediscovery",
            phase="orientation",
            knowledge_kind="derivable",
            move="elicit_claim",
            disclosure_level=0,
            target_understanding="理解二分查找边界",
        ),
    )

    assert "left <= right" in plan.private_query
    assert "二分查找边界" in plan.private_query
