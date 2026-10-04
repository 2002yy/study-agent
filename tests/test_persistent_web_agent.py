from __future__ import annotations

from concurrent.futures import TimeoutError as FutureTimeout
from types import SimpleNamespace

import src.tools.persistent_web_agent as persistent_web_agent
from src.tools.persistent_web_agent import PersistentWebToolAgent


class FakeGateway:
    def search_exact(self, query: str, *, max_results: int) -> dict:
        self.query = query
        return {
            "status": "ok",
            "reason": "results_found",
            "query": query,
            "results": [
                {
                    "title": f"{query} reference",
                    "url": "https://example.test/source",
                    "snippet": "source summary",
                }
            ][:max_results],
            "provider_errors": [],
            "providers_attempted": ["test"],
        }

    def github_pr_review_context(self, repo_url: str, number: int, **kwargs) -> dict:
        return {
            "ok": True,
            "repository": repo_url,
            "number": number,
            "kwargs": kwargs,
            "verdict": {"status": "not_generated"},
        }

    def read(self, url: str, *, max_chars: int, timeout: float | None = None) -> dict:
        return {
            "ok": True,
            "url": url,
            "content": f"Reference body: {self.query}"[:max_chars],
            "method": "test_read",
        }


def test_persistent_agent_exposes_and_executes_pr_review_context_tool():
    captured: dict = {}

    def run_loop(_messages, *, tools, execute_tool, **_kwargs):
        names = [tool["function"]["name"] for tool in tools]
        captured["names"] = names
        result = execute_tool(
            "github_pr_review_context",
            {
                "repo_url": "https://github.com/openai/example",
                "number": 7,
                "max_files": 10,
                "max_symbols": 20,
            },
        )
        return [
            {
                "name": "github_pr_review_context",
                "arguments": {"number": 7},
                "result": result,
            }
        ]

    agent = PersistentWebToolAgent(
        gateway=FakeGateway(),  # type: ignore[arg-type]
        run_loop=run_loop,
    )
    trace = agent.resolve("Review PR 7 with evidence")

    assert "github_pr_review_context" in captured["names"]
    assert trace.used is True
    result = trace.calls[0]["result"]
    assert result["ok"] is True
    assert result["number"] == 7
    assert result["kwargs"]["max_files"] == 10
    assert result["kwargs"]["max_symbols"] == 20
    assert result["verdict"]["status"] == "not_generated"


def test_persistent_agent_owns_and_records_chat_research_run():
    captured: dict = {}

    class FakeResearchService:
        def create(self, query: str, **kwargs):
            captured["create"] = {"query": query, **kwargs}
            return SimpleNamespace(id="web_lookup_chat_1")

        def record_tool_trace(self, run_id: str, **kwargs):
            captured["record"] = {"run_id": run_id, **kwargs}

        def begin_tool_trace(self, run_id: str):
            captured["begin"] = run_id
            return "operation-1"

        def tool_trace_cancel_requested(self, _run_id: str, _operation_id: str):
            return False

    def run_loop(_messages, **_kwargs):
        return [
            {
                "name": "web_search",
                "arguments": {"query": "durable research"},
                "result": {"status": "ok"},
            }
        ]

    agent = PersistentWebToolAgent(
        gateway=FakeGateway(),  # type: ignore[arg-type]
        run_loop=run_loop,
        research_service=FakeResearchService(),  # type: ignore[arg-type]
    )
    trace = agent.resolve(
        "Research durable runs",
        owner_thread_id="thread-1",
        owner_turn_id="turn-1",
    )

    assert trace.run_id == "web_lookup_chat_1"
    assert trace.to_dict()["run_id"] == "web_lookup_chat_1"
    assert captured["create"] == {
        "query": "Research durable runs",
        "owner_thread_id": "thread-1",
        "owner_turn_id": "turn-1",
        "run_kind": "chat_tool_loop",
    }
    assert captured["record"]["run_id"] == "web_lookup_chat_1"
    assert captured["record"]["calls"] == list(trace.calls)
    assert captured["record"]["operation_id"] == "operation-1"


def test_persistent_agent_fails_soft_when_total_budget_expires(monkeypatch):
    captured: dict = {}

    class FakeResearchService:
        def create(self, _query: str, **_kwargs):
            return SimpleNamespace(id="web_lookup_timeout")

        def begin_tool_trace(self, _run_id: str):
            return "operation-timeout"

        def tool_trace_cancel_requested(self, _run_id: str, _operation_id: str):
            return False

        def record_tool_trace(self, run_id: str, **kwargs):
            captured["record"] = {"run_id": run_id, **kwargs}

    class TimedOutFuture:
        def result(self, *, timeout: float):
            captured["timeout"] = timeout
            raise FutureTimeout

        def cancel(self):
            captured["cancelled"] = True
            return True

    def submit(_function, _messages, **_kwargs):
        captured["request_max_retries"] = _kwargs["request_max_retries"]
        return TimedOutFuture()

    monkeypatch.setenv("WEB_TOOL_TOTAL_BUDGET_SECONDS", "7")
    agent = PersistentWebToolAgent(
        gateway=FakeGateway(),  # type: ignore[arg-type]
        research_service=FakeResearchService(),  # type: ignore[arg-type]
        submit_tool_loop=submit,
    )

    trace = agent.resolve("Review GitHub PR 42 within a bounded time")

    assert captured["timeout"] == 7.0
    assert captured["request_max_retries"] == 0
    assert captured["cancelled"] is True
    assert trace.run_id == "web_lookup_timeout"
    assert "TimeoutError" in trace.error
    assert "7 秒总预算" in trace.error
    assert captured["record"]["operation_id"] == "operation-timeout"
    assert captured["record"]["calls"] == []
    assert "7 秒总预算" in captured["record"]["error"]


def test_six_consecutive_timeouts_each_settle_without_shared_pool_starvation(
    monkeypatch,
):
    executors: list[object] = []

    class FakeResearchService:
        next_id = 0

        def create(self, _query: str, **_kwargs):
            self.next_id += 1
            return SimpleNamespace(id=f"web_lookup_timeout_{self.next_id}")

        def begin_tool_trace(self, _run_id: str):
            return "operation-timeout"

        def tool_trace_cancel_requested(self, _run_id: str, _operation_id: str):
            return False

        def record_tool_trace(self, _run_id: str, **_kwargs):
            return None

    class TimedOutFuture:
        def result(self, *, timeout: float):
            raise FutureTimeout

        def cancel(self):
            return True

    class PerRequestExecutor:
        def __init__(self, **_kwargs):
            self.shutdown_called = False
            executors.append(self)

        def submit(self, *_args, **_kwargs):
            return TimedOutFuture()

        def shutdown(self, *, wait: bool, cancel_futures: bool):
            assert wait is False
            assert cancel_futures is True
            self.shutdown_called = True

    monkeypatch.setenv("WEB_TOOL_TOTAL_BUDGET_SECONDS", "5")
    monkeypatch.setattr(persistent_web_agent, "ThreadPoolExecutor", PerRequestExecutor)
    agent = PersistentWebToolAgent(
        gateway=FakeGateway(),  # type: ignore[arg-type]
        research_service=FakeResearchService(),  # type: ignore[arg-type]
    )

    traces = [agent.resolve(f"Review GitHub PR {index + 1}") for index in range(6)]

    assert len(traces) == 6
    assert len(executors) == 6
    assert all(executor.shutdown_called for executor in executors)
    assert all("5 秒总预算" in trace.error for trace in traces)
    assert traces[-1].run_id == "web_lookup_timeout_6"


def test_ordinary_research_bypasses_slow_model_tool_planner():
    agent = PersistentWebToolAgent(
        gateway=FakeGateway(),  # type: ignore[arg-type]
        run_loop=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ordinary research must not invoke the model tool planner")
        ),
    )

    trace = agent.resolve("Search the official Python documentation")

    assert trace.used is True
    network_calls = [
        row for row in trace.calls if row["name"] in {"web_search", "web_read"}
    ]
    assert [row["name"] for row in network_calls] == ["web_search", "web_read"]
    assert network_calls[0]["result"]["results"][0]["url"] == (
        "https://example.test/source"
    )


def test_explicit_research_searches_first_and_cannot_adopt_search_only_output():
    captured: dict = {}

    def run_loop(*_args, **_kwargs):
        raise AssertionError(
            "A public research query must search before model planning"
        )

    class FailedReadGateway(FakeGateway):
        def read(self, url, **kwargs):
            captured["attempted"] = True
            return {"ok": False, "url": url, "error": "offline_fixture"}

    trace = PersistentWebToolAgent(
        gateway=FailedReadGateway(),  # type: ignore[arg-type]
        run_loop=run_loop,
    ).resolve("请联网研究：opus5", research_intent=True)

    assert captured["attempted"] is True
    assert trace.used is False
    assert trace.to_dict()["evidence_status"] == "candidate_only"
    assert trace.context_block() == ""


def test_multi_aspect_explicit_research_uses_standard_recovery_not_legacy_deep():
    created_queries = []

    class ResearchService:
        def create(self, query, **_kwargs):
            created_queries.append(query)
            return SimpleNamespace(id="research-ordinary")

        def execute(self, *_args):
            raise AssertionError("Standard research must not enter legacy Deep")

        def begin_tool_trace(self, _run_id):
            return "operation-test"

        def tool_trace_cancel_requested(self, *_args):
            return False

        def record_tool_trace(self, *_args, **_kwargs):
            pass

    agent = PersistentWebToolAgent(
        gateway=FakeGateway(), research_service=ResearchService(),
    )
    topic = "opus5.5是什么？性能如何？对比？"
    initial = "联网研究：" + topic
    history = "Research query lead: " + topic
    traces = [agent.resolve(initial, research_intent=True)]
    traces.extend(agent.resolve(control, conversation_context=history) for control in [
        "直接去。不要一次失败就返回", "再查查",
    ])
    assert created_queries == [topic] * 3
    for trace in traces:
        summary = trace.to_dict()["recovery"]
        assert summary["mode"] == "standard"
        assert summary["query"] == topic
        assert summary["limits"]["hard_seconds"] == 60
        assert all("opus5.5" in call["arguments"]["query"] or "opus 5.5" in call["arguments"]["query"].casefold()
                   for call in trace.calls if call["name"] == "web_search")


def test_auto_deep_does_not_slice_an_absent_explicit_prefix(monkeypatch):
    queries = []

    class ResearchService:
        def create(self, query, **_kwargs):
            queries.append(query)
            return SimpleNamespace(id="auto-deep")

        def execute(self, _run_id):
            return SimpleNamespace(id="auto-deep", research_context={}, query_attempts=[])

    monkeypatch.setattr(persistent_web_agent, "_requires_deep_research", lambda _text: True)
    trace = PersistentWebToolAgent(research_service=ResearchService()).resolve(
        "opus5.5 performance comparison"
    )
    assert not trace.error
    assert queries == ["opus5.5 performance comparison"]
