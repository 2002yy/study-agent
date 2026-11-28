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


def test_autonomous_loop_runs_inside_the_experiment_spend_scope(monkeypatch):
    monkeypatch.setenv(AUTONOMOUS_RESEARCH_FLAG, "1")
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", "rab-test")
    seen: dict[str, str] = {}

    class ScopeLoop(FakeRunLoop):
        def __call__(self, messages, **kwargs):
            from src.llm_spend_guard import current_scope

            scope = current_scope()
            seen["experiment"] = scope.experiment if scope else ""
            seen["purpose"] = scope.purpose if scope else ""
            seen["run_id"] = scope.run_id if scope else ""
            return []

    agent = _agent(ScopeLoop(), FakeService())

    agent.resolve("Godot Jolt limitations", research_intent=True)

    assert seen == {
        "experiment": "rab-test",
        "purpose": "autonomous_research",
        "run_id": "run-auto",
    }


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
    assert loop.kwargs[0]["max_rounds"] == 12
    assert isinstance(loop.kwargs[0]["execute_tool"], AutonomousToolBudget)
    assert "You decide the next action" in loop.messages[0][0]["content"]
    assert "at most 12 model calls" in loop.messages[0][0]["content"]
    assert "12 searches" in loop.messages[0][0]["content"]
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
    assert loop2.kwargs[0]["max_rounds"] == 30
    assert "at most 30 model calls" in loop2.messages[0][0]["content"]
    assert "30 searches" in loop2.messages[0][0]["content"]
    assert service2.traces[0][0] == "run-auto"


def test_budget_blocks_only_the_exhausted_kind():
    executed: list[str] = []

    def execute(name, arguments):
        executed.append(name)
        return {"ok": True, "name": name}

    budget = AutonomousBudget(
        max_rounds=4,
        max_searches=1,
        max_reads=2,
        max_model_calls=4,
        max_tool_calls=10,
        max_seconds=60,
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
        max_rounds=4,
        max_searches=4,
        max_reads=4,
        max_model_calls=4,
        max_tool_calls=10,
        max_seconds=10,
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
    assert "searches 0/12" in block
    assert "SECRET BODY" not in block


def test_autonomous_budget_defaults_and_env_override(monkeypatch):
    normal = autonomous_budget(deep=False)
    deep = autonomous_budget(deep=True)
    assert (normal.max_rounds, normal.max_searches, normal.max_reads) == (12, 12, 20)
    assert (normal.max_model_calls, normal.max_tool_calls) == (12, 40)
    assert normal.max_seconds == 300
    assert (deep.max_rounds, deep.max_searches, deep.max_reads) == (30, 30, 60)
    assert (deep.max_model_calls, deep.max_tool_calls) == (30, 120)
    assert deep.max_seconds == 1800

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


def test_total_tool_quota_blocks_every_kind():
    budget = AutonomousBudget(
        max_rounds=4,
        max_searches=4,
        max_reads=4,
        max_model_calls=4,
        max_tool_calls=1,
        max_seconds=60,
    )
    gate = AutonomousToolBudget(
        lambda _name, _arguments: {"ok": True},
        budget,
        deadline=time.monotonic() + 60,
    )

    assert gate("web_search", {"query": "a"})["ok"] is True
    blocked = gate("web_read", {"url": "https://a.example"})
    assert blocked["reason"] == "tool_quota"


def test_read_receives_the_remaining_wall_time():
    captured: list[float] = []
    budget = AutonomousBudget(
        max_rounds=4,
        max_searches=4,
        max_reads=4,
        max_model_calls=4,
        max_tool_calls=10,
        max_seconds=60,
    )
    gate = AutonomousToolBudget(
        lambda _name, _arguments: {"ok": True},
        budget,
        deadline=100.0,
        clock=lambda: 90.0,
        read_execute=lambda arguments, remaining: (
            captured.append(remaining),
            {"ok": True, "url": arguments["url"]},
        )[1],
    )

    gate("web_read", {"url": "https://a.example"})
    assert captured == [10.0]


def test_partial_rounds_are_persisted_before_the_final_trace(monkeypatch):
    monkeypatch.setenv(AUTONOMOUS_RESEARCH_FLAG, "1")
    service = FakeService()
    partial_calls = [
        {
            "name": "web_read",
            "arguments": {"url": "https://docs.example.org/a"},
            "result": {"ok": True, "url": "https://docs.example.org/a", "content": "x"},
        }
    ]

    class OneRoundLoop(FakeRunLoop):
        def __call__(self, messages, **kwargs):
            kwargs["stop_state"]["reason"] = "deadline"
            kwargs["stop_state"]["model_calls"] = 2
            kwargs["on_round"](partial_calls)
            return partial_calls

    trace = _agent(OneRoundLoop(), service).resolve(
        "research topic", research_intent=True
    )

    assert trace.stop_reason == "deadline"
    assert trace.model_calls == 2
    assert trace.tool_calls == 0
    assert trace.error == ""
    flags = [row[1]["final"] for row in service.traces]
    assert flags == [False, True]
    assert service.traces[0][1]["stop_reason"] == "sources_partially_read"
    assert service.traces[1][1]["stop_reason"] == "sources_partially_read"


def test_provider_failure_keeps_partial_calls_and_reports_the_error(monkeypatch):
    monkeypatch.setenv(AUTONOMOUS_RESEARCH_FLAG, "1")
    service = FakeService()
    calls = [
        {
            "name": "web_read",
            "arguments": {"url": "https://docs.example.org/a"},
            "result": {"ok": True, "url": "https://docs.example.org/a", "content": "x"},
        }
    ]

    class FailingLoop(FakeRunLoop):
        def __call__(self, messages, **kwargs):
            kwargs["stop_state"]["reason"] = "provider_error"
            kwargs["stop_state"]["error"] = "RuntimeError: provider down"
            kwargs["on_round"](calls)
            return calls

    trace = _agent(FailingLoop(), service).resolve(
        "research topic", research_intent=True
    )

    assert "provider down" in trace.error
    assert trace.stop_reason == "provider_error"
    assert [row[1]["final"] for row in service.traces] == [False, True]
    assert service.traces[1][1]["stop_reason"] == "chat_tool_loop_failed"
    assert service.traces[1][1]["calls"] == calls


def test_turn_model_budget_counts_autonomous_calls():
    from types import SimpleNamespace

    import pytest

    from src.application.chat_service import ChatService

    failed: list[object] = []
    fake = SimpleNamespace(fail_turn=lambda prepared: failed.append(prepared))
    prepared = SimpleNamespace(
        rag={"web_tools": {"model_calls": 64, "semantics": None}}
    )

    with pytest.raises(TimeoutError, match="research_model_call_budget_exhausted"):
        ChatService._check_research_model_budget(fake, prepared, 1)
    assert failed


def _budget_for(execute):
    return AutonomousToolBudget(
        execute,
        AutonomousBudget(30, 10, 10, 30, 50, 600),
        time.monotonic() + 300,
        read_execute=lambda arguments, _remaining: execute("web_read", arguments),
        search_execute=lambda arguments, _deadline: execute("web_search", arguments),
    )


def test_duplicate_search_is_refused_without_spending_search_budget():
    executed: list[str] = []

    def execute(name, arguments):
        executed.append(str(arguments.get("query") or arguments.get("url")))
        return {"ok": True, "status": "ok", "results": []}

    budget = _budget_for(execute)
    first = budget("web_search", {"query": "Godot Jolt"})
    second = budget("web_search", {"query": "  Godot   Jolt "})
    changed = budget("web_search", {"query": "Godot Jolt limitations"})

    assert first["status"] == "ok"
    assert second["status"] == "duplicate"
    assert second["reason"] == "duplicate_query"
    assert changed["status"] == "ok"
    assert executed == ["Godot Jolt", "Godot Jolt limitations"]
    assert budget.snapshot()["searches"] == 2


def test_duplicate_successful_read_reuses_the_existing_body():
    executed: list[str] = []

    def execute(_name, arguments):
        executed.append(str(arguments.get("url")))
        return {"ok": True, "url": arguments.get("url"), "content": "body"}

    budget = _budget_for(execute)
    first = budget("web_read", {"url": "https://example.org/a/"})
    second = budget("web_read", {"url": "https://example.org/a"})

    assert first["ok"] is True
    assert second["reason"] == "duplicate_read"
    assert executed == ["https://example.org/a/"]
    assert budget.snapshot()["reads"] == 1


def test_a_failed_read_can_be_retried_with_another_mode():
    executed: list[str] = []

    def execute(_name, arguments):
        executed.append(str(arguments.get("url")))
        return {"ok": False, "url": arguments.get("url"), "error": "js_shell"}

    budget = _budget_for(execute)
    first = budget("web_read", {"url": "https://example.org/a"})
    second = budget("web_read", {"url": "https://example.org/a"})

    assert first["ok"] is False
    assert second["ok"] is False
    assert len(executed) == 2
    assert budget.snapshot()["reads"] == 2

def test_a_short_shell_read_can_be_retried_once_with_browse():
    executed: list[str] = []

    def execute(_name, arguments):
        mode = str(arguments.get("mode") or "auto")
        executed.append(mode)
        if mode == "browse":
            return {"ok": True, "url": arguments.get("url"), "content": "full article " * 100}
        return {"ok": True, "url": arguments.get("url"), "content": "Please enable JavaScript"}

    budget = _budget_for(execute)
    auto = budget("web_read", {"url": "https://example.org/app"})
    browse = budget("web_read", {"url": "https://example.org/app", "mode": "browse"})
    again = budget("web_read", {"url": "https://example.org/app", "mode": "browse"})

    assert auto["ok"] is True
    assert browse["ok"] is True
    assert again["reason"] == "duplicate_read"
    assert executed == ["auto", "browse"]
