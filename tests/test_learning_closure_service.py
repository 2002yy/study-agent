from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.application.learning_closure_service import (
    LearningClosureNotEligible,
    LearningClosureService,
)
from src.application.memory_service import MemoryService
from src.application.session_service import SessionService
from src.domain.learning_closure import LearningClosureRun
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.learning_closure_repository import LearningClosureRepository
from src.repositories.memory_repository import MemoryRepository
from src.repositories.runtime_repository import RuntimeRepository


def _task_contract(intent: str, closure: str, *, learning: bool) -> dict:
    return {
        "task_intent": intent,
        "source_policy": "local_and_web",
        "closure_eligibility": closure,
        "learning_state_enabled": learning,
        "confidence": "high",
    }


def _build_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    contract: dict | None = None,
    generator=None,
    memory_service=None,
):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime_repository = RuntimeRepository(database)
    thread = runtime_repository.create_chat_thread(
        ChatThread(
            id="thread-1",
            learning_state={
                "protocol": "socratic_rediscovery",
                "objective": "理解二分查找复杂度",
                "confirmed_points": ["区间每轮减半"],
                "unresolved_gap": "边界条件",
                "phase": "guided_practice",
            },
        )
    )
    runtime_repository.add_chat_turn(
        ChatTurn(
            id="turn-1",
            thread_id=thread.id,
            user_message="为什么是 O(log n)？",
            assistant_message="因为每轮把搜索区间缩小一半。",
            status="completed",
            role="nahida",
            mode="socratic",
            model="pro",
            route_snapshot={
                "task_contract": contract
                or _task_contract("learn", "learning_summary", learning=True)
            },
            pedagogy_snapshot={"phase": "guided_practice"},
        )
    )
    session_service = SessionService(
        runtime_repository,
        current_dir=tmp_path / "current",
        archive_dir=tmp_path / "archive",
    )
    real_memory_service = MemoryService(MemoryRepository(database))
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
    calls = {"count": 0, "structured_inputs": []}

    def default_generator(*args, **kwargs):
        calls["count"] += 1
        calls["structured_inputs"].append(args[0])
        return {
            "progress_update": "已确认区间每轮减半；下一步练习边界条件",
            "learner_profile_update": "本轮无需更新",
            "current_focus_update": "优先练习二分查找边界条件",
            "revision_notes_update": "补充左右边界示例",
            "session_archive_update": "理解了 O(log n) 的减半来源",
            "role_updates": "本轮无需更新",
        }

    service = LearningClosureService(
        LearningClosureRepository(database),
        session_service,
        memory_service or real_memory_service,
        generator=generator or default_generator,
        memory_bundle_loader=lambda _mode: {},
    )
    return service, runtime_repository, real_memory_service, calls, database


def test_closure_generates_preview_and_reuses_same_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    service, _runtime, _memory, calls, database = _build_service(
        tmp_path, monkeypatch
    )

    first = service.create_and_execute("thread-1")
    second = service.create_and_execute("thread-1")

    assert first.status == "preview_ready"
    assert first.memory_run_id
    assert second.id == first.id
    assert second.source_hash == first.source_hash
    assert calls["count"] == 1
    structured = first.committed_snapshot["structured_input"]
    assert calls["structured_inputs"] == [structured]
    assert structured["committed_learning_state"]["confirmed_points"] == [
        "区间每轮减半"
    ]
    assert structured["recent_dialogue"][0]["turn_id"] == "turn-1"
    assert "messages" not in structured
    linked = service.linked_memory_run(first)
    assert linked is not None
    assert linked.status == "previewed"
    assert linked.preview["writable"] is True
    with database.connect() as connection:
        row = connection.execute(
            "SELECT version FROM runtime_component_migrations WHERE component = ?",
            ("learning_closure",),
        ).fetchone()
    assert row is not None and row["version"] == 1


def test_research_contract_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    service, *_ = _build_service(
        tmp_path,
        monkeypatch,
        contract=_task_contract("research", "research_summary", learning=False),
    )

    with pytest.raises(LearningClosureNotEligible, match="does not allow"):
        service.create_and_execute("thread-1")

    assert service.list() == []


def test_retry_keeps_generated_checkpoint_and_skips_second_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    class FailOnceMemoryService:
        def __init__(self, delegate: MemoryService):
            self.delegate = delegate
            self.fail = True

        def create(self, updates, *, run_id=None, runtime_modes=None):
            if self.fail:
                self.fail = False
                raise RuntimeError("preview store unavailable")
            return self.delegate.create(
                updates,
                run_id=run_id,
                runtime_modes=runtime_modes,
            )

        def get(self, run_id):
            return self.delegate.get(run_id)

        def commit(self, run_id, *, runtime_modes=None):
            return self.delegate.commit(run_id, runtime_modes=runtime_modes)

    base_service, runtime, real_memory, calls, database = _build_service(
        tmp_path, monkeypatch
    )
    service = LearningClosureService(
        LearningClosureRepository(database),
        base_service.session_service,
        FailOnceMemoryService(real_memory),
        generator=base_service.generator,
        memory_bundle_loader=lambda _mode: {},
    )

    failed = service.create_and_execute("thread-1")
    retried = service.retry(failed.id)

    assert failed.status == "failed"
    assert failed.generated_result["progress_update"]
    assert retried.status == "preview_ready"
    assert retried.memory_run_id
    assert calls["count"] == 1
    assert runtime.get_chat_thread("thread-1") is not None


def test_cancelled_created_run_does_not_generate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    service, *_ = _build_service(tmp_path, monkeypatch)
    snapshot, eligibility, source_hash = service._collect_source("thread-1")
    created = service.repository.create(
        LearningClosureRun(
            thread_id="thread-1",
            source_thread_version=snapshot["source_thread_version"],
            last_completed_turn_id=snapshot["last_completed_turn_id"],
            source_hash=source_hash,
            closure_eligibility=eligibility,
            committed_snapshot=snapshot,
        )
    )

    cancelled = service.cancel(created.id)

    assert cancelled.status == "cancelled"
    assert cancelled.reason == "user_cancelled"
    assert cancelled.generated_result == {}


def test_confirmed_memory_commit_completes_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    service, _runtime, _memory, _calls, _database = _build_service(
        tmp_path, monkeypatch
    )
    written = tmp_path / "written.md"
    monkeypatch.setattr(
        "src.memory_writer.write_current_focus",
        lambda content: written,
    )
    monkeypatch.setattr(
        "src.memory_writer.append_memory",
        lambda target, content, learner_pending=False: written,
    )
    preview = service.create_and_execute("thread-1")

    completed = service.commit(preview.id)
    repeated = service.commit(preview.id)

    assert completed.status == "completed"
    assert repeated.id == completed.id
    assert repeated.status == "completed"
    memory_run = service.linked_memory_run(completed)
    assert memory_run is not None
    assert memory_run.status == "succeeded"
