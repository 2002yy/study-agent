"""Server-owned ToolRun application workflow."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable

from src.domain.runtime_entities import ToolRun, new_id, utc_now
from src.repositories.tool_repository import ToolRepository
from src.tools.registry import ToolExecutionResult, ToolRegistry
from src.workflows.store import WorkflowStore, elapsed_ms_since


class ToolService:
    def __init__(
        self,
        repository: ToolRepository,
        registry: ToolRegistry,
        *,
        workflow_store_factory: Callable[[], WorkflowStore],
    ):
        self.repository = repository
        self.registry = registry
        self.workflow_store_factory = workflow_store_factory

    def create(self, tool_name: str, args: dict) -> ToolRun:
        frozen_args = dict(args)
        started_at = time.perf_counter()
        try:
            result = self.registry.preview(tool_name, frozen_args)
        except Exception as exc:
            result = ToolExecutionResult(tool_name, "failed", reason=str(exc))
        elapsed_ms = elapsed_ms_since(started_at)
        now = utc_now()
        status = "previewed" if result.status == "preview" else result.status
        return self.repository.create(
            ToolRun(
                tool_name=tool_name,
                args=frozen_args,
                args_hash=args_hash(frozen_args),
                status=status,
                preview=result.output,
                reason=result.reason,
                elapsed_ms=elapsed_ms,
                previewed_at=now,
                completed_at=now if status in {"failed", "blocked"} else None,
                created_at=now,
                updated_at=now,
            )
        )

    def call(self, run_id: str) -> ToolRun:
        operation_id = new_id("tool_call")
        run = self.repository.acquire_call(run_id, operation_id)
        started_at = time.perf_counter()
        if args_hash(run.args) != run.args_hash:
            return self.repository.complete_call(
                run.id,
                operation_id,
                status="blocked",
                result={},
                reason="args_hash_mismatch",
                elapsed_ms=elapsed_ms_since(started_at),
            )
        self._audit_started(run)
        try:
            result = self.registry.call(run.tool_name, run.args)
            elapsed_ms = elapsed_ms_since(started_at)
            completed = self.repository.complete_call(
                run.id,
                operation_id,
                status=result.status,
                result=result.output,
                reason=result.reason,
                elapsed_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = elapsed_ms_since(started_at)
            completed = self.repository.fail_call(
                run.id, operation_id, str(exc), elapsed_ms
            )
            self._audit_completed(
                run, ToolExecutionResult(run.tool_name, "failed", reason=str(exc)), elapsed_ms
            )
            raise
        self._audit_completed(run, result, elapsed_ms)
        return completed

    def get(self, run_id: str) -> ToolRun:
        run = self.repository.get(run_id)
        if run is None:
            raise ValueError(f"ToolRun not found: {run_id}")
        return run

    def list(self, *, limit: int = 20) -> list[ToolRun]:
        return self.repository.list(limit=limit)

    def _audit_started(self, run: ToolRun) -> None:
        try:
            self.workflow_store_factory().record_event(
                run_id=run.id,
                step_id=run.tool_name,
                event_type="started",
                status="running",
                workflow_name="tool_call",
                data={"tool_name": run.tool_name, "args_hash": run.args_hash},
            )
        except Exception:
            pass

    def _audit_completed(
        self, run: ToolRun, result: ToolExecutionResult, elapsed_ms: int
    ) -> None:
        try:
            self.workflow_store_factory().record_event(
                run_id=run.id,
                step_id=run.tool_name,
                event_type=result.status,
                status="succeeded" if result.status == "succeeded" else "failed",
                workflow_name="tool_call",
                data={"tool_name": run.tool_name, "result_status": result.status},
                elapsed_ms=elapsed_ms,
                error=result.reason if result.status in {"failed", "blocked"} else "",
            )
        except Exception:
            pass


def args_hash(args: dict) -> str:
    payload = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
