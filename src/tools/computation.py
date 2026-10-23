"""Authoritative computation-result protocol.

A computation result may only be displayed after the server has validated and
bound it.  A model-supplied chart payload is never trusted, and correct
arithmetic never makes the input data true: research sources still pass the
existing Evidence Gate.

The envelope is intentionally small and explicit so the frontend can render
bar/line/table views from ``result.columns``/``result.rows`` alone, with no
HTML, JavaScript or callbacks travelling from the model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "1"
MAX_COLUMNS = 12
MAX_ROWS = 500
MAX_SOURCE_REFS = 50
MAX_CELL_CHARS = 400

ENGINES = ("deterministic", "isolated_python")
STATUSES = ("succeeded", "failed", "blocked", "cancelled")


class ComputationError(ValueError):
    """Raised when a computation result cannot be bound as authoritative."""


@dataclass(frozen=True)
class ComputationResult:
    run_id: str
    tool_run_id: str
    status: str
    input_revision: int
    result: dict[str, Any] = field(default_factory=dict)
    source_refs: tuple[str, ...] = ()
    engine: str = "deterministic"
    schema_version: str = SCHEMA_VERSION
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "tool_run_id": self.tool_run_id,
            "status": self.status,
            "input_revision": self.input_revision,
            "source_refs": list(self.source_refs),
            "engine": self.engine,
            "reason": self.reason,
            "result": self.result,
        }


def validate_table(table: Any) -> list[str]:
    """Return every reason the table is not renderable; empty means valid."""

    if not isinstance(table, dict):
        return ["result must be an object"]
    problems: list[str] = []
    columns = table.get("columns")
    rows = table.get("rows")
    if not isinstance(columns, list) or not columns:
        problems.append("columns must be a non-empty list")
        columns = []
    if not isinstance(rows, list):
        problems.append("rows must be a list")
        rows = []
    if len(columns) > MAX_COLUMNS:
        problems.append(f"too many columns (max {MAX_COLUMNS})")
    if len(rows) > MAX_ROWS:
        problems.append(f"too many rows (max {MAX_ROWS})")
    seen: set[str] = set()
    for name in columns:
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            problems.append("column names must be short non-empty strings")
            continue
        if name in seen:
            problems.append(f"duplicate column: {name}")
        seen.add(name)
    unit = table.get("unit")
    if unit is not None and (not isinstance(unit, str) or len(unit) > 40):
        problems.append("unit must be a short string")
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(columns):
            problems.append(f"row {index} does not match column count")
            continue
        for cell in row:
            problems.extend(_cell_problems(index, cell))
    return problems


def _cell_problems(row_index: int, cell: Any) -> list[str]:
    if cell is None or isinstance(cell, (str, bool)):
        if isinstance(cell, str) and len(cell) > MAX_CELL_CHARS:
            return [f"row {row_index} cell text too long"]
        return []
    if isinstance(cell, int):
        return []
    if isinstance(cell, float):
        return [] if math.isfinite(cell) else [f"row {row_index} number is not finite"]
    return [f"row {row_index} cell must be a finite number, string, bool or null"]


def build_result(
    *,
    run_id: str,
    tool_run_id: str,
    status: str,
    input_revision: int,
    table: dict[str, Any] | None = None,
    source_refs: tuple[str, ...] | list[str] = (),
    engine: str = "deterministic",
    reason: str = "",
) -> ComputationResult:
    if status not in STATUSES:
        raise ComputationError(f"unknown status: {status}")
    if engine not in ENGINES:
        raise ComputationError(f"unknown engine: {engine}")
    if not str(run_id).strip() or not str(tool_run_id).strip():
        raise ComputationError("run_id and tool_run_id are required")
    if not isinstance(input_revision, int) or input_revision < 0:
        raise ComputationError("input_revision must be a non-negative integer")
    refs = tuple(str(ref) for ref in source_refs)
    if len(refs) > MAX_SOURCE_REFS:
        raise ComputationError(f"too many source_refs (max {MAX_SOURCE_REFS})")
    if any(not ref.strip() for ref in refs):
        raise ComputationError("source_refs must be non-empty strings")
    if status == "succeeded":
        problems = validate_table(table)
        if problems:
            raise ComputationError("; ".join(problems))
    elif table not in (None, {}):
        raise ComputationError("a non-succeeded result must not carry a table")
    return ComputationResult(
        run_id=str(run_id),
        tool_run_id=str(tool_run_id),
        status=status,
        input_revision=input_revision,
        result=dict(table) if table else {},
        source_refs=refs,
        engine=engine,
        reason=reason,
    )


def supersede(previous: dict[str, Any], *, input_revision: int) -> dict[str, Any]:
    """Mark a displayed result stale without overwriting its execution record."""

    updated = dict(previous)
    updated["status"] = "superseded"
    updated["superseded_by_revision"] = input_revision
    return updated
