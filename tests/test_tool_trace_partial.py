"""A failed research turn keeps the tool results it already collected."""

from __future__ import annotations

from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository


def _search_call() -> dict:
    return {
        "name": "web_search",
        "arguments": {"query": "a"},
        "result": {
            "status": "ok",
            "results": [{"title": "A", "url": "https://example.org/a"}],
        },
    }


def _read_call() -> dict:
    return {
        "name": "web_read",
        "arguments": {"url": "https://example.org/a"},
        "result": {
            "ok": True,
            "status": "read",
            "url": "https://example.org/a",
            "title": "A",
            "content": "body",
        },
    }


def test_partial_checkpoint_keeps_the_run_open_then_failure_keeps_the_calls(tmp_path):
    service = WebLookupService(
        WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    )
    run = service.create(
        "topic",
        run_kind="autonomous_research",
        research_mode="standard",
    )
    operation = service.begin_tool_trace(run.id)

    partial = service.record_tool_trace(
        run.id,
        calls=[_search_call(), _read_call()],
        source_block="",
        operation_id=operation,
        final=False,
        stop_reason="sources_partially_read",
    )

    assert partial.status == "running"
    assert len(partial.selected_sources) == 1

    failed = service.record_tool_trace(
        run.id,
        calls=[_search_call(), _read_call()],
        source_block="",
        error="provider down",
        operation_id=operation,
        final=True,
        stop_reason="chat_tool_loop_failed",
    )

    assert failed.status == "failed"
    assert len(failed.selected_sources) == 1
    assert failed.stop_reason == "chat_tool_loop_failed"
