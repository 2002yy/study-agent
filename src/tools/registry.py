from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal

from src.rag.index import DEFAULT_RAG_INDEX_PATH
from src.tools.local_knowledge import retrieve_local_knowledge, should_retrieve_local_knowledge
from src.workflows.schema import WorkflowStatus
from src.workflows.store import WorkflowStore, elapsed_ms_since, new_run_id

ToolPermission = Literal["read", "write"]
ToolStatus = Literal["preview", "succeeded", "failed", "blocked"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    permissions: tuple[ToolPermission, ...] = ("read",)
    requires_confirmation: bool = False
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "permissions": list(self.permissions),
            "requires_confirmation": self.requires_confirmation,
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class ToolExecutionResult:
    tool_name: str
    status: ToolStatus
    output: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    elapsed_ms: int = 0
    run_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ToolHandler = Callable[[dict[str, Any]], ToolExecutionResult]


@dataclass(frozen=True)
class RegisteredTool:
    spec: ToolSpec
    preview_handler: ToolHandler
    call_handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        if tool.spec.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.spec.name}")
        self._tools[tool.spec.name] = tool

    def list_specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in sorted(self._tools.values(), key=lambda item: item.spec.name)]

    def get_spec(self, name: str) -> ToolSpec | None:
        tool = self._tools.get(name)
        return tool.spec if tool else None

    def preview(self, name: str, args: dict[str, Any]) -> ToolExecutionResult:
        tool = self._tools.get(name)
        if tool is None:
            return _blocked(name, "tool_not_registered")
        if not tool.spec.enabled:
            return _blocked(name, "tool_disabled")
        validation_error = _validate_args(tool.spec, args)
        if validation_error:
            return _blocked(name, validation_error)
        return tool.preview_handler(args)

    def call(self, name: str, args: dict[str, Any]) -> ToolExecutionResult:
        tool = self._tools.get(name)
        if tool is None:
            return _blocked(name, "tool_not_registered")
        if not tool.spec.enabled:
            return _blocked(name, "tool_disabled")
        validation_error = _validate_args(tool.spec, args)
        if validation_error:
            return _blocked(name, validation_error)
        return tool.call_handler(args)

    def call_with_audit(
        self,
        name: str,
        args: dict[str, Any],
        *,
        store: WorkflowStore,
        run_id: str | None = None,
        workflow_name: str = "tool_call",
    ) -> ToolExecutionResult:
        target_run_id = run_id or new_run_id("tool")
        started_at = time.perf_counter()
        store.record_event(
            run_id=target_run_id,
            step_id=name,
            event_type="started",
            status="running",
            workflow_name=workflow_name,
            data={"tool_name": name, "args": _summarize_args(args)},
        )
        result = self.call(name, args)
        elapsed_ms = elapsed_ms_since(started_at)
        status: WorkflowStatus = "succeeded" if result.status == "succeeded" else "failed"
        store.record_event(
            run_id=target_run_id,
            step_id=name,
            event_type=result.status,
            status=status,
            workflow_name=workflow_name,
            data={"tool_name": name, "result_status": result.status},
            elapsed_ms=elapsed_ms,
            error=result.reason if result.status in {"failed", "blocked"} else "",
        )
        return ToolExecutionResult(
            tool_name=result.tool_name,
            status=result.status,
            output=result.output,
            reason=result.reason,
            elapsed_ms=elapsed_ms,
            run_id=target_run_id,
        )


def create_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name="retrieve_local_knowledge",
                description="Retrieve cited local RAG context when the user query has a local-knowledge signal.",
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "minLength": 1},
                        "enabled": {"type": "boolean", "default": True},
                        "force": {"type": "boolean", "default": False},
                        "index_path": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 3},
                        "min_score": {"type": "number", "minimum": 0, "default": 0.01},
                        "retrieval_mode": {
                            "type": "string",
                            "enum": ["lexical", "vector", "hybrid", "backend_vector"],
                            "default": "hybrid",
                        },
                    },
                },
                permissions=("read",),
            ),
            preview_handler=_preview_local_knowledge,
            call_handler=_call_local_knowledge,
        )
    )
    return registry


def _validate_args(spec: ToolSpec, args: dict[str, Any]) -> str:
    properties = set(spec.input_schema.get("properties", {}).keys())
    unknown = sorted(set(args) - properties)
    if unknown:
        return f"unknown_args: {', '.join(unknown)}"
    required = spec.input_schema.get("required", [])
    missing = [name for name in required if not str(args.get(name, "")).strip()]
    if missing:
        return f"missing_required_args: {', '.join(missing)}"
    return ""


def _blocked(tool_name: str, reason: str) -> ToolExecutionResult:
    return ToolExecutionResult(tool_name=tool_name, status="blocked", reason=reason)


def _summarize_args(args: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and len(value) > 120:
            summary[key] = f"{value[:117]}..."
        else:
            summary[key] = value
    return summary


def _preview_local_knowledge(args: dict[str, Any]) -> ToolExecutionResult:
    query = str(args.get("query", ""))
    should_retrieve, reason = should_retrieve_local_knowledge(query)
    return ToolExecutionResult(
        tool_name="retrieve_local_knowledge",
        status="preview",
        reason=reason,
        output={
            "will_retrieve": bool(args.get("force", False) or should_retrieve),
            "query": query,
            "args": _summarize_args(args),
        },
    )


def _call_local_knowledge(args: dict[str, Any]) -> ToolExecutionResult:
    started_at = time.perf_counter()
    try:
        result = retrieve_local_knowledge(
            str(args["query"]),
            enabled=bool(args.get("enabled", True)),
            force=bool(args.get("force", False)),
            index_path=str(args["index_path"]) if args.get("index_path") else DEFAULT_RAG_INDEX_PATH,
            top_k=int(args.get("top_k", 3)),
            min_score=float(args.get("min_score", 0.01)),
            retrieval_mode=str(args.get("retrieval_mode", "hybrid")),
        )
    except Exception as exc:
        return ToolExecutionResult(
            tool_name="retrieve_local_knowledge",
            status="failed",
            reason=str(exc),
            elapsed_ms=elapsed_ms_since(started_at),
        )
    return ToolExecutionResult(
        tool_name="retrieve_local_knowledge",
        status="succeeded",
        output=result.to_dict(),
        reason=result.reason,
        elapsed_ms=elapsed_ms_since(started_at),
    )
