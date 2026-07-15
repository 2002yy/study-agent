from __future__ import annotations

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
