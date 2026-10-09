"""Bounded rational arithmetic on decimal literals. No eval or executable calls.

PASS means arithmetic under the supplied formula only; its factual assumptions
and applicability remain unverified. Unsupported syntax yields UNKNOWN.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from decimal import (
    Decimal,
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    localcontext,
)
from fractions import Fraction
import re
from typing import Mapping

_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
_ROUNDING = {
    "half_even": ROUND_HALF_EVEN,
    "half_up": ROUND_HALF_UP,
    "floor": ROUND_FLOOR,
    "ceiling": ROUND_CEILING,
}


@dataclass(frozen=True)
class CalculationCheck:
    status: str
    reason: str
    exact_value: str = ""
    semantic_support: str = "UNKNOWN"


def _bounded(value: Fraction) -> Fraction:
    if value.numerator.bit_length() > 1024 or value.denominator.bit_length() > 1024:
        raise ValueError("number_limit")
    return value


def _number(value: str) -> Fraction:
    if not isinstance(value, str) or len(value) > 120 or not _NUMBER.fullmatch(value):
        raise ValueError("invalid_decimal")
    decimal = Decimal(value)
    exponent = decimal.as_tuple().exponent
    if not decimal.is_finite() or not isinstance(exponent, int) or abs(exponent) > 100:
        raise ValueError("number_limit")
    return _bounded(Fraction(decimal))


def _tree(expression: str) -> ast.AST:
    if not isinstance(expression, str) or len(expression) > 512:
        raise ValueError("expression_limit")
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise ValueError("expression_limit")
    return tree.body


def _evaluate(
    node: ast.AST, source: str, variables: Mapping[str, Fraction]
) -> Fraction:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return _number(ast.get_source_segment(source, node) or "")
    if isinstance(node, ast.Name) and node.id in variables:
        return variables[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate(node.operand, source, variables)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left, source, variables)
        right = _evaluate(node.right, source, variables)
        if isinstance(node.op, ast.Add):
            return _bounded(left + right)
        if isinstance(node.op, ast.Sub):
            return _bounded(left - right)
        if isinstance(node.op, ast.Mult):
            return _bounded(left * right)
        if isinstance(node.op, ast.Div):
            return _bounded(left / right)
        if isinstance(node.op, ast.Pow) and right.denominator == 1 and abs(right) <= 8:
            return _bounded(left ** int(right))
    raise ValueError("unsupported_expression")


def evaluate(expression: str, variables: Mapping[str, str] | None = None) -> Fraction:
    """Pure arithmetic; max 32 bounded decimal variables, 64 AST nodes."""
    if variables is not None and len(variables) > 32:
        raise ValueError("variable_limit")
    values = {name: _number(value) for name, value in (variables or {}).items()}
    return _evaluate(_tree(expression), expression, values)


def _matches(value: Fraction, claimed: str, places: int | None, rounding: str) -> bool:
    if places is None:
        return value == _number(claimed)
    if type(places) is not int or not 0 <= places <= 12 or rounding not in _ROUNDING:
        raise ValueError("rounding_unverified")
    with localcontext() as context:
        context.prec = 400
        rounded = (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
            Decimal(1).scaleb(-places), rounding=_ROUNDING[rounding]
        )
    return Fraction(rounded) == _number(claimed)


def check_calculation(
    expression: str,
    claimed: str,
    *,
    variables: Mapping[str, str] | None = None,
    places: int | None = None,
    rounding: str = "half_even",
) -> CalculationCheck:
    try:
        value = evaluate(expression, variables)
        match = _matches(value, claimed, places, rounding)
    except (ValueError, TypeError, SyntaxError, ArithmeticError, RecursionError):
        return CalculationCheck("UNKNOWN", "unsupported_or_invalid_calculation")
    return CalculationCheck(
        "PASS" if match else "FAIL",
        "arithmetic_matches" if match else "arithmetic_mismatch",
        str(value),
    )


def _affine(node: ast.AST, source: str, variable: str) -> tuple[Fraction, Fraction]:
    """Prove linearity structurally, never infer it from sampled values."""
    if isinstance(node, ast.Name) and node.id == variable:
        return Fraction(1), Fraction(0)
    if isinstance(node, ast.Constant):
        return Fraction(0), _evaluate(node, source, {})
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        a, b = _affine(node.operand, source, variable)
        return (-a, -b) if isinstance(node.op, ast.USub) else (a, b)
    if isinstance(node, ast.BinOp):
        a, b = _affine(node.left, source, variable)
        c, d = _affine(node.right, source, variable)
        if isinstance(node.op, ast.Add):
            return _bounded(a + c), _bounded(b + d)
        if isinstance(node.op, ast.Sub):
            return _bounded(a - c), _bounded(b - d)
        if isinstance(node.op, ast.Mult) and not (a and c):
            return _bounded(a * d + c * b), _bounded(b * d)
        if isinstance(node.op, ast.Div) and not c:
            return _bounded(a / d), _bounded(b / d)
    raise ValueError("nonlinear_or_unsupported_boundary")


def check_boundary(
    left: str,
    right: str,
    variable: str,
    claimed: str,
    *,
    below: str,
    above: str,
    below_relation: str,
    above_relation: str,
    places: int | None = None,
    rounding: str = "half_even",
) -> CalculationCheck:
    try:
        a, b = _affine(_tree(left), left, variable)
        c, d = _affine(_tree(right), right, variable)
        slope = a - c
        root = _bounded((d - b) / slope)
        if not _matches(root, claimed, places, rounding):
            return CalculationCheck("FAIL", "boundary_mismatch", str(root))
        low, high = _number(below), _number(above)
        if not low < root < high:
            return CalculationCheck(
                "UNKNOWN", "probes_do_not_bracket_boundary", str(root)
            )
        if below_relation not in {"<", ">"} or above_relation not in {"<", ">"}:
            return CalculationCheck(
                "UNKNOWN", "unsupported_boundary_relation", str(root)
            )
        low_relation = "<" if slope * (low - root) < 0 else ">"
        high_relation = "<" if slope * (high - root) < 0 else ">"
        ok = (low_relation, high_relation) == (below_relation, above_relation)
        return CalculationCheck(
            "PASS" if ok else "FAIL",
            "boundary_and_sides_match" if ok else "boundary_sides_reversed",
            str(root),
        )
    except (ValueError, TypeError, SyntaxError, ArithmeticError, RecursionError):
        return CalculationCheck("UNKNOWN", "unsupported_or_invalid_boundary")
