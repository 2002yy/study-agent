from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.application.learning_closure_service import LearningClosureService
from src.application.memory_service import MemoryService
from src.application.session_service import SessionService
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.learning_closure_repository import LearningClosureRepository
from src.repositories.memory_repository import MemoryRepository
from src.repositories.runtime_repository import RuntimeRepository
from src.structured_closure import (
    generate_structured_closure_candidates,
    normalize_structured_closure_result,
)


def test_generator_uses_frozen_memory_context_instead_of_live_bundle(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict = {}

    def fake_chat(messages, **kwargs):
        captured.update(json.loads(messages[1]["content"]))
        return json.dumps(
            {
                "candidates": [
                    {
                        "target": "progress",
                        "content": "沿用已确认的旧进度",
                        "confidence": "high",
                        "source_refs": ["memory:progress.md"],
                        "evaluation_refs": [],
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("src.structured_closure.chat", fake_chat)
    result = generate_structured_closure_candidates(
        {
            "schema_version": "learning-closure-input-v1",
            "summary_kind": "learning_summary",
            "allowed_source_refs": ["memory:progress.md"],
            "memory_context": {"progress.md": "冻结进度"},
            "final_pedagogy_evaluation": None,
        },
        {"progress.md": "生成前被修改的实时进度"},
        "nahida",
        "socratic",
    )

    assert captured["memory_context"] == {"progress.md": "冻结进度"}
    assert "生成前被修改" not in json.dumps(captured, ensure_ascii=False)
    assert result["candidates"][0]["confidence"] == "high"


def test_progress_high_confidence_requires_confirmed_or_accepted_source():
    normalized = normalize_structured_closure_result(
        {
            "candidates": [
                {
                    "target": "progress",
                    "content": "正在推进目标",
                    "confidence": "high",
                    "source_refs": ["learning_state.objective"],
                    "evaluation_refs": [],
                }
            ]
        },
        structured_input={
            "schema_version": "learning-closure-input-v1",
            "summary_kind": "learning_summary",
            "allowed_source_refs": ["learning_state.objective"],
            "final_pedagogy_evaluation": None,
        },
    )

    assert normalized["candidates"][0]["confidence"] == "medium"


def test_service_freezes_existing_memory_files_in_committed_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
    runtime.create_chat_thread(
        ChatThread(
            id="thread-memory-freeze",
            learning_state={
                "protocol": "socratic_rediscovery",
                "objective": "理解索引",
                "confirmed_points": ["B+ 树适合范围查询"],
                "unresolved_gap": "联合索引顺序",
            },
        )
    )
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-memory-freeze",
            thread_id="thread-memory-freeze",
            status="completed",
            user_message="为什么使用 B+ 树？",
            assistant_message="叶子节点有序，适合范围查询。",
            route_snapshot={
                "task_contract": {
                    "task_intent": "learn",
                    "source_policy": "local_and_web",
                    "closure_eligibility": "learning_summary",
                    "learning_state_enabled": True,
                }
            },
        )
    )
    modes = SimpleNamespace(
        memory_mode="confirm",
        safe_mode=False,
        profile=SimpleNamespace(memory_write_reason=""),
    )
    monkeypatch.setattr(
        "src.application.memory_service.load_runtime_modes", lambda: modes
    )
    monkeypatch.setattr(
        "src.application.memory_service.is_memory_write_allowed", lambda _modes: True
    )
    seen: list[dict] = []

    def generator(structured_input, memory_bundle, *args, **kwargs):
        seen.append({"input": structured_input, "bundle": memory_bundle})
        return {
            "progress_update": "已确认 B+ 树范围查询优势",
            "learner_profile_update": "本轮无需更新",
            "current_focus_update": "继续学习联合索引",
            "revision_notes_update": "补充最左匹配原则",
            "session_archive_update": "完成索引结构学习",
            "role_updates": "本轮无需更新",
        }

    service = LearningClosureService(
        LearningClosureRepository(database),
        SessionService(
            runtime,
            current_dir=tmp_path / "current",
            archive_dir=tmp_path / "archive",
        ),
        MemoryService(MemoryRepository(database)),
        generator=generator,
        memory_bundle_loader=lambda _mode: {
            "progress.md": "冻结的历史进度",
            "current_focus.md": "冻结的当前重点",
            "learner_profile.md": "[文件不存在: learner_profile.md]",
        },
    )

    run = service.create_and_execute("thread-memory-freeze")

    structured = run.committed_snapshot["structured_input"]
    assert structured["memory_context"] == {
        "progress.md": "冻结的历史进度",
        "current_focus.md": "冻结的当前重点",
    }
    assert "memory:progress.md" in structured["allowed_source_refs"]
    assert "memory:learner_profile.md" not in structured["allowed_source_refs"]
    assert seen[0]["bundle"] == structured["memory_context"]
