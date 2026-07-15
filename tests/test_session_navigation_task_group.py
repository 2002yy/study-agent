from __future__ import annotations

from pathlib import Path

from src.application.session_service import SessionService
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository


def test_learning_session_keeps_learning_group_after_organize_turn(tmp_path: Path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
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
    service = SessionService(
        runtime,
        current_dir=tmp_path / "current",
        archive_dir=tmp_path / "archive",
    )

    row = service.list_sessions()[0]

    assert row["task_intent"] == "learn"
    assert row["title"] == "理解数据库事务隔离级别"
    assert row["phase"] == "transfer_check"
