from __future__ import annotations

import threading
import time

import pytest

from src.api.models.chat import ChatRequest
from src.api.routes.chat_routes import _chat_command
from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository


def test_chat_tool_trace_is_owned_by_thread_and_turn(tmp_path):
    service = WebLookupService(
        WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    )
    created = service.create(
        "Research durable ownership",
        owner_thread_id="thread-1",
        owner_turn_id="turn-1",
        run_kind="chat_tool_loop",
    )

    completed = service.record_tool_trace(
        created.id,
        calls=[
            {
                "name": "web_search",
                "arguments": {"query": "durable ownership"},
                "result": {"status": "ok"},
            }
        ],
        source_block="bounded tool evidence",
    )

    assert completed.status == "completed"
    assert completed.provider_status == "found"
    assert completed.research_context["run_kind"] == "chat_tool_loop"
    assert completed.research_context["owner"] == {
        "thread_id": "thread-1",
        "turn_id": "turn-1",
    }
    assert completed.research_context["tool_trace"]["calls"][0]["name"] == "web_search"
    assert completed.source_block == "bounded tool evidence"


def test_chat_command_accepts_only_matching_completed_research_evidence(tmp_path):
    service = WebLookupService(
        WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    )
    created = service.create("Recovered evidence", run_kind="chat_tool_loop")
    completed = service.record_tool_trace(
        created.id,
        calls=[{"name": "web_search", "result": {"status": "ok"}}],
        source_block="server-owned evidence",
    )

    command = _chat_command(
        ChatRequest(
            user_input="Use it",
            web_context="server-owned evidence",
            web_context_run_id=completed.id,
        ),
        service,
    )

    assert command.web_context == "server-owned evidence"
    assert command.web_context_run_id == completed.id

    with pytest.raises(ValueError, match="source block does not match"):
        _chat_command(
            ChatRequest(
                user_input="Use a fake copy",
                web_context="client-substituted evidence",
                web_context_run_id=completed.id,
            ),
            service,
        )


def test_chat_tool_trace_cancelled_by_owner_turn_cannot_complete(tmp_path):
    service = WebLookupService(
        WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    )
    created = service.create(
        "Cancel durable ownership",
        owner_thread_id="thread-1",
        owner_turn_id="turn-cancel",
        run_kind="chat_tool_loop",
    )
    operation_id = service.begin_tool_trace(created.id)

    requested = service.cancel_owned_by_turn("turn-cancel")
    completed = service.record_tool_trace(
        created.id,
        calls=[{"name": "web_search", "result": {"status": "ok"}}],
        source_block="must not commit",
        operation_id=operation_id,
    )

    assert requested[0].cancel_requested_at is not None
    assert completed.status == "cancelled"
    assert completed.stop_reason == "user_cancelled"
    assert completed.source_block == ""


def test_owner_cancel_waits_for_chat_research_run_creation(tmp_path):
    service = WebLookupService(
        WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    )

    def create_after_cancel_request() -> None:
        time.sleep(0.05)
        service.create(
            "Late durable ownership",
            owner_thread_id="thread-1",
            owner_turn_id="turn-late",
            run_kind="chat_tool_loop",
        )

    creator = threading.Thread(target=create_after_cancel_request)
    creator.start()
    cancelled = service.cancel_owned_by_turn("turn-late", wait_seconds=0.5)
    creator.join()

    assert len(cancelled) == 1
    assert cancelled[0].status == "cancelled"
    assert cancelled[0].stop_reason == "user_cancelled"
