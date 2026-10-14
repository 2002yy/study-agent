"""Bounded planner compute decision inside the Deep executor."""

from __future__ import annotations

import pytest

from src.tools.compute_tools import register_compute_tools
from src.tools.python_isolation import NullRunner
from src.tools.registry import ToolRegistry
from src.web.research.computation_step import (
    ComputeRequestError,
    bind_source_refs,
    execute_compute,
    parse_compute_request,
)


def registry() -> ToolRegistry:
    return register_compute_tools(ToolRegistry(), NullRunner())


def test_only_declarative_requests_are_accepted():
    assert parse_compute_request(None) is None
    assert parse_compute_request({}) is None
    parsed = parse_compute_request({"engine": "deterministic", "mode": "expression", "expression": "1 + 1"})
    assert parsed == {"engine": "deterministic", "request": {"mode": "expression", "expression": "1 + 1"}}
    with pytest.raises(ComputeRequestError):
        parse_compute_request({"engine": "shell", "mode": "expression"})
    with pytest.raises(ComputeRequestError):
        parse_compute_request({"engine": "deterministic"})  # no computation carried
    with pytest.raises(ComputeRequestError):
        parse_compute_request({"engine": "deterministic", "expression": "1+1"})  # mode missing


def test_execute_binds_run_tool_revision_and_sources():
    parsed = parse_compute_request({"engine": "deterministic", "mode": "expression", "expression": "a + 1", "variables": {"a": 1}})
    payload = execute_compute(
        parsed, registry=registry(), run_id="run-1", tool_run_id="tool-1",
        input_revision=2, source_refs=["s1"], isolation_ready=False,
    )
    assert payload["status"] == "succeeded"
    assert payload["run_id"] == "run-1"
    assert payload["tool_run_id"] == "tool-1"
    assert payload["input_revision"] == 2
    assert payload["source_refs"] == ["s1"]
    assert payload["result"]["rows"] == [[2]]


def test_isolated_request_is_blocked_and_never_downgraded_to_deterministic():
    parsed = parse_compute_request({"engine": "isolated_python", "mode": "expression", "expression": "1 + 1"})
    payload = execute_compute(
        parsed, registry=registry(), run_id="run-1", tool_run_id="tool-1",
        input_revision=0, source_refs=[], isolation_ready=False,
    )
    assert payload["status"] == "blocked"
    assert payload["engine"] == "isolated_python"
    assert payload["reason"] == "isolation_unavailable"


def test_source_refs_are_bounded_and_deduplicated():
    notes = [{"url": url} for url in ["a", "a", "b", "c", "d", "e", "f"]]
    assert bind_source_refs(notes, limit=3) == ["a", "b", "c"]
    assert bind_source_refs([{"url": ""}, {}]) == []
