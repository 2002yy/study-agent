"""Model-call accounting: the run must never record a call it did not make."""

from __future__ import annotations

import json

from src.web.research_tool_agent import (HARD_MODEL_CALL_CAP, MAX_CORRECTIONS, AgentBudget,
                                         run_tool_agent)
from tests.test_research_tool_agent import FakeGateway


def _run(max_rounds: int) -> tuple[dict, int]:
    gateway = FakeGateway()
    calls = {"n": 0}

    def completion(**_kwargs):
        calls["n"] += 1
        # A search that is refused as a duplicate keeps the round loop turning without
        # producing progress, which is exactly the case that used to over-count.
        return json.dumps({"tool": "search", "query": "same query every round"})

    trace = run_tool_agent(
        gateway=gateway, completion=completion, question="Python 是什么？",
        budget=AgentBudget(max_rounds=max_rounds, max_searches=0, max_reads=0,
                           hard_seconds=30.0),
        initial_urls=("https://example.org/a",))
    return trace, calls["n"]


def test_standard_rounds_stop_at_exactly_the_allowance():
    """12 rounds plus the free corrections: 14 real calls, never 15."""
    trace, real_calls = _run(12)
    allowance = min(12 + MAX_CORRECTIONS, HARD_MODEL_CALL_CAP)
    assert trace["cost"]["model_calls"] == allowance == 14
    assert real_calls == trace["cost"]["model_calls"]      # no call recorded that never happened


def test_a_larger_tier_can_reach_the_global_cap_exactly():
    trace, real_calls = _run(20)
    assert trace["cost"]["model_calls"] == HARD_MODEL_CALL_CAP == 22
    assert real_calls == trace["cost"]["model_calls"]


def test_the_recorded_cost_never_exceeds_the_global_cap():
    for rounds in (4, 12, 16, 20, 30):
        trace, real_calls = _run(rounds)
        assert trace["cost"]["model_calls"] <= HARD_MODEL_CALL_CAP
        assert real_calls == trace["cost"]["model_calls"]
