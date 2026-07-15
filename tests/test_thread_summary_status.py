from __future__ import annotations

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
from src.repositories.thread_summary_repository import ThreadSummaryRepository


def _contract() -> dict:
    return {
        "task_intent": "learn",
        "source_policy": "local_and_web",
        "closure_eligibility": "learning_summary",
        "learning_state_enabled": True,
        "confidence": "high",
    }


def _build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
    runtime.create_chat_thread(
        ChatThread(
            id="thread-summary",
            learning_state={
                "protocol": "socratic_rediscovery",
                "objective": "理解二分查找",
                "confirmed_points": ["区间每轮减半"],
                "unresolved_gap": "边界条件",
                "phase": "guided_practice",
            },
        )
    )
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-summary-1",
            thread_id="thread-summary",
            status="completed",
            user_message="为什么是 O(log n)？",
            assistant_message="因为每轮把区间缩小一半。",
            role="nahida",
            mode="socratic",
            model="pro",
            route_snapshot={"task_contract": _contract()},
            pedagogy_snapshot={"phase": "guided_practice"},
        )
    )
    summary_repository = ThreadSummaryRepository(database)
    sessions = SessionService(
        runtime,
        summary_repository=summary_repository,
        current_dir=tmp_path / "current",
        archive_dir=tmp_path / "archive",
    )
    memory = MemoryService(MemoryRepository(database))
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
    writes = tmp_path / "memory.md"
    monkeypatch.setattr(
        "src.memory_writer.write_current_focus", lambda _content: writes
    )
    monkeypatch.setattr(
        "src.memory_writer.append_memory",
        lambda _target, _content, learner_pending=False: writes,
    )
    calls = {"count": 0}

    def generator(*_args, **_kwargs):
        calls["count"] += 1
        return {
            "progress_update": "已确认区间每轮减半",
            "learner_profile_update": "本轮无需更新",
            "current_focus_update": "继续练习边界条件",
            "revision_notes_update": "补充边界反例",
            "session_archive_update": "完成复杂度解释",
            "role_updates": "本轮无需更新",
        }

    closure = LearningClosureService(
        LearningClosureRepository(database),
        sessions,
        memory,
        generator=generator,
        memory_bundle_loader=lambda _mode: {},
    )
    return runtime, sessions, memory, closure, calls, database


def test_commit_marks_thread_summarized_without_archiving_or_bumping_content_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    runtime, sessions, _memory, closure, _calls, database = _build(
        tmp_path, monkeypatch
    )
    preview = closure.create_and_execute("thread-summary")
    version_before_commit = runtime.get_chat_thread("thread-summary").version

    completed = closure.commit(preview.id)

    thread = runtime.get_chat_thread("thread-summary")
    summary = sessions.summary_payload("thread-summary")
    assert completed.status == "completed"
    assert thread is not None and thread.status == "active"
    assert thread.version == version_before_commit
    assert summary["status"] == "summarized"
    assert summary["last_completed_turn_id"] == "turn-summary-1"
    assert summary["current_last_completed_turn_id"] == "turn-summary-1"
    assert summary["closure_run_id"] == completed.id
    assert summary["can_summarize"] is False
    with database.connect() as connection:
        row = connection.execute(
            "SELECT version FROM runtime_component_migrations WHERE component = ?",
            ("thread_summary",),
        ).fetchone()
    assert row is not None and row["version"] == 1


def test_settings_change_does_not_unlock_duplicate_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    runtime, sessions, _memory, closure, calls, _database = _build(
        tmp_path, monkeypatch
    )
    first = closure.create_and_execute("thread-summary")
    completed = closure.commit(first.id)
    runtime.update_chat_thread_settings("thread-summary", {"selectedRole": "march7"})

    repeated = closure.create_and_execute("thread-summary")

    assert repeated.id == completed.id
    assert calls["count"] == 1
    assert sessions.summary_payload("thread-summary")["status"] == "summarized"


def test_new_completed_turn_reopens_summary_and_allows_new_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    runtime, sessions, _memory, closure, calls, _database = _build(
        tmp_path, monkeypatch
    )
    first = closure.create_and_execute("thread-summary")
    closure.commit(first.id)
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-summary-2",
            thread_id="thread-summary",
            status="completed",
            user_message="边界怎么处理？",
            assistant_message="使用闭区间时循环条件是 left <= right。",
            role="nahida",
            mode="socratic",
            model="pro",
            route_snapshot={"task_contract": _contract()},
            pedagogy_snapshot={"phase": "transfer_check"},
        )
    )

    reopened = sessions.summary_payload("thread-summary")
    second = closure.create_and_execute("thread-summary")

    assert reopened["status"] == "needs_update"
    assert reopened["can_summarize"] is True
    assert second.id != first.id
    assert second.last_completed_turn_id == "turn-summary-2"
    assert calls["count"] == 2


def test_stale_preview_is_rejected_before_memory_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    runtime, sessions, memory, closure, _calls, _database = _build(
        tmp_path, monkeypatch
    )
    preview = closure.create_and_execute("thread-summary")
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-summary-race",
            thread_id="thread-summary",
            status="completed",
            user_message="新增问题",
            assistant_message="新增完成回答",
            route_snapshot={"task_contract": _contract()},
        )
    )

    failed = closure.commit(preview.id)

    assert failed.status == "failed"
    assert failed.reason == "thread_source_changed"
    assert memory.get(preview.memory_run_id).status == "previewed"
    assert sessions.summary_payload("thread-summary")["status"] == "not_summarized"
    assert runtime.get_chat_thread("thread-summary").status == "active"


def test_marking_old_source_after_race_records_needs_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    runtime, sessions, _memory, _closure, _calls, _database = _build(
        tmp_path, monkeypatch
    )
    source_version = runtime.get_chat_thread("thread-summary").version
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-summary-late",
            thread_id="thread-summary",
            status="completed",
            user_message="并发新增",
            assistant_message="新的已完成内容",
            route_snapshot={"task_contract": _contract()},
        )
    )

    summary = sessions.mark_summary_completed(
        "thread-summary",
        source_thread_version=source_version,
        last_completed_turn_id="turn-summary-1",
        closure_run_id="closure-old-source",
    )

    assert summary["status"] == "needs_update"
    assert summary["last_completed_turn_id"] == "turn-summary-1"
    assert summary["current_last_completed_turn_id"] == "turn-summary-late"
    assert summary["can_summarize"] is True
