"""Controlled deterministic calculator for arithmetic, statistics and formulas.

This is **not** a Python interpreter and must never be described as one.  It
evaluates a bounded subset of arithmetic/statistical expressions through an
explicit AST node whitelist.  Model-generated source is never executed with
``eval``/``exec``, and no attribute access, subscript, import or statement is
allowed.  It deliberately cannot read files, open sockets or call functions
outside the whitelist.
"""

from __future__ import annotations

import ast
import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

MAX_EXPRESSION_CHARS = 500
MAX_NODES = 200
MAX_POWER = 12.0
MAX_ITEMS = 4096

_AST_ALLOWED = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Call,
    ast.List,
    ast.Tuple,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.UAdd,
    ast.USub,
)

_FUNCTIONS: dict[str, tuple[Any, int, int]] = {
    "abs": (abs, 1, 1),
    "min": (min, 1, MAX_ITEMS),
    "max": (max, 1, MAX_ITEMS),
    "sum": (sum, 1, 1),
    "round": (round, 1, 2),
    "sqrt": (math.sqrt, 1, 1),
    "log": (math.log, 1, 2),
    "log10": (math.log10, 1, 1),
    "exp": (math.exp, 1, 1),
    "hypot": (math.hypot, 2, 2),
    "pow": (pow, 2, 2),
    "mean": (statistics.fmean, 1, 1),
    "median": (statistics.median, 1, 1),
    "stdev": (statistics.pstdev, 1, 1),
    "variance": (statistics.pvariance, 1, 1),
}

SUM_OPS = ("sum", "mean", "median", "min", "max", "stdev", "variance", "count")


class ComputeError(ValueError):
    """Raised when an expression or a numeric input is not acceptable."""


def evaluate_expression(expression: str, variables: Mapping[str, float] | None = None) -> float:
    text = str(expression or "").strip()
    if not text:
        raise ComputeError("expression is required")
    if len(text) > MAX_EXPRESSION_CHARS:
        raise ComputeError("expression is too long")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ComputeError("expression is not valid arithmetic") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise ComputeError("expression is too complex")
    names = {str(key): _finite(value) for key, value in (variables or {}).items()}
    value = _eval_node(tree.body, names)
    return _finite(value)


def _eval_node(node: ast.AST, names: Mapping[str, float]) -> float:
    if not isinstance(node, _AST_ALLOWED):
        raise ComputeError(f"unsupported construct: {type(node).__name__}")
    if isinstance(node, ast.Constant):
        return _finite(node.value)
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise ComputeError(f"unknown name: {node.id}")
        return names[node.id]
    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, names)
        return operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.BinOp):
        return _eval_binop(node, names)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_node(item, names) for item in node.elts]  # type: ignore[return-value]
    if isinstance(node, ast.Call):
        return _eval_call(node, names)
    raise ComputeError(f"unsupported construct: {type(node).__name__}")


def _eval_binop(node: ast.BinOp, names: Mapping[str, float]) -> float:
    left = _eval_node(node.left, names)
    right = _eval_node(node.right, names)
    try:
        if isinstance(node.op, ast.Add):
            return _finite(left + right)
        if isinstance(node.op, ast.Sub):
            return _finite(left - right)
        if isinstance(node.op, ast.Mult):
            return _finite(left * right)
        if isinstance(node.op, ast.Div):
            return _finite(left / right)
        if isinstance(node.op, ast.FloorDiv):
            return _finite(left // right)
        if isinstance(node.op, ast.Mod):
            return _finite(left % right)
        if isinstance(node.op, ast.Pow):
            if abs(float(right)) > MAX_POWER:
                raise ComputeError("exponent is out of bounds")
            return _finite(left**right)
    except ZeroDivisionError as exc:
        raise ComputeError("division by zero") from exc
    raise ComputeError("unsupported operator")


def _eval_call(node: ast.Call, names: Mapping[str, float]) -> float:
    if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
        raise ComputeError("function is not allowed")
    if node.keywords:
        raise ComputeError("keyword arguments are not allowed")
    func, low, high = _FUNCTIONS[node.func.id]
    if not low <= len(node.args) <= high:
        raise ComputeError(f"{node.func.id} received an invalid number of arguments")
    args = [_eval_node(arg, names) for arg in node.args]
    try:
        return _finite(func(*args))
    except (TypeError, ValueError, statistics.StatisticsError) as exc:
        raise ComputeError(f"{node.func.id} failed: {exc}") from exc


def summarize(values: Sequence[float], ops: Sequence[str]) -> dict[str, float]:
    numbers = _numbers(values)
    if not numbers:
        raise ComputeError("no numeric values")
    unknown = [op for op in ops if op not in SUM_OPS]
    if unknown:
        raise ComputeError(f"unknown statistic: {', '.join(unknown)}")
    out: dict[str, float] = {}
    for op in ops:
        if op == "sum":
            out[op] = _finite(sum(numbers))
        elif op == "mean":
            out[op] = _finite(statistics.fmean(numbers))
        elif op == "median":
            out[op] = _finite(statistics.median(numbers))
        elif op == "min":
            out[op] = _finite(min(numbers))
        elif op == "max":
            out[op] = _finite(max(numbers))
        elif op == "stdev":
            out[op] = _finite(statistics.pstdev(numbers))
        elif op == "variance":
            out[op] = _finite(statistics.pvariance(numbers))
        elif op == "count":
            out[op] = float(len(numbers))
    return out


def comparison_table(series: Mapping[str, Sequence[float]], *, statistic: str = "mean", unit: str = "") -> dict[str, Any]:
    """Build a renderable table (one row per named series) from measured values."""

    if statistic not in SUM_OPS:
        raise ComputeError(f"unknown statistic: {statistic}")
    if not series:
        raise ComputeError("no series supplied")
    if len(series) > 12:
        raise ComputeError("too many series")
    rows: list[list[Any]] = []
    for label, values in series.items():
        if not isinstance(label, str) or not label.strip():
            raise ComputeError("series labels must be non-empty strings")
        rows.append([label, summarize(values, [statistic])[statistic]])
    return {"columns": ["方案", statistic], "rows": rows, "unit": str(unit)[:40]}


def _numbers(values: Sequence[float]) -> list[float]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ComputeError("values must be a numeric list")
    if len(values) > MAX_ITEMS:
        raise ComputeError("too many values")
    return [_finite(value) for value in values]


def _finite(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    if not isinstance(value, (int, float)):
        raise ComputeError("value is not a number")
    if not math.isfinite(float(value)):
        raise ComputeError("value is not finite")
    return value
