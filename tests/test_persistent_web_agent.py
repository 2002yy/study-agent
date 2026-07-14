from __future__ import annotations

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
