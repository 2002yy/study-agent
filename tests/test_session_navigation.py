from __future__ import annotations

from pathlib import Path

from src.application.session_service import SessionService
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.session_navigation_repository import SessionNavigationRepository
from src.repositories.thread_summary_repository import ThreadSummaryRepository


def _service(tmp_path: Path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
    service = SessionService(
        runtime,
        summary_repository=ThreadSummaryRepository(database),
        navigation_repository=SessionNavigationRepository(database),
        current_dir=tmp_path / "current",
        archive_dir=tmp_path / "archive",
    )
    return runtime, service, database


def test_session_projection_uses_committed_learning_truth_and_latest_contract(tmp_path: Path):
    runtime, service, _database = _service(tmp_path)
    runtime.create_chat_thread(
        ChatThread(
            id="thread-learning-nav",
            learning_state={
                "protocol": "socratic_rediscovery",
                "objective": "理解二分查找的时间复杂度",
                "phase": "guided_practice",
                "confirmed_points": ["区间每轮减半"],
                "unresolved_gap": "边界条件",
            },
        )
    )
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-learning-1",
            thread_id="thread-learning-nav",
            status="completed",
            user_message="为什么二分查找是 O(log n)？",
            assistant_message="因为每一轮都会把搜索区间缩小一半。",
            route_snapshot={
                "task_contract": {
                    "task_intent": "learn",
                    "closure_eligibility": "learning_summary",
                    "source_policy": "local_only",
                    "learning_state_enabled": True,
                    "confidence": "high",
                }
            },
            pedagogy_snapshot={"phase": "guided_practice"},
        )
    )

    row = service.list_sessions()[0]
    detail = service.get_session("thread-learning-nav")

    assert row["title"] == "理解二分查找的时间复杂度"
    assert row["title_source"] == "auto"
    assert row["auto_title"] == "理解二分查找的时间复杂度"
    assert row["manual_title"] == ""
    assert row["objective"] == "理解二分查找的时间复杂度"
    assert row["task_intent"] == "learn"
    assert row["phase"] == "guided_practice"
    assert row["unresolved_gap"] == "边界条件"
    assert row["preview"] == "因为每一轮都会把搜索区间缩小一半。"
    assert row["research_summary"] == ""
    assert row["last_completed_turn_id"] == "turn-learning-1"
    assert row["summary"]["status"] == "not_summarized"
    assert detail is not None
    assert detail["navigation"]["title"] == row["title"]
    assert detail["navigation"]["summary"] == row["summary"]


def test_manual_title_is_independent_and_clearable(tmp_path: Path):
    runtime, service, _database = _service(tmp_path)
    runtime.create_chat_thread(
        ChatThread(
            id="thread-manual-title",
            learning_state={"objective": "原始自动标题"},
        )
    )
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-manual-title",
            thread_id="thread-manual-title",
            status="completed",
            user_message="原始问题",
            assistant_message="原始回答",
        )
    )
    version_before = runtime.get_chat_thread("thread-manual-title").version

    renamed = service.rename_session("thread-manual-title", "  我的二分查找复习  ")
    runtime.update_chat_thread_learning_state(
        "thread-manual-title",
        {"objective": "后来变化的自动标题"},
    )
    after_state_change = service.list_sessions()[0]
    cleared = service.rename_session("thread-manual-title", "")

    assert renamed["title"] == "我的二分查找复习"
    assert renamed["title_source"] == "manual"
    assert renamed["manual_title"] == "我的二分查找复习"
    assert after_state_change["title"] == "我的二分查找复习"
    assert after_state_change["auto_title"] == "后来变化的自动标题"
    assert cleared["title"] == "后来变化的自动标题"
    assert cleared["title_source"] == "auto"
    assert runtime.get_chat_thread("thread-manual-title").version > version_before
    # Only the learning-state change bumps ChatThread version; title metadata is separate.
    assert cleared["version"] == runtime.get_chat_thread("thread-manual-title").version


def test_research_session_exposes_latest_research_summary(tmp_path: Path):
    runtime, service, _database = _service(tmp_path)
    runtime.create_chat_thread(ChatThread(id="thread-research-nav"))
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-research-1",
            thread_id="thread-research-nav",
            status="completed",
            user_message="联网查看 Python 3.14 最近进展",
            assistant_message="这是第一轮研究结果。",
            route_snapshot={
                "task_contract": {
                    "task_intent": "research",
                    "closure_eligibility": "research_summary",
                    "source_policy": "web_only",
                    "learning_state_enabled": False,
                    "confidence": "high",
                }
            },
        )
    )
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-research-2",
            thread_id="thread-research-nav",
            status="completed",
            user_message="继续确认发布时间",
            assistant_message="最新核对结果显示发布时间仍需等待官方确认。",
            route_snapshot={
                "task_contract": {
                    "task_intent": "research",
                    "closure_eligibility": "research_summary",
                    "source_policy": "web_only",
                    "learning_state_enabled": False,
                    "confidence": "high",
                }
            },
        )
    )

    row = service.list_sessions()[0]

    assert row["title"] == "联网查看 Python 3.14 最近进展"
    assert row["task_intent"] == "research"
    assert row["research_summary"] == "最新核对结果显示发布时间仍需等待官方确认。"
    assert row["preview"] == row["research_summary"]
    assert row["last_completed_turn_id"] == "turn-research-2"


def test_empty_legacy_session_has_compatible_fallback_navigation(tmp_path: Path):
    runtime, service, _database = _service(tmp_path)
    runtime.create_chat_thread(ChatThread(id="thread-empty-legacy"))

    row = service.list_sessions()[0]

    assert row["title"].startswith("快速问答 · ")
    assert row["task_intent"] == "quick_answer"
    assert row["preview"] == ""
    assert row["has_completed_turns"] is False
    assert row["summary"]["status"] == "not_summarized"
