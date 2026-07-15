from __future__ import annotations

from types import SimpleNamespace

from src.tools.persistent_web_agent import PersistentWebToolAgent


class FakeGateway:
    def github_pr_review_context(self, repo_url: str, number: int, **kwargs) -> dict:
        return {
            "ok": True,
            "repository": repo_url,
            "number": number,
            "kwargs": kwargs,
            "verdict": {"status": "not_generated"},
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
