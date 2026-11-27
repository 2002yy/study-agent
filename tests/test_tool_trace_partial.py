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


def _read_call(url: str = "https://example.org/a") -> dict:
    return {
        "name": "web_read",
        "arguments": {"url": url},
        "result": {
            "ok": True,
            "status": "read",
            "url": url,
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


def test_recorded_trace_admits_a_user_supplied_url_without_a_search(tmp_path):
    service = WebLookupService(
        WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    )
    run = service.create(
        "topic",
        run_kind="autonomous_research",
        research_mode="standard",
    )
    operation = service.begin_tool_trace(run.id)
    url = "https://user.example/doc"

    completed = service.record_tool_trace(
        run.id,
        calls=[_read_call(url)],
        source_block="",
        operation_id=operation,
        final=True,
        user_urls=(url,),
    )

    assert completed.status == "completed"
    assert [row["item"]["url"] for row in completed.selected_sources] == [url]
    assert [row["url"] for row in completed.items] == [url]


def test_rejected_exploratory_read_body_survives_in_the_durable_trace(tmp_path):
    service = WebLookupService(
        WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    )
    run = service.create(
        "topic",
        run_kind="autonomous_research",
        research_mode="standard",
    )
    operation = service.begin_tool_trace(run.id)
    admitted_url = "https://example.org/a"
    explored_url = "https://random.example/x"

    completed = service.record_tool_trace(
        run.id,
        calls=[_search_call(), _read_call(admitted_url), _read_call(explored_url)],
        source_block="",
        operation_id=operation,
        final=True,
    )

    stored = service.get(run.id)
    trace = stored.research_context["tool_trace"]
    assert [row["item"]["url"] for row in completed.selected_sources] == [
        admitted_url
    ]
    assert [row["url"] for row in trace["exploration_reads"]] == [explored_url]
    record = trace["exploration_reads"][0]
    assert record["content"] == "body"
    assert record["chars"] == 4
    assert record["reason"] == "source_not_established"


def test_relaxed_trace_persists_an_undiscovered_public_read(tmp_path):
    service = WebLookupService(
        WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    )
    url = "https://docs.example.org/en/latest/guide"
    strict_run = service.create("topic", run_kind="autonomous_research")
    strict_operation = service.begin_tool_trace(strict_run.id)

    strict = service.record_tool_trace(
        strict_run.id,
        calls=[_read_call(url)],
        source_block="",
        operation_id=strict_operation,
        final=True,
    )

    relaxed_run = service.create("topic", run_kind="autonomous_research")
    relaxed_operation = service.begin_tool_trace(relaxed_run.id)
    relaxed = service.record_tool_trace(
        relaxed_run.id,
        calls=[_read_call(url)],
        source_block="",
        operation_id=relaxed_operation,
        final=True,
        require_discovery=False,
    )

    assert strict.selected_sources == []
    assert [row["item"]["url"] for row in relaxed.selected_sources] == [url]
    assert [row["url"] for row in relaxed.items] == [url]
