from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from src.application.tool_service import ToolService
from src.repositories.tool_repository import ToolRepository
from src.tools.registry import (
    RegisteredTool,
    ToolExecutionResult,
    ToolRegistry,
    ToolSpec,
)


def _service(runtime_test_context, call_handler, workflow_store_factory=None):
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name="frozen",
                description="test",
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                },
            ),
            preview_handler=lambda args: ToolExecutionResult(
                "frozen", "preview", output={"query": args["query"]}
            ),
            call_handler=call_handler,
        )
    )
    return ToolService(
        runtime_test_context.tool_repository,
        registry,
        workflow_store_factory=workflow_store_factory or (lambda: _NoopStore()),
    )


class _NoopStore:
    def record_event(self, **kwargs):
        return kwargs


def test_tool_run_call_uses_frozen_server_args(runtime_test_context):
    observed = []
    service = _service(
        runtime_test_context,
        lambda args: observed.append(dict(args))
        or ToolExecutionResult("frozen", "succeeded", output={"query": args["query"]}),
    )
    previewed = service.create("frozen", {"query": "original"})

    completed = service.call(previewed.id)

    assert observed == [{"query": "original"}]
    assert completed.status == "succeeded"
    assert completed.result == {"query": "original"}


def test_tool_run_concurrent_call_has_single_owner(runtime_test_context):
    started = Event()
    release = Event()

    def call_handler(args):
        started.set()
        assert release.wait(timeout=5)
        return ToolExecutionResult("frozen", "succeeded", output=dict(args))

    service = _service(runtime_test_context, call_handler)
    previewed = service.create("frozen", {"query": "once"})

    with ThreadPoolExecutor(max_workers=2) as executor:
        owner = executor.submit(service.call, previewed.id)
        assert started.wait(timeout=5)
        contender = executor.submit(service.call, previewed.id)
        with pytest.raises(ValueError, match="ownership conflict"):
            contender.result(timeout=5)
        release.set()
        result = owner.result(timeout=5)

    assert result.status == "succeeded"


def test_tool_run_result_survives_workflow_audit_failure(runtime_test_context):
    class BrokenStore:
        def record_event(self, **kwargs):
            raise OSError("audit unavailable")

    service = _service(
        runtime_test_context,
        lambda args: ToolExecutionResult("frozen", "succeeded", output=dict(args)),
        workflow_store_factory=lambda: BrokenStore(),
    )
    previewed = service.create("frozen", {"query": "durable"})

    completed = service.call(previewed.id)

    assert completed.status == "succeeded"
    assert service.get(previewed.id).result == {"query": "durable"}


def test_tool_run_blocks_when_persisted_args_no_longer_match_hash(
    runtime_test_context
):
    calls = []
    service = _service(
        runtime_test_context,
        lambda args: calls.append(args)
        or ToolExecutionResult("frozen", "succeeded", output=dict(args)),
    )
    previewed = service.create("frozen", {"query": "original"})
    with runtime_test_context.tool_repository.database.connect() as connection:
        connection.execute(
            "UPDATE tool_runs SET args = ? WHERE id = ?",
            ('{"query":"tampered"}', previewed.id),
        )

    blocked = service.call(previewed.id)

    assert blocked.status == "blocked"
    assert blocked.reason == "args_hash_mismatch"
    assert calls == []


def test_tool_run_persists_execution_failure_reason(runtime_test_context):
    service = _service(
        runtime_test_context,
        lambda args: ToolExecutionResult("frozen", "failed", reason="provider down"),
    )
    previewed = service.create("frozen", {"query": "failure"})

    failed = service.call(previewed.id)

    assert failed.status == "failed"
    assert failed.reason == "provider down"
    assert failed.completed_at is not None


def test_unknown_tool_is_persisted_as_blocked(runtime_test_context):
    blocked = runtime_test_context.tool_service.create("unknown", {"query": "x"})

    assert blocked.status == "blocked"
    assert blocked.reason == "tool_not_registered"
    with pytest.raises(ValueError, match="ownership conflict"):
        runtime_test_context.tool_service.call(blocked.id)


def test_preview_exception_still_returns_persisted_tool_run(runtime_test_context):
    registry = ToolRegistry()

    def fail_preview(args):
        raise RuntimeError("preview failed")

    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name="broken-preview",
                description="test",
                input_schema={"type": "object", "properties": {}},
            ),
            preview_handler=fail_preview,
            call_handler=lambda args: ToolExecutionResult(
                "broken-preview", "succeeded"
            ),
        )
    )
    service = ToolService(
        runtime_test_context.tool_repository,
        registry,
        workflow_store_factory=lambda: _NoopStore(),
    )

    failed = service.create("broken-preview", {})

    assert failed.id.startswith("tool_")
    assert failed.status == "failed"
    assert failed.reason == "preview failed"
    assert service.get(failed.id) == failed


def test_tool_repository_recovers_stale_running_call(runtime_test_context):
    service = _service(
        runtime_test_context,
        lambda args: ToolExecutionResult("frozen", "succeeded", output=dict(args)),
    )
    previewed = service.create("frozen", {"query": "stale"})
    runtime_test_context.tool_repository.acquire_call(previewed.id, "old-operation")
    with runtime_test_context.tool_repository.database.connect() as connection:
        connection.execute(
            "UPDATE tool_runs SET active_operation_started_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", previewed.id),
        )

    repository = ToolRepository(runtime_test_context.tool_repository.database)
    recovered = repository.get(previewed.id)

    assert recovered is not None
    assert recovered.status == "failed"
    assert recovered.reason == "stale operation recovered"
    assert recovered.active_operation_id is None
