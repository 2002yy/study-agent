from __future__ import annotations

from src.application.closure_input_builder import build_structured_closure_input
from src.domain.runtime_entities import ChatTurn
from src.structured_closure import (
    normalize_structured_closure_result,
    structured_candidates_to_memory_updates,
)


def _completed_turn() -> ChatTurn:
    return ChatTurn(
        id="turn-project-1",
        thread_id="thread-project",
        status="completed",
        user_message="继续修复项目",
        assistant_message="已完成实现，测试仍有一项失败。",
        pedagogy_snapshot={"phase": "run_validation"},
    )


def test_project_closure_whitelists_and_bounds_committed_payload():
    turn = _completed_turn()
    structured = build_structured_closure_input(
        thread_id="thread-project",
        closure_eligibility="project_summary",
        task_contract={"task_intent": "project_execution"},
        learning_state={
            "protocol": "project_execution",
            "objective": "完成闭包功能",
            "phase": "run_validation",
            "payload": {
                "current_stage": "run_validation",
                "next_action": "修复剩余失败测试",
                "known_facts": ["后端测试通过", "前端类型检查失败"],
                "completed_deliverables": ["状态机", "API"],
                "failed_tests": ["frontend typecheck"],
                "blockers": ["测试类型定义"],
                "milestones": {"implementation": "completed", "validation": "blocked"},
                "project_validation_passed": False,
                "validation_required": True,
                "unknown_internal_field": "不得进入模型",
                "artifacts": [f"artifact-{index}" for index in range(30)],
            },
        },
        all_turns=[turn],
        completed_turns=[turn],
    )

    project = structured["committed_project_state"]
    assert structured["summary_kind"] == "project_closure"
    assert project["current_stage"] == "run_validation"
    assert project["failed_tests"] == ["frontend typecheck"]
    assert project["project_validation_passed"] is False
    assert project["validation_required"] is True
    assert "unknown_internal_field" not in project
    assert len(project["artifacts"]) == 20
    assert "project_state.failed_tests" in structured["allowed_source_refs"]
    assert "project_state.unknown_internal_field" not in structured["allowed_source_refs"]


def test_project_context_candidate_requires_project_source_and_freezes_target():
    normalized = normalize_structured_closure_result(
        {
            "candidates": [
                {
                    "target": "project_context",
                    "content": "实现已完成，验证仍被前端类型检查阻塞。",
                    "confidence": "high",
                    "source_refs": [
                        "project_state.completed_deliverables",
                        "project_state.failed_tests",
                        "project_state.blockers",
                    ],
                    "evaluation_refs": [],
                },
                {
                    "target": "project_context",
                    "content": "重复目标应被去重",
                    "confidence": "high",
                    "source_refs": ["turn:turn-project-1"],
                },
            ]
        },
        structured_input={
            "schema_version": "learning-closure-input-v1",
            "summary_kind": "project_closure",
            "allowed_source_refs": [
                "project_state.completed_deliverables",
                "project_state.failed_tests",
                "project_state.blockers",
                "turn:turn-project-1",
            ],
            "committed_project_state": {
                "completed_deliverables": ["状态机", "API"],
                "failed_tests": ["frontend typecheck"],
                "blockers": ["测试类型定义"],
                "project_validation_passed": False,
            },
            "final_pedagogy_evaluation": None,
        },
    )

    assert normalized["candidate_count"] == 1
    assert normalized["candidates"][0]["target"] == "project_context"
    assert normalized["candidates"][0]["confidence"] == "high"
    updates = structured_candidates_to_memory_updates(normalized)
    assert updates == [
        {
            "target": "project_context",
            "content": "实现已完成，验证仍被前端类型检查阻塞。",
            "append": True,
            "learner_pending": False,
            "confidence": "high",
            "source_refs": [
                "project_state.blockers",
                "project_state.completed_deliverables",
                "project_state.failed_tests",
            ],
            "evaluation_refs": [],
            "provenance_schema_version": "learning-closure-candidates-v1",
        }
    ]


def test_failed_project_validation_cannot_keep_high_confidence_pass_claim():
    normalized = normalize_structured_closure_result(
        {
            "candidates": [
                {
                    "target": "progress",
                    "content": "项目验证已通过",
                    "confidence": "high",
                    "source_refs": ["project_state.project_validation_passed"],
                    "evaluation_refs": [],
                }
            ]
        },
        structured_input={
            "schema_version": "learning-closure-input-v1",
            "summary_kind": "project_closure",
            "allowed_source_refs": ["project_state.project_validation_passed"],
            "committed_project_state": {"project_validation_passed": False},
            "final_pedagogy_evaluation": None,
        },
    )

    assert normalized["candidates"][0]["confidence"] == "medium"
