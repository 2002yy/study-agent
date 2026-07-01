from __future__ import annotations

from src.mode_manager import RuntimeModes
from src.application.session_service import SessionService
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.pedagogy.engine import PedagogyEngine
from src.pedagogy.evidence import EvidenceDisclosurePolicy
from src.pedagogy.types import LearningState
from src.router import route_request
from src.repositories.runtime_repository import RuntimeRepository


def route(text: str) -> dict:
    return route_request(
        user_input=text,
        selected_role="auto",
        selected_mode="auto",
        selected_model="auto",
        runtime_modes=RuntimeModes(route_mode="auto_rule"),
    )


def test_why_question_routes_to_normal_deep_explanation():
    result = route("为什么负负得正？")
    assert result["mode"] == "普通"
    assert result["model_profile"] == "pro"


def test_explicit_rediscovery_intent_routes_to_socratic():
    result = route("别直接告诉我，引导我推出负负得正")
    assert result["mode"] == "苏格拉底"


def test_explicit_behavior_transition_overrides_sticky_mode():
    result = route_request(
        user_input="我来讲一遍，你检查我理解",
        selected_role="auto",
        selected_mode="auto",
        selected_model="auto",
        runtime_modes=RuntimeModes(route_mode="auto_rule"),
        previous_mode="苏格拉底",
    )
    assert result["mode"] == "费曼"
    assert result["explicit_mode_intent"] is True
    assert result["behavior_transition"] is True
    assert result["sticky_mode_applied"] is False


def test_first_stuck_turn_scaffolds_without_full_answer():
    engine = PedagogyEngine()
    _, state = engine.plan(
        user_input="别直接告诉我，引导我理解二分查找",
        mode="苏格拉底",
        state=LearningState(),
    )
    plan, next_state = engine.plan(
        user_input="不知道",
        mode="苏格拉底",
        state=state,
    )
    assert plan.move == "test_example"
    assert plan.disclosure_level < 5
    assert next_state.hint_level == 1


def test_repeated_stuck_turn_increases_hint_level():
    engine = PedagogyEngine()
    state = LearningState(objective="二分查找", turn_count=1, hint_level=1)
    plan, next_state = engine.plan(
        user_input="还是不知道",
        mode="苏格拉底",
        state=state,
    )
    assert plan.move == "give_hint"
    assert next_state.hint_level == 2
    assert plan.disclosure_level == 3


def test_external_fact_is_supplied_by_library_not_guessed():
    plan, _ = PedagogyEngine().plan(
        user_input="这篇论文是哪一年发表的？",
        mode="苏格拉底",
        state=LearningState(),
    )
    assert plan.knowledge_kind == "empirical"
    assert plan.move == "provide_library_fact"
    assert plan.library_needed is True
    assert plan.disclosure_level >= 3


def test_wrong_assumption_progresses_to_counterexample():
    plan, _ = PedagogyEngine().plan(
        user_input="索引总是让查询更快",
        mode="苏格拉底",
        state=LearningState(
            objective="理解索引边界",
            phase="test_assumption",
            turn_count=2,
        ),
    )
    assert plan.move == "offer_counterexample"


def test_rag_answer_is_withheld_until_current_move_needs_it():
    policy = EvidenceDisclosurePolicy()
    engine = PedagogyEngine()
    plan, _ = engine.plan(
        user_input="引导我理解为什么负负得正",
        mode="苏格拉底",
        state=LearningState(),
    )
    disclosed = policy.select(context="完整答案：负负得正因为……", plan=plan)
    assert disclosed.context == ""
    assert disclosed.policy == "withheld_derivable_answer"


def test_evidence_policy_selects_whole_units_without_character_truncation():
    from src.pedagogy.evidence import EvidenceUnit

    unit = EvidenceUnit(
        source_id="doc-1",
        type="definition",
        content="D" * 5000,
        citation="book.md:L1-L20",
        disclosure_role="necessary_fact",
        reliability=0.95,
    )
    plan, _ = PedagogyEngine().plan(
        user_input="这项术语的定义是什么？",
        mode="苏格拉底",
        state=LearningState(protocol="socratic_rediscovery"),
    )
    disclosed = EvidenceDisclosurePolicy().select(units=[unit], plan=plan)
    assert "D" * 5000 in disclosed.context
    assert disclosed.units[0]["citation"] == "book.md:L1-L20"


def test_direct_answer_override_exits_guidance():
    plan, _ = PedagogyEngine().plan(
        user_input="直接告诉我完整答案",
        mode="苏格拉底",
        state=LearningState(objective="负负得正", turn_count=3),
    )
    assert plan.move == "direct_explain"
    assert plan.disclosure_level == 5


def test_learner_conclusion_moves_to_transfer():
    plan, state = PedagogyEngine().plan(
        user_input="所以每次减半，k 次后 n/2^k=1，因此 k=log n",
        mode="苏格拉底",
        state=LearningState(objective="二分查找复杂度", turn_count=3),
    )
    assert plan.move == "transfer"
    assert state.phase == "transfer"


def test_wrong_conclusion_does_not_enter_transfer_or_confirm_point():
    plan, state = PedagogyEngine().plan(
        user_input="所以二分查找是 O(n)，因为每次只检查一个元素，我明白了。",
        mode="苏格拉底",
        state=LearningState(
            protocol="socratic_rediscovery",
            objective="理解二分查找复杂度",
            turn_count=3,
        ),
    )
    assert plan.move == "surface_contradiction"
    assert plan.phase == "test_assumption"
    assert state.confirmed_points == ()


def test_mode_transition_isolates_and_restores_protocol_payload():
    engine = PedagogyEngine()
    socratic = LearningState(
        protocol="socratic_rediscovery",
        objective="索引边界",
        phase="scaffold",
        hint_level=2,
        turn_count=4,
        payload={"path": "counterexample"},
    )
    feynman_plan, feynman = engine.plan(
        user_input="我来讲一遍，你检查我理解",
        mode="费曼",
        state=socratic,
    )
    assert feynman.protocol == "feynman_diagnosis"
    assert feynman.hint_level == 0
    assert feynman_plan.mode == "feynman_diagnosis"

    _, restored = engine.plan(
        user_input="继续引导我",
        mode="苏格拉底",
        state=feynman,
    )
    assert restored.protocol == "socratic_rediscovery"
    assert restored.hint_level == 2
    assert restored.payload["path"] == "counterexample"


def test_feynman_protocol_repairs_one_unconditional_gap():
    plan, state = PedagogyEngine().plan(
        user_input="索引像目录，所以任何查询一定都会更快。",
        mode="费曼",
        state=LearningState(protocol="feynman_diagnosis"),
    )
    assert plan.phase == "repair"
    assert plan.move == "minimal_repair"
    assert state.payload["current_gap"]
    assert state.payload["repair_given"] == "counterexample"


def test_feynman_transfer_records_evidence_before_closing():
    plan, state = PedagogyEngine().plan(
        user_input="因为输入为空时没有元素，所以这个边界情况应直接返回空结果。",
        mode="费曼",
        state=LearningState(
            protocol="feynman_diagnosis",
            objective="解释空输入边界",
            phase="transfer",
            payload={"repair_given": "boundary", "reexplanation_passed": True},
        ),
    )
    assert plan.phase == "complete"
    assert state.payload["transfer_passed"] is True
    assert state.payload["transfer_evidence"]


def test_project_protocol_advances_to_verification():
    plan, state = PedagogyEngine().plan(
        user_input="代码已修改，现在运行测试验证回归",
        mode="项目",
        state=LearningState(
            protocol="project_execution",
            objective="修复滚动跳顶",
            phase="implement",
            turn_count=3,
            payload={"current_stage": "implement"},
        ),
    )
    assert plan.phase == "verify"
    assert plan.move == "run_validation"
    assert state.payload["current_stage"] == "verify"


def test_project_cannot_deliver_without_validation_evidence():
    plan, state = PedagogyEngine().plan(
        user_input="已经完成，可以交付收尾了",
        mode="项目",
        state=LearningState(
            protocol="project_execution",
            objective="修复滚动跳顶",
            phase="implement",
            payload={"current_stage": "implement"},
        ),
    )
    assert plan.phase == "verify"
    assert plan.move == "run_validation"
    assert state.payload["validation_required"] is True


def test_failed_assistant_contract_does_not_commit_planned_progress():
    engine = PedagogyEngine()
    before = LearningState(
        protocol="socratic_rediscovery",
        objective="二分查找",
        phase="orientation",
        turn_count=1,
    )
    plan, planned = engine.plan(
        user_input="我觉得每次能排除一半",
        mode="苏格拉底",
        state=before,
    )
    evaluation = engine.evaluate_response(
        "你认为剩多少？为什么？还能举例吗？",
        plan=plan,
    )
    committed = engine.apply_transition(
        before=before,
        planned=planned,
        evaluation=evaluation,
    )
    assert evaluation.passed is False
    assert committed.phase == before.phase
    assert committed.turn_count == before.turn_count


def test_session_refresh_restores_same_learning_phase(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = RuntimeRepository(database)
    thread = repository.create_chat_thread(ChatThread())
    operation_id = "op_pedagogy"
    repository.acquire_chat_operation(thread.id, operation_id)
    state = LearningState(
        objective="二分查找复杂度",
        phase="test_assumption",
        learner_claim="每次排除一半",
        hint_level=1,
        turn_count=2,
    )
    repository.add_chat_turn(
        ChatTurn(
            thread_id=thread.id,
            user_message="还剩多少？",
            assistant_message="试试 16 个元素。",
            status="completed",
            role="nahida",
            mode="苏格拉底",
            operation_id=operation_id,
            pedagogy_snapshot={"phase": "test_assumption", "move": "test_example"},
        )
    )
    repository.update_chat_thread_learning_state(
        thread.id, state.to_dict(), operation_id=operation_id
    )
    repository.release_chat_operation(thread.id, operation_id)

    refreshed = SessionService(
        RuntimeRepository(database),
        current_dir=tmp_path / "current",
        archive_dir=tmp_path / "archive",
    ).get_session(thread.id)

    assert refreshed is not None
    assert refreshed["learning_state"]["phase"] == "test_assumption"
    assert refreshed["pedagogy"]["move"] == "test_example"
