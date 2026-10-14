"""Controlled deterministic calculator: no arbitrary Python execution."""

from __future__ import annotations

import pytest

from src.tools.deterministic_compute import (
    ComputeError,
    comparison_table,
    evaluate_expression,
    summarize,
)


def test_arithmetic_and_variables():
    assert evaluate_expression("2 + 3 * 4") == 14
    assert evaluate_expression("(a + b) / 2", {"a": 10, "b": 20}) == 15
    assert evaluate_expression("round(sqrt(2), 3)") == 1.414


def test_statistics_summary_and_table():
    stats = summarize([1, 2, 3, 4], ["sum", "mean", "median", "stdev", "count"])
    assert stats["sum"] == 10
    assert stats["mean"] == 2.5
    assert stats["median"] == 2.5
    assert stats["count"] == 4
    built = comparison_table({"A": [12.5, 11.0], "B": [9.8, 10.2]}, unit="seconds")
    assert built["columns"] == ["方案", "mean"]
    assert built["rows"] == [["A", pytest.approx(11.75)], ["B", pytest.approx(10.0)]]
    assert built["unit"] == "seconds"


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",     # import / attribute
        "open('/etc/passwd').read()",        # host file read
        "(1).__class__",                     # attribute access
        "eval('1+1')",                       # nested eval
        "exec('x=1')",                       # statement
        "sqrt.__call__(9)",                  # attribute call
        "unknown_name + 1",                  # unknown variable
        "2 ** 1000",                         # unbounded power
        "1 / 0",                             # division by zero
        "[x for x in range(3)]",             # comprehension
        "lambda: 1",                         # lambda
    ],
)
def test_unsafe_or_unknown_constructs_are_rejected(expression):
    with pytest.raises(ComputeError):
        evaluate_expression(expression)


def test_non_finite_and_oversized_inputs_are_rejected():
    with pytest.raises(ComputeError):
        evaluate_expression("1e308 * 1e308")
    with pytest.raises(ComputeError):
        summarize([1, 2], ["bogus"])
    with pytest.raises(ComputeError):
        comparison_table({"A": list(range(5000))})
