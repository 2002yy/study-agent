from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.application.closure_input_builder import build_structured_closure_input
from src.application.memory_service import MemoryService
from src.domain.runtime_entities import ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.pedagogy.evaluation import PedagogyEvalRun, SemanticEvaluation
from src.repositories.memory_repository import MemoryRepository
from src.structured_closure import (
    normalize_structured_closure_result,
    structured_candidates_to_memory_updates,
)


class FakeEvaluationRepository:
    def __init__(self, runs: dict[str, PedagogyEvalRun]):
        self.runs = runs

    def get_for_turn(self, turn_id: str) -> PedagogyEvalRun | None:
        return self.runs.get(turn_id)


def _turn(
    index: int,
    *,
    status: str = "completed",
    user: str | None = None,
    assistant: str | None = None,
) -> ChatTurn:
    return ChatTurn(
        id=f"turn-{index}",
        thread_id="thread-1",
        status=status,
        user_message=user if user is not None else f"user-{index}",
        assistant_message=assistant if assistant is not None else f"assistant-{index}",
        rag_snapshot={
            "results": [
                {
                    "chunk": {
                        "chunk_id": f"chunk-{index}",
                        "source_path": f"docs/{index}.md",
                    }
                }
            ]
        },
        pedagogy_snapshot={"phase": "guided_practice"},
    )


def _eval(*, decision: str = "accept") -> PedagogyEvalRun:
    return PedagogyEvalRun(
        id="ped-eval-final",
        learner_input="我的解释",
        objective="理解二分查找",
        protocol="socratic_rediscovery",
        expected_concepts=("区间减半",),
        evidence=("chunk-8",),
        deterministic_result={"is_claim": True},
        semantic_result=SemanticEvaluation(
            claims=("每轮区间减半",),
            correct_points=("区间减半",),
            gaps=("边界条件",),
            reasoning_complete=decision == "accept",
            transfer_ready=decision == "accept",
            confidence=0.9,
            evidence_refs=("chunk-8",),
        ),
        confidence=0.9,
        final_decision=decision,
        evaluator_version="pedagogy-eval-v-test",
        prompt_version="pedagogy-prompt-v-test",
        schema_version="7",
    )


def test_structured_input_uses_committed_truth_and_final_evaluation_only():
    completed = [_turn(index) for index in range(1, 9)]
    failed = _turn(
        9,
        status="interrupted",
        user="我已经完全掌握了",
        assistant="未提交回答",
    )
    structured = build_structured_closure_input(
        thread_id="thread-1",
        closure_eligibility="learning_summary",
        task_contract={"task_intent": "learn"},
        learning_state={
            "protocol": "socratic_rediscovery",
            "objective": "理解二分查找",
            "phase": "guided_practice",
            "confirmed_points": ["区间每轮减半"],
            "unresolved_gap": "边界条件",
            "planned_points": ["这不是 committed 字段"],
        },
        all_turns=[*completed, failed],
        completed_turns=completed,
        evaluation_repository=FakeEvaluationRepository({"turn-8": _eval()}),
        recent_turn_limit=3,
        dialogue_char_budget=1000,
    )

    committed = structured["committed_learning_state"]
    assert committed["confirmed_points"] == ["区间每轮减半"]
    assert "planned_points" not in committed
    assert structured["final_pedagogy_evaluation"]["id"] == "ped-eval-final"
    assert structured["final_pedagogy_evaluation"]["turn_id"] == "turn-8"
    assert structured["final_pedagogy_evaluation"]["evaluator_version"] == "pedagogy-eval-v-test"
    assert structured["final_pedagogy_evaluation"]["prompt_version"] == "pedagogy-prompt-v-test"
    assert structured["final_pedagogy_evaluation"]["schema_version"] == "7"
    assert [item["turn_id"] for item in structured["recent_dialogue"]] == [
        "turn-6",
        "turn-7",
        "turn-8",
    ]
    assert structured["excluded_uncommitted_turns"] == [
        {"turn_id": "turn-9", "status": "interrupted"}
    ]
    serialized_recent = str(structured["recent_dialogue"])
    assert "完全掌握" not in serialized_recent
    assert "pedagogy_eval:ped-eval-final" in structured["allowed_source_refs"]
    assert "evidence:chunk-8" in structured["allowed_source_refs"]


def test_structured_input_applies_character_budget_to_long_sessions():
    completed = [
        _turn(index, user="u" * 1400, assistant="a" * 1400)
        for index in range(1, 13)
    ]
    structured = build_structured_closure_input(
        thread_id="thread-1",
        closure_eligibility="learning_summary",
        task_contract={"task_intent": "learn"},
        learning_state={"objective": "长会话", "confirmed_points": []},
        all_turns=completed,
        completed_turns=completed,
        recent_turn_limit=6,
        dialogue_char_budget=1800,
        message_char_limit=900,
    )

    budget = structured["dialogue_budget"]
    assert budget["used_chars"] <= 1800
    assert budget["included_completed_turns"] <= 6
    assert budget["omitted_completed_turns"] >= 6
    assert budget["older_context_strategy"] == "dropped"
    assert len(str(structured["recent_dialogue"])) < 4000


def test_candidate_normalization_requires_allowed_provenance_and_pending_profile():
    structured_input = {
        "schema_version": "learning-closure-input-v1",
        "summary_kind": "learning_summary",
        "allowed_source_refs": [
            "learning_state.confirmed_points",
            "learning_state.unresolved_gap",
            "pedagogy_eval:ped-eval-final",
        ],
        "final_pedagogy_evaluation": {
            "id": "ped-eval-final",
            "final_decision": "reject",
        },
    }
    normalized = normalize_structured_closure_result(
        {
            "candidates": [
                {
                    "target": "progress",
                    "content": "已掌握区间减半",
                    "confidence": "high",
                    "source_refs": [
                        "learning_state.confirmed_points",
                        "unknown-source",
                    ],
                    "evaluation_refs": ["ped-eval-final", "other-eval"],
                },
                {
                    "target": "learner_profile",
                    "content": "更适合从反例学习",
                    "confidence": "medium",
                    "source_refs": ["learning_state.unresolved_gap"],
                    "learner_pending": False,
                },
                {
                    "target": "revision_notes",
                    "content": "无来源候选应删除",
                    "source_refs": ["unknown-source"],
                },
            ]
        },
        structured_input=structured_input,
    )

    assert normalized["candidate_count"] == 2
    progress, profile = normalized["candidates"]
    assert progress["confidence"] == "medium"
    assert progress["source_refs"] == ["learning_state.confirmed_points"]
    assert progress["evaluation_refs"] == ["ped-eval-final"]
    assert profile["learner_pending"] is True

    updates = structured_candidates_to_memory_updates(normalized)
    assert updates[0]["confidence"] == "medium"
    assert updates[0]["source_refs"] == ["learning_state.confirmed_points"]
    assert updates[1]["target"] == "learner_profile"
    assert updates[1]["learner_pending"] is True


def test_memory_run_freezes_candidate_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    service = MemoryService(MemoryRepository(database))
    modes = SimpleNamespace(
        memory_mode="confirm",
        safe_mode=False,
        profile=SimpleNamespace(memory_write_reason=""),
    )
    monkeypatch.setattr(
        "src.application.memory_service.is_memory_write_allowed", lambda _modes: True
    )

    run = service.create(
        [
            {
                "target": "learner_profile",
                "content": "更适合从反例学习",
                "append": True,
                "learner_pending": False,
                "confidence": "medium",
                "source_refs": ["turn:turn-8", "pedagogy_eval:ped-eval-final"],
                "evaluation_refs": ["ped-eval-final"],
                "provenance_schema_version": "learning-closure-candidates-v1",
            }
        ],
        runtime_modes=modes,
    )

    frozen = run.updates[0]
    assert frozen["learner_pending"] is True
    assert frozen["confidence"] == "medium"
    assert frozen["source_refs"] == [
        "pedagogy_eval:ped-eval-final",
        "turn:turn-8",
    ]
    assert run.preview["updates"][0]["evaluation_refs"] == ["ped-eval-final"]
