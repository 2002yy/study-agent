"""Autonomous research path: model chooses, the wrapper bounds."""

from __future__ import annotations

import time
from types import SimpleNamespace

from src.tools.persistent_web_agent import (
    AUTONOMOUS_DEEP_FLAG,
    AUTONOMOUS_RESEARCH_FLAG,
    AutonomousBudget,
    AutonomousToolBudget,
    PersistentWebToolAgent,
    autonomous_budget,
)


class FakeService:
    def __init__(self) -> None:
        self.created: list[tuple[str, dict]] = []
        self.traces: list[tuple[str, dict]] = []
        self.executed: list[str] = []

    def create(self, query: str, **kwargs):
        self.created.append((query, kwargs))
        return SimpleNamespace(id="run-auto", version=1)

    def begin_tool_trace(self, run_id: str) -> str:
        return "op-auto"

    def record_tool_trace(self, run_id: str, **kwargs) -> None:
        self.traces.append((run_id, kwargs))

    def tool_trace_cancel_requested(self, *_args) -> bool:
        return False

    def execute(self, run_id: str):
        self.executed.append(run_id)
        return SimpleNamespace(
            id=run_id,
            research_context={"deep": {}},
            query_attempts=[],
        )


class FakeRunLoop:
    def __init__(self, calls=None) -> None:
        self.calls = calls or []
        self.kwargs: list[dict] = []
        self.messages: list[list[dict]] = []

    def __call__(self, messages, **kwargs):
        self.messages.append(messages)
        self.kwargs.append(kwargs)
        return list(self.calls)


def _agent(run_loop, service=None):
    return PersistentWebToolAgent(
        gateway=SimpleNamespace(),
        research_service=service or FakeService(),
        run_loop=run_loop,
    )


def test_autonomous_normal_research_uses_the_existing_loop(monkeypatch):
    monkeypatch.setenv(AUTONOMOUS_RESEARCH_FLAG, "1")
    monkeypatch.delenv(AUTONOMOUS_DEEP_FLAG, raising=False)
    service = FakeService()
    loop = FakeRunLoop()
    agent = _agent(loop, service)

    trace = agent.resolve(
        "Godot Jolt physics limitations for breakable structures",
        research_intent=True,
    )

    assert trace.run_id == "run-auto"
    assert trace.answer_deadline is not None
    assert service.created[0][1]["run_kind"] == "autonomous_research"
    assert service.created[0][1]["research_mode"] == "standard"
    assert loop.kwargs[0]["task_name"] == "autonomous_research"
    assert loop.kwargs[0]["max_rounds"] == 6
    assert isinstance(loop.kwargs[0]["execute_tool"], AutonomousToolBudget)
    assert "You decide the next action" in loop.messages[0][0]["content"]
    assert "at most 4 searches" in loop.messages[0][0]["content"]
    assert service.traces and service.traces[0][0] == "run-auto"


def test_autonomous_is_off_by_default_and_skips_github_workflows(monkeypatch):
    monkeypatch.delenv(AUTONOMOUS_RESEARCH_FLAG, raising=False)
    loop = FakeRunLoop()
    agent = _agent(loop)
    agent.resolve("research a public topic", research_intent=True)
    assert not loop.kwargs or loop.kwargs[0]["task_name"] != "autonomous_research"

    monkeypatch.setenv(AUTONOMOUS_RESEARCH_FLAG, "1")
    loop2 = FakeRunLoop()
    agent2 = _agent(loop2)
    agent2.resolve("review https://github.com/o/r/pull/1", research_intent=True)
    assert loop2.kwargs and loop2.kwargs[0]["task_name"] != "autonomous_research"


def test_explicit_deep_needs_the_deep_flag(monkeypatch):
    monkeypatch.setenv(AUTONOMOUS_RESEARCH_FLAG, "1")
    monkeypatch.delenv(AUTONOMOUS_DEEP_FLAG, raising=False)
    service = FakeService()
    loop = FakeRunLoop()
    agent = _agent(loop, service)
    agent.resolve("deep topic", research_intent=True, deep_requested=True)
    assert service.executed == ["run-auto"]
    assert not loop.kwargs

    monkeypatch.setenv(AUTONOMOUS_DEEP_FLAG, "1")
    service2 = FakeService()
    loop2 = FakeRunLoop()
    agent2 = _agent(loop2, service2)
    agent2.resolve("deep topic", research_intent=True, deep_requested=True)
    assert loop2.kwargs[0]["task_name"] == "autonomous_research"
    assert loop2.kwargs[0]["max_rounds"] == 10
    assert "at most 8 searches" in loop2.messages[0][0]["content"]
    assert service2.traces[0][0] == "run-auto"


def test_budget_blocks_only_the_exhausted_kind():
    executed: list[str] = []

    def execute(name, arguments):
        executed.append(name)
        return {"ok": True, "name": name}

    budget = AutonomousBudget(
        max_rounds=4, max_searches=1, max_reads=2, max_seconds=60
    )
    gate = AutonomousToolBudget(
        execute, budget, deadline=time.monotonic() + 60
    )

    assert gate("web_search", {"query": "a"})["ok"] is True
    blocked_search = gate("web_search", {"query": "b"})
    assert blocked_search["status"] == "budget_exhausted"
    assert blocked_search["reason"] == "search_quota"

    assert gate("web_read", {"url": "https://a.example"})["ok"] is True
    assert gate("web_read", {"url": "https://b.example"})["ok"] is True
    assert gate("web_read", {"url": "https://c.example"})["reason"] == "read_quota"
    assert executed == ["web_search", "web_read", "web_read"]
    assert "searches 1/1" in gate.usage_line()


def test_wall_clock_blocks_every_tool():
    budget = AutonomousBudget(
        max_rounds=4, max_searches=4, max_reads=4, max_seconds=10
    )
    gate = AutonomousToolBudget(
        lambda name, arguments: {"ok": True},
        budget,
        deadline=100.0,
        clock=lambda: 101.0,
    )

    assert gate("web_search", {"query": "a"})["reason"] == "wall_time"
    assert gate("web_read", {"url": "https://a.example"})["reason"] == "wall_time"


def test_state_provider_reports_budget_without_page_body(monkeypatch):
    monkeypatch.setenv(AUTONOMOUS_RESEARCH_FLAG, "1")
    loop = FakeRunLoop()
    _agent(loop).resolve("research topic", research_intent=True)

    state_provider = loop.kwargs[0]["state_provider"]
    block = state_provider(
        [
            {
                "name": "web_read",
                "arguments": {"url": "https://docs.example.org/a"},
                "result": {
                    "ok": True,
                    "url": "https://docs.example.org/a",
                    "content": "SECRET BODY",
                },
            }
        ],
        2,
    )

    assert "[research_state]" in block
    assert "budget: searches 0/4" in block
    assert "SECRET BODY" not in block


def test_autonomous_budget_defaults_and_env_override(monkeypatch):
    normal = autonomous_budget(deep=False)
    deep = autonomous_budget(deep=True)
    assert (normal.max_rounds, normal.max_searches, normal.max_reads) == (6, 4, 6)
    assert normal.max_seconds == 180
    assert (deep.max_rounds, deep.max_searches, deep.max_reads) == (10, 8, 12)
    assert deep.max_seconds == 600

    monkeypatch.setenv("WEB_AUTONOMOUS_MAX_ROUNDS", "3")
    assert autonomous_budget(deep=False).max_rounds == 3


def test_cancel_requested_stops_the_loop(monkeypatch):
    monkeypatch.setenv(AUTONOMOUS_RESEARCH_FLAG, "1")
    service = FakeService()
    service.tool_trace_cancel_requested = lambda *_args: True
    class CancellingLoop(FakeRunLoop):
        def __call__(self, messages, **kwargs):
            self.kwargs.append(kwargs)
            if kwargs["should_cancel"]():
                raise RuntimeError("tool_loop_cancelled")
            return []

    agent = _agent(CancellingLoop(), service)
    trace = agent.resolve("research topic", research_intent=True)

    assert "tool_loop_cancelled" in trace.error
    assert service.traces and "tool_loop_cancelled" in service.traces[0][1]["error"]
