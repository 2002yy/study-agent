"""Bounded compute-tool decision inside the Deep research executor.

The agent (planner) may request one computation per revision as a *bounded*
declarative request — never free-form code.  The executor validates the
request, runs it through the already-registered compute tools, binds the
returned envelope to the run and to the sources it used, and stores it
durably.  ``isolated_python`` is never downgraded to ``deterministic`` when the
isolation runtime is unavailable; the request is recorded as blocked instead.
"""

from __future__ import annotations

from typing import Any

from src.tools import computation
from src.tools.python_isolation import isolated_python_available
from src.tools.registry import ToolRegistry

DETERMINISTIC_TOOL = "deterministic_compute"
ISOLATED_TOOL = "isolated_python"
MAX_COMPUTATIONS = 20

_REQUEST_KEYS = ("mode", "expression", "variables", "values", "series", "statistic", "unit")


class ComputeRequestError(ValueError):
    """Raised when a planner compute request is not acceptable."""


def parse_compute_request(raw: Any) -> dict[str, Any] | None:
    """Validate the bounded tool decision; ``None`` means "no computation"."""

    if raw in (None, {}, []):
        return None
    if not isinstance(raw, dict):
        raise ComputeRequestError("compute request must be an object")
    engine = str(raw.get("engine") or "deterministic")
    if engine not in computation.ENGINES:
        raise ComputeRequestError(f"unsupported compute engine: {engine}")
    request = {key: raw[key] for key in _REQUEST_KEYS if key in raw}
    if not request:
        raise ComputeRequestError("compute request carries no computation")
    if not str(request.get("mode", "")).strip():
        raise ComputeRequestError("compute request needs an explicit mode")
    return {"engine": engine, "request": request}


def execute_compute(
    parsed: dict[str, Any],
    *,
    registry: ToolRegistry,
    run_id: str,
    tool_run_id: str,
    input_revision: int,
    source_refs: list[str],
    isolation_ready: bool | None = None,
) -> dict[str, Any]:
    """Run the request and return an authoritative, bound envelope."""

    engine = str(parsed["engine"])
    ready = isolated_python_available() if isolation_ready is None else isolation_ready
    if engine == "isolated_python" and not ready:
        return computation.build_result(
            run_id=run_id,
            tool_run_id=tool_run_id,
            status="blocked",
            input_revision=input_revision,
            source_refs=source_refs,
            engine="isolated_python",
            reason="isolation_unavailable",
        ).to_payload()
    tool = ISOLATED_TOOL if engine == "isolated_python" else DETERMINISTIC_TOOL
    args = {
        **parsed["request"],
        "run_id": run_id,
        "tool_run_id": tool_run_id,
        "input_revision": input_revision,
        "source_refs": list(source_refs),
    }
    result = registry.call(tool, args)
    payload = result.output if isinstance(result.output, dict) else {}
    if not payload.get("schema_version"):
        return computation.build_result(
            run_id=run_id,
            tool_run_id=tool_run_id,
            status="failed",
            input_revision=input_revision,
            source_refs=source_refs,
            engine=engine,
            reason=result.reason or "computation produced no bound result",
        ).to_payload()
    if payload.get("status") == "succeeded":
        problems = computation.validate_table(payload.get("result"))
        if problems:
            return computation.build_result(
                run_id=run_id,
                tool_run_id=tool_run_id,
                status="failed",
                input_revision=input_revision,
                source_refs=source_refs,
                engine=engine,
                reason="; ".join(problems),
            ).to_payload()
    return payload


def bind_source_refs(notes: list[dict[str, Any]], *, limit: int = 8) -> list[str]:
    """Source identity bound to a computation, from the notes actually used."""

    refs: list[str] = []
    for note in notes:
        url = str(note.get("url") or "").strip()
        if url and url not in refs:
            refs.append(url)
        if len(refs) >= limit:
            break
    return refs
