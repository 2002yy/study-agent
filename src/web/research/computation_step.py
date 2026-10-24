"""Bounded compute-tool decision inside the Deep research executor.

The agent (planner) may request one computation per revision as a *bounded*
declarative request — never free-form code.  The executor validates the
request, runs it through the already-registered compute tools, binds the
returned envelope to the run and to the sources it used, and stores it
durably.  ``isolated_python`` is never downgraded to ``deterministic`` when the
isolation runtime is unavailable; the request is recorded as blocked instead.
"""

from __future__ import annotations

import json
from typing import Any

from src.tools import computation
from src.tools.python_isolation import isolated_python_available
from src.tools.registry import ToolRegistry

DETERMINISTIC_TOOL = "deterministic_compute"
ISOLATED_TOOL = "isolated_python"
MAX_COMPUTATIONS = 20

_REQUEST_KEYS = ("mode", "expression", "variables", "values", "series", "statistic", "unit")

# Server-authored statistics kernels for the isolated engine.  The model never
# supplies code: it supplies a declarative request and the server generates a
# fixed program from a whitelisted statistic set.
_ISOLATED_STATS = ("sum", "mean", "median", "min", "max", "stdev", "variance", "count")


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


def build_isolated_program(request: dict[str, Any]) -> str:
    """Generate the fixed program the isolated engine runs.

    Only declarative, already-validated inputs are embedded; the model's text is
    never executed.  Expression evaluation deliberately stays in the
    deterministic engine so no model-authored logic reaches the container.
    """

    mode = str(request.get("mode") or "")
    if mode == "expression":
        raise ComputeRequestError("expression stays deterministic; isolated Python runs data processing")
    if mode not in {"summarize", "table"}:
        raise ComputeRequestError(f"isolated Python does not support mode: {mode}")
    statistic = str(request.get("statistic") or "mean")
    if statistic not in _ISOLATED_STATS:
        raise ComputeRequestError(f"unsupported statistic: {statistic}")
    payload = json.dumps({**request, "statistic": statistic})
    return (
        "import json, statistics\n"
        f"DATA = json.loads({json.dumps(payload)})\n"
        "STAT = DATA.get('statistic') or 'mean'\n"
        "UNIT = DATA.get('unit') or ''\n"
        "def stat(values):\n"
        "    values = [float(v) for v in values]\n"
        "    return {'sum': sum, 'mean': statistics.fmean, 'median': statistics.median,\n"
        "            'min': min, 'max': max, 'stdev': statistics.pstdev,\n"
        "            'variance': statistics.pvariance, 'count': len}[STAT](values)\n"
        "if DATA.get('mode') == 'summarize':\n"
        "    table = {'columns': ['指标', '数值'], 'rows': [[STAT, float(stat(DATA.get('values') or []))]], 'unit': UNIT}\n"
        "else:\n"
        "    table = {'columns': ['方案', STAT],\n"
        "             'rows': [[str(label), float(stat(values))] for label, values in (DATA.get('series') or {}).items()],\n"
        "             'unit': UNIT}\n"
        "print(json.dumps(table))\n"
    )


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
    identity = {
        "run_id": run_id,
        "tool_run_id": tool_run_id,
        "input_revision": input_revision,
        "source_refs": list(source_refs),
    }
    if engine == "isolated_python":
        if not ready:
            return _blocked(isolation_unavailable=True, **identity)
        try:
            program = build_isolated_program(parsed["request"])
        except ComputeRequestError as exc:
            return _failed(str(exc), engine=engine, **identity)
        tool, args = ISOLATED_TOOL, {**identity, "code": program}
    else:
        tool, args = DETERMINISTIC_TOOL, {**identity, **parsed["request"]}
    result = registry.call(tool, args)
    payload = result.output if isinstance(result.output, dict) else {}
    if not payload.get("schema_version"):
        return _failed(result.reason or "computation produced no bound result", engine=engine, **identity)
    if payload.get("status") == "succeeded":
        problems = computation.validate_table(payload.get("result"))
        if problems:
            return _failed("; ".join(problems), engine=engine, **identity)
    return payload


def _blocked(*, isolation_unavailable: bool, **identity: Any) -> dict[str, Any]:
    return computation.build_result(
        status="blocked", engine="isolated_python",
        reason="isolation_unavailable" if isolation_unavailable else "blocked",
        **identity,
    ).to_payload()


def _failed(reason: str, *, engine: str, **identity: Any) -> dict[str, Any]:
    return computation.build_result(
        status="failed", engine=engine, reason=reason, **identity
    ).to_payload()


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
