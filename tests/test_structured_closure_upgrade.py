from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.application.learning_closure_service import LearningClosureService
from src.application.memory_service import MemoryService
from src.application.session_service import SessionService
from src.domain.learning_closure import LearningClosureRun
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.learning_closure_repository import LearningClosureRepository
from src.repositories.memory_repository import MemoryRepository
from src.repositories.runtime_repository import RuntimeRepository


def _service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
    runtime.create_chat_thread(
        ChatThread(
            id="thread-upgrade",
            learning_state={
                "protocol": "socratic_rediscovery",
                "objective": "理解二分查找",
                "confirmed_points": ["区间减半"],
                "unresolved_gap": "边界条件",
                "phase": "guided_practice",
            },
        )
    )
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-upgrade-1",
            thread_id="thread-upgrade",
            status="completed",
            user_message="为什么是 O(log n)？",
            assistant_message="每轮把区间缩小一半。",
            role="nahida",
            mode="socratic",
            model="pro",
            route_snapshot={
                "task_contract": {
                    "task_intent": "learn",
                    "source_policy": "local_and_web",
                    "closure_eligibility": "learning_summary",
                    "learning_state_enabled": True,
                    "confidence": "high",
                }
            },
            pedagogy_snapshot={"phase": "guided_practice"},
        )
    )
    session_service = SessionService(
        runtime,
        current_dir=tmp_path / "current",
        archive_dir=tmp_path / "archive",
    )
    memory_service = MemoryService(MemoryRepository(database))
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
    calls: list[dict] = []

    def generator(structured_input, *args, **kwargs):
        calls.append(structured_input)
        return {
            "progress_update": "已确认区间减半",
            "learner_profile_update": "本轮无需更新",
            "current_focus_update": "继续练习边界条件",
            "revision_notes_update": "补充边界反例",
            "session_archive_update": "完成复杂度解释",
            "role_updates": "本轮无需更新",
        }

    service = LearningClosureService(
        LearningClosureRepository(database),
        session_service,
        memory_service,
        generator=generator,
        memory_bundle_loader=lambda _mode: {},
    )
    return service, runtime, calls


def test_g1_created_run_rebuilds_structured_input_before_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    service, _runtime, calls = _service(tmp_path, monkeypatch)
    snapshot, eligibility, source_hash = service._collect_source("thread-upgrade")
    legacy_snapshot = dict(snapshot)
    legacy_snapshot.pop("structured_input")
    legacy = service.repository.create(
        LearningClosureRun(
            id="closure-g1-created",
            thread_id="thread-upgrade",
            source_thread_version=snapshot["source_thread_version"],
            last_completed_turn_id=snapshot["last_completed_turn_id"],
            source_hash=source_hash,
            closure_eligibility=eligibility,
            status="created",
            committed_snapshot=legacy_snapshot,
        )
    )

    retried = service.retry(legacy.id)

    assert retried.status == "preview_ready"
    assert len(calls) == 1
    assert calls[0]["schema_version"] == "learning-closure-input-v1"
    assert calls[0]["committed_learning_state"]["confirmed_points"] == [
        "区间减半"
    ]
    assert "messages" not in calls[0]


def test_g1_retry_refuses_to_mix_changed_thread_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    service, runtime, calls = _service(tmp_path, monkeypatch)
    snapshot, eligibility, source_hash = service._collect_source("thread-upgrade")
    legacy_snapshot = dict(snapshot)
    legacy_snapshot.pop("structured_input")
    legacy = service.repository.create(
        LearningClosureRun(
            id="closure-g1-stale",
            thread_id="thread-upgrade",
            source_thread_version=snapshot["source_thread_version"],
            last_completed_turn_id=snapshot["last_completed_turn_id"],
            source_hash=source_hash,
            closure_eligibility=eligibility,
            status="failed",
            committed_snapshot=legacy_snapshot,
            error="old failure",
            reason="closure_generation_failed",
        )
    )
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-upgrade-2",
            thread_id="thread-upgrade",
            status="completed",
            user_message="新增问题",
            assistant_message="新增已提交回答",
            route_snapshot=legacy_snapshot["task_contract"],
        )
    )

    retried = service.retry(legacy.id)

    assert retried.status == "failed"
    assert "source changed" in retried.error
    assert calls == []
