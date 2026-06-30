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
