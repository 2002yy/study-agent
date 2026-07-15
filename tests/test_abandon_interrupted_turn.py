from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api.routes.chat_routes import abandon_interrupted_turn_endpoint
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository


def _runtime(tmp_path: Path) -> RuntimeRepository:
    runtime = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    runtime.create_chat_thread(ChatThread(id="thread-recovery"))
    return runtime


def test_interrupted_turn_can_be_durably_abandoned(tmp_path: Path):
    runtime = _runtime(tmp_path)
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-interrupted",
            thread_id="thread-recovery",
            status="interrupted",
            user_message="question",
            assistant_message="partial answer",
        )
    )
    service = SimpleNamespace(repository=runtime)

    first = abandon_interrupted_turn_endpoint(
        "thread-recovery",
        "turn-interrupted",
        service,
    )
    repeated = abandon_interrupted_turn_endpoint(
        "thread-recovery",
        "turn-interrupted",
        service,
    )

    assert first == {
        "session_id": "thread-recovery",
        "turn_id": "turn-interrupted",
        "status": "abandoned",
        "changed": True,
    }
    assert repeated["changed"] is False
    persisted = runtime.get_chat_turn("turn-interrupted")
    assert persisted is not None and persisted.status == "abandoned"


def test_completed_turn_cannot_be_abandoned(tmp_path: Path):
    runtime = _runtime(tmp_path)
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-completed",
            thread_id="thread-recovery",
            status="completed",
            user_message="question",
            assistant_message="answer",
        )
    )

    with pytest.raises(HTTPException) as exc:
        abandon_interrupted_turn_endpoint(
            "thread-recovery",
            "turn-completed",
            SimpleNamespace(repository=runtime),
        )

    assert exc.value.status_code == 409
    assert "cannot be abandoned" in str(exc.value.detail)
