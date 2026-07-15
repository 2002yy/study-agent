from __future__ import annotations

from pathlib import Path

from src.application.session_service import SessionService
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository


def _service(tmp_path: Path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
    return runtime, SessionService(
        runtime,
        current_dir=tmp_path / "current",
        archive_dir=tmp_path / "archive",
    )


def test_learning_session_keeps_learning_group_after_organize_turn(tmp_path: Path):
    runtime, service = _service(tmp_path)
    runtime.create_chat_thread(
        ChatThread(
            id="thread-learning-group",
            learning_state={
                "protocol": "socratic_rediscovery",
                "objective": "理解数据库事务隔离级别",
                "phase": "transfer_check",
            },
        )
    )
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-learning-group-1",
            thread_id="thread-learning-group",
            status="completed",
            user_message="带我学习事务隔离级别",
            assistant_message="先从脏读和不可重复读开始。",
            route_snapshot={
                "task_contract": {
                    "task_intent": "learn",
                    "closure_eligibility": "learning_summary",
                    "source_policy": "local_only",
                    "learning_state_enabled": True,
                    "confidence": "high",
                }
            },
        )
    )
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-learning-group-2",
            thread_id="thread-learning-group",
            status="completed",
            user_message="整理这次学习",
            assistant_message="已准备整理候选。",
            route_snapshot={
                "task_contract": {
                    "task_intent": "organize",
                    "closure_eligibility": "learning_summary",
                    "source_policy": "local_only",
                    "learning_state_enabled": True,
                    "confidence": "high",
                }
            },
        )
    )

    row = service.list_sessions()[0]

    assert row["task_intent"] == "learn"
    assert row["title"] == "理解数据库事务隔离级别"
    assert row["phase"] == "transfer_check"


def test_research_session_ignores_low_confidence_quick_answer_followup(tmp_path: Path):
    runtime, service = _service(tmp_path)
    runtime.create_chat_thread(ChatThread(id="thread-research-group"))
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-research-group-1",
            thread_id="thread-research-group",
            status="completed",
            user_message="联网查看 Python 3.14 最近进展",
            assistant_message="第一轮研究结果。",
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
            id="turn-research-group-2",
            thread_id="thread-research-group",
            status="completed",
            user_message="那发布时间呢？",
            assistant_message="还需要等待官方确认。",
            route_snapshot={
                "task_contract": {
                    "task_intent": "quick_answer",
                    "closure_eligibility": "not_applicable",
                    "source_policy": "model_only",
                    "learning_state_enabled": False,
                    "confidence": "low",
                }
            },
        )
    )

    row = service.list_sessions()[0]

    assert row["task_intent"] == "research"
    assert row["research_summary"] == "还需要等待官方确认。"
    assert row["title"] == "联网查看 Python 3.14 最近进展"
