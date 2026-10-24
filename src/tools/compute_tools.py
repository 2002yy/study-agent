"""Compute tools registered on the existing :class:`ToolRegistry`.

Two tools are exposed:

``deterministic_compute``
    Arithmetic/statistics over supplied numbers through a controlled
    interpreter.  No untrusted source is executed.

``isolated_python``
    Untrusted Python run inside an OS-level isolated container.  It fails
    closed: when isolation is unavailable the call is ``blocked`` and host
    Python is never used as a fallback.

Both return the authoritative ``ComputationResult`` envelope from
:mod:`src.tools.computation`; illegal chart data is rejected before it can
reach the frontend.
"""

from __future__ import annotations

import json
from typing import Any

from src.domain.runtime_entities import new_id
from src.tools import computation, deterministic_compute
from src.tools.python_isolation import IsolatedPythonRunner, IsolationUnavailable, NullRunner
from src.tools.registry import RegisteredTool, ToolExecutionResult, ToolRegistry, ToolSpec

DETERMINISTIC_TOOL = "deterministic_compute"
ISOLATED_PYTHON_TOOL = "isolated_python"


def register_compute_tools(registry: ToolRegistry, runner: IsolatedPythonRunner | None = None) -> ToolRegistry:
    bounded_runner = runner or NullRunner()
    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name=DETERMINISTIC_TOOL,
                description="Deterministic arithmetic/statistics/table computation over supplied numbers.",
                input_schema={
                    "type": "object",
                    "required": ["mode"],
                    "properties": {
                        "mode": {"type": "string", "enum": ["expression", "summarize", "table"]},
                        "expression": {"type": "string"},
                        "variables": {"type": "object"},
                        "values": {"type": "array"},
                        "series": {"type": "object"},
                        "statistic": {"type": "string"},
                        "unit": {"type": "string"},
                        "run_id": {"type": "string"},
                        "tool_run_id": {"type": "string"},
                        "input_revision": {"type": "integer", "minimum": 0},
                        "source_refs": {"type": "array"},
                    },
                },
                permissions=("read",),
            ),
            preview_handler=lambda args: _preview(DETERMINISTIC_TOOL, args),
            call_handler=lambda args: _call_deterministic(args),
        )
    )
    registry.register(
        RegisteredTool(
            spec=ToolSpec(
                name=ISOLATED_PYTHON_TOOL,
                description="Run untrusted Python inside an OS-level isolated, network-less container.",
                input_schema={
                    "type": "object",
                    "required": ["code"],
                    "properties": {
                        "code": {"type": "string", "minLength": 1},
                        "run_id": {"type": "string"},
                        "tool_run_id": {"type": "string"},
                        "input_revision": {"type": "integer", "minimum": 0},
                        "source_refs": {"type": "array"},
                        "timeout_seconds": {"type": "number", "minimum": 0.1},
                    },
                },
                permissions=("read",),
            ),
            preview_handler=lambda args: _preview(ISOLATED_PYTHON_TOOL, args),
            call_handler=lambda args: _call_isolated(args, bounded_runner),
        )
    )
    return registry


def _preview(name: str, args: dict[str, Any]) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name=name,
        status="preview",
        output={"args": args, "engine": "deterministic" if name == DETERMINISTIC_TOOL else "isolated_python"},
    )


def _call_deterministic(args: dict[str, Any]) -> ToolExecutionResult:
    try:
        table, unit = _deterministic_table(args)
        payload = computation.build_result(
            run_id=str(args.get("run_id") or "unbound"),
            tool_run_id=str(args.get("tool_run_id") or new_id("tool")),
            status="succeeded",
            input_revision=int(args.get("input_revision") or 0),
            table={**table, "unit": unit or table.get("unit", "")},
            source_refs=[str(ref) for ref in args.get("source_refs") or []],
            engine="deterministic",
        )
    except (deterministic_compute.ComputeError, computation.ComputationError, ValueError) as exc:
        return ToolExecutionResult(tool_name=DETERMINISTIC_TOOL, status="failed", reason=str(exc))
    return ToolExecutionResult(tool_name=DETERMINISTIC_TOOL, status="succeeded", output=payload.to_payload())


def _deterministic_table(args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    mode = str(args.get("mode") or "")
    unit = str(args.get("unit") or "")
    if mode == "expression":
        value = deterministic_compute.evaluate_expression(
            str(args.get("expression") or ""),
            {str(k): float(v) for k, v in (args.get("variables") or {}).items()},
        )
        return {"columns": ["结果"], "rows": [[value]], "unit": unit}, unit
    if mode == "summarize":
        stats = deterministic_compute.summarize(
            [float(v) for v in args.get("values") or []],
            [str(op) for op in (args.get("statistic") and [args["statistic"]] or deterministic_compute.SUM_OPS)],
        )
        return {"columns": ["指标", "数值"], "rows": [[k, v] for k, v in stats.items()], "unit": unit}, unit
    if mode == "table":
        series = {str(k): [float(v) for v in values] for k, values in (args.get("series") or {}).items()}
        table = deterministic_compute.comparison_table(series, statistic=str(args.get("statistic") or "mean"), unit=unit)
        return table, unit
    raise deterministic_compute.ComputeError("unknown mode")


def _call_isolated(args: dict[str, Any], runner: IsolatedPythonRunner) -> ToolExecutionResult:
    if not runner.available():
        return ToolExecutionResult(
            tool_name=ISOLATED_PYTHON_TOOL,
            status="blocked",
            reason="isolation_unavailable",
            output=computation.build_result(
                run_id=str(args.get("run_id") or "unbound"),
                tool_run_id=str(args.get("tool_run_id") or new_id("tool")),
                status="blocked",
                input_revision=int(args.get("input_revision") or 0),
                source_refs=[str(ref) for ref in args.get("source_refs") or []],
                engine="isolated_python",
                reason="isolation_unavailable",
            ).to_payload(),
        )
    try:
        outcome = runner.run(str(args["code"]), timeout_seconds=args.get("timeout_seconds"))
    except IsolationUnavailable as exc:
        return ToolExecutionResult(tool_name=ISOLATED_PYTHON_TOOL, status="blocked",
                                   reason=f"isolation_unavailable: {exc}")
    if outcome.get("status") != "succeeded":
        return ToolExecutionResult(
            tool_name=ISOLATED_PYTHON_TOOL,
            status="failed",
            reason=str(outcome.get("reason") or outcome.get("status")),
            output={"stderr": outcome.get("stderr", "")[:2000], "truncated": outcome.get("truncated", False)},
        )
    return _bound_isolated_table(args, outcome)


def _bound_isolated_table(args: dict[str, Any], outcome: dict[str, Any]) -> ToolExecutionResult:
    try:
        table = json.loads(str(outcome.get("stdout") or ""))
    except json.JSONDecodeError:
        return ToolExecutionResult(tool_name=ISOLATED_PYTHON_TOOL, status="failed",
                                   reason="output is not a JSON table")
    try:
        payload = computation.build_result(
            run_id=str(args.get("run_id") or "unbound"),
            tool_run_id=str(args.get("tool_run_id") or new_id("tool")),
            status="succeeded",
            input_revision=int(args.get("input_revision") or 0),
            table=table,
            source_refs=[str(ref) for ref in args.get("source_refs") or []],
            engine="isolated_python",
        )
    except computation.ComputationError as exc:
        return ToolExecutionResult(tool_name=ISOLATED_PYTHON_TOOL, status="failed", reason=str(exc))
    return ToolExecutionResult(tool_name=ISOLATED_PYTHON_TOOL, status="succeeded", output=payload.to_payload())
