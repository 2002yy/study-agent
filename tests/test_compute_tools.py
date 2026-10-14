"""Compute tools reuse the registry and return only validated envelopes."""

from __future__ import annotations

from src.tools.compute_tools import DETERMINISTIC_TOOL, ISOLATED_PYTHON_TOOL, register_compute_tools
from src.tools.python_isolation import NullRunner
from src.tools.registry import ToolRegistry


class FakeRunner:
    def __init__(self, *, available=True, result=None):
        self._available = available
        self.result = result or {"status": "succeeded", "stdout": '{"columns":["a"],"rows":[[1]]}', "stderr": "", "truncated": False}
        self.executed: list[str] = []

    def available(self) -> bool:
        return self._available

    def run(self, code, *, timeout_seconds=None):
        self.executed.append(code)
        return self.result


def registry(runner) -> ToolRegistry:
    return register_compute_tools(ToolRegistry(), runner)


def test_isolated_python_is_blocked_and_never_falls_back_to_host():
    fake = FakeRunner(available=False)
    result = registry(fake).call(ISOLATED_PYTHON_TOOL, {"code": "print(1)", "run_id": "r", "input_revision": 1})
    assert result.status == "blocked"
    assert result.reason == "isolation_unavailable"
    assert result.output["status"] == "blocked"
    assert fake.executed == []  # untrusted code is not executed anywhere else


def test_isolated_python_binds_a_validated_table():
    fake = FakeRunner()
    result = registry(fake).call(
        ISOLATED_PYTHON_TOOL,
        {"code": "print('{}')", "run_id": "run-9", "input_revision": 2, "source_refs": ["s1"]},
    )
    assert result.status == "succeeded"
    assert result.output["engine"] == "isolated_python"
    assert result.output["run_id"] == "run-9"
    assert result.output["input_revision"] == 2
    assert result.output["source_refs"] == ["s1"]
    assert fake.executed == ["print('{}')"]


def test_illegal_chart_output_is_rejected_before_render():
    for bad in ("not json", '{"columns":["a"],"rows":[["x","y"]]}', '{"columns":["a"],"rows":[[NaN]]}'):
        result = registry(FakeRunner(result={"status": "succeeded", "stdout": bad, "stderr": "", "truncated": False})).call(
            ISOLATED_PYTHON_TOOL, {"code": "print(1)"}
        )
        assert result.status == "failed"


def test_default_runner_is_fail_closed():
    result = register_compute_tools(ToolRegistry(), NullRunner()).call(ISOLATED_PYTHON_TOOL, {"code": "print(1)"})
    assert result.status == "blocked"


def test_deterministic_tool_returns_bound_envelope():
    result = registry(NullRunner()).call(
        DETERMINISTIC_TOOL,
        {"mode": "expression", "expression": "a * 2", "variables": {"a": 21}, "run_id": "run-1", "input_revision": 3, "source_refs": ["s1"]},
    )
    assert result.status == "succeeded"
    assert result.output["engine"] == "deterministic"
    assert result.output["result"]["rows"] == [[42]]
    assert result.output["source_refs"] == ["s1"]


def test_deterministic_tool_rejects_bad_input():
    result = registry(NullRunner()).call(DETERMINISTIC_TOOL, {"mode": "expression", "expression": "__import__('os')"})
    assert result.status == "failed"
