"""The research stream surfaces the newest authoritative computation."""

from __future__ import annotations

from types import SimpleNamespace

from src.api.routes.chat_routes import _latest_computation


def run_with(computations, *, mode="deep"):
    return SimpleNamespace(research_context={"deep": {"computations": computations}})


def test_no_computation_yields_nothing():
    assert _latest_computation(run_with([])) is None
    assert _latest_computation(SimpleNamespace(research_context={})) is None


def test_only_bound_payloads_are_surfaced():
    entry = {
        "schema_version": "1",
        "run_id": "run-1",
        "tool_run_id": "tool-1",
        "status": "succeeded",
        "input_revision": 1,
        "source_refs": ["s1"],
        "engine": "deterministic",
        "result": {"columns": ["a"], "rows": [[1]], "unit": ""},
        "round": 1,
        "at": "now",
    }
    payload = _latest_computation(run_with([entry]))
    assert payload is not None
    assert payload["tool_run_id"] == "tool-1"
    assert payload["result"]["rows"] == [[1]]
    # Internal bookkeeping fields are not leaked to the client.
    assert "round" not in payload and "at" not in payload


def test_unbound_entry_is_ignored():
    assert _latest_computation(run_with([{"round": 1, "at": "now"}])) is None
