from __future__ import annotations

from src.rag import index_documents
from src.tools.registry import create_default_tool_registry
from src.workflows.store import WorkflowStore


def test_workflow_store_records_and_lists_run(tmp_path):
    store = WorkflowStore(tmp_path)
    run_id = "tool-test-run"

    store.record_event(
        run_id=run_id,
        step_id="retrieve_local_knowledge",
        event_type="started",
        status="running",
        workflow_name="tool_call",
    )
    store.record_event(
        run_id=run_id,
        step_id="retrieve_local_knowledge",
        event_type="succeeded",
        status="succeeded",
        workflow_name="tool_call",
        elapsed_ms=12,
    )

    run = store.load_run(run_id)
    runs = store.list_runs()

    assert run is not None
    assert run.status == "succeeded"
    assert run.elapsed_ms == 12
    assert [event.event_type for event in run.events] == ["started", "succeeded"]
    assert [item.run_id for item in runs] == [run_id]


def test_default_tool_registry_lists_local_knowledge_tool():
    registry = create_default_tool_registry()

    specs = registry.list_specs()

    assert [spec.name for spec in specs] == ["retrieve_local_knowledge"]
    assert specs[0].permissions == ("read",)
    assert specs[0].requires_confirmation is False
    assert "query" in specs[0].input_schema["required"]


def test_tool_registry_preview_blocks_unknown_args():
    registry = create_default_tool_registry()

    result = registry.preview(
        "retrieve_local_knowledge",
        {"query": "local knowledge about RAG", "shell": "whoami"},
    )

    assert result.status == "blocked"
    assert result.reason == "unknown_args: shell"


def test_tool_registry_calls_local_knowledge_with_audit(tmp_path):
    document = tmp_path / "notes.md"
    index_path = tmp_path / "rag_index.json"
    document.write_text("Local knowledge tools should cite local evidence.", encoding="utf-8")
    index_documents([document], index_path=index_path, max_chars=200, overlap_chars=0)
    registry = create_default_tool_registry()
    store = WorkflowStore(tmp_path / "workflows")

    result = registry.call_with_audit(
        "retrieve_local_knowledge",
        {
            "query": "local knowledge tools cite local evidence",
            "index_path": str(index_path),
            "top_k": 1,
        },
        store=store,
        run_id="local-knowledge-run",
    )
    run = store.load_run("local-knowledge-run")

    assert result.status == "succeeded"
    assert result.output["status"] == "found"
    assert result.run_id == "local-knowledge-run"
    assert run is not None
    assert run.status == "succeeded"
    assert [event.event_type for event in run.events] == ["started", "succeeded"]
    assert run.events[0].data["tool_name"] == "retrieve_local_knowledge"
