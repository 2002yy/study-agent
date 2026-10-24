"""Authoritative computation-result protocol."""

from __future__ import annotations

import pytest

from src.tools.computation import (
    ComputationError,
    build_result,
    supersede,
    validate_table,
)


def table(**overrides):
    base = {"columns": ["方案", "耗时"], "rows": [["A", 12.5], ["B", 9.8]], "unit": "seconds"}
    return base | overrides


def test_valid_result_binds_identity_and_sources():
    payload = build_result(
        run_id="run-1", tool_run_id="tool-1", status="succeeded",
        input_revision=2, table=table(), source_refs=["source-1"],
    ).to_payload()
    assert payload["schema_version"] == "1"
    assert payload["run_id"] == "run-1"
    assert payload["tool_run_id"] == "tool-1"
    assert payload["status"] == "succeeded"
    assert payload["input_revision"] == 2
    assert payload["source_refs"] == ["source-1"]
    assert payload["result"]["unit"] == "seconds"


@pytest.mark.parametrize(
    "bad",
    [
        {"columns": ["a"], "rows": [["x", "y"]]},          # ragged row
        {"columns": ["a", "a"], "rows": [[1, 2]]},          # duplicate column
        {"columns": ["a"], "rows": [[float("nan")]]},       # non-finite
        {"columns": ["a"], "rows": [[float("inf")]]},       # non-finite
        {"columns": ["a"], "rows": [{"x": 1}]},             # not a row
        {"columns": ["a"], "rows": [[{"nested": 1}]]},      # nested object
        {"columns": [], "rows": []},                        # no columns
        {"columns": ["a"], "rows": [[1]] * 501},            # too many rows
    ],
)
def test_illegal_chart_data_is_rejected(bad):
    assert validate_table(bad)
    with pytest.raises(ComputationError):
        build_result(run_id="r", tool_run_id="t", status="succeeded", input_revision=0, table=bad)


def test_identity_and_status_are_enforced():
    with pytest.raises(ComputationError):
        build_result(run_id="", tool_run_id="t", status="succeeded", input_revision=0, table=table())
    with pytest.raises(ComputationError):
        build_result(run_id="r", tool_run_id="t", status="done", input_revision=0, table=table())
    with pytest.raises(ComputationError):
        build_result(run_id="r", tool_run_id="t", status="succeeded", input_revision=-1, table=table())
    with pytest.raises(ComputationError):
        build_result(run_id="r", tool_run_id="t", status="failed", input_revision=0, table=table())


def test_failure_carries_no_table_and_supersede_marks_stale():
    failed = build_result(
        run_id="r", tool_run_id="t", status="failed", input_revision=1, reason="boom"
    ).to_payload()
    assert failed["result"] == {}
    stale = supersede(failed, input_revision=2)
    assert stale["status"] == "superseded"
    assert stale["superseded_by_revision"] == 2
