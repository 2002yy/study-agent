from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.llm_client import run_tool_loop
from src.tools.web_agent import WebToolAgent
from src.web.tool_gateway import _DuckDuckGoResultsParser


def test_tool_loop_executes_function_calls_and_returns_evidence(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("MODEL_FLASH_NAME", "test-flash")
    monkeypatch.setenv("MODEL_PRO_NAME", "test-pro")

    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="web_search", arguments='{"query":"FastAPI release"}'),
    )
    responses = iter(
        [
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tool_call]))]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="TOOL_RESEARCH_COMPLETE", tool_calls=[]))]),
        ]
    )
    requests: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            requests.append(kwargs)
            return next(responses)

    monkeypatch.setattr(
        "src.llm_client.get_client",
        lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )

    evidence = run_tool_loop(
        [{"role": "user", "content": "latest FastAPI release"}],
        tools=[{"type": "function", "function": {"name": "web_search"}}],
        execute_tool=lambda name, arguments: {"name": name, "query": arguments["query"]},
        max_rounds=2,
        timeout=12.0,
    )

    assert evidence == [
        {
            "name": "web_search",
            "arguments": {"query": "FastAPI release"},
            "result": {"name": "web_search", "query": "FastAPI release"},
        }
    ]
    assert requests[0]["tool_choice"] == "auto"
    assert requests[0]["timeout"] == 12.0
    assert requests[1]["messages"][-2]["role"] == "assistant"
    assert requests[1]["messages"][-1]["role"] == "tool"


def test_tool_loop_stops_before_provider_request_when_cancelled(monkeypatch):
    monkeypatch.setattr(
        "src.llm_client.get_client",
        lambda **kwargs: pytest.fail("provider must not be called after cancellation"),
    )

    with pytest.raises(RuntimeError, match="tool_loop_cancelled"):
        run_tool_loop(
            [{"role": "user", "content": "cancel me"}],
            tools=[{"type": "function", "function": {"name": "web_search"}}],
            execute_tool=lambda _name, _arguments: {},
            should_cancel=lambda: True,
        )


def test_web_agent_formats_model_selected_results_as_context():
    class FakeGateway:
        def search(self, query, *, max_results):
            return [{"title": query, "url": "https://example.com", "source": "test"}]

        def read(self, url, *, max_chars):
            return {"ok": "true", "url": url, "content": "page text"}

    def run_loop(messages, *, execute_tool, **kwargs):
        return [
            {
                "name": "web_search",
                "arguments": {"query": "official docs"},
                "result": execute_tool("web_search", {"query": "official docs"}),
            },
            {
                "name": "web_read",
                "arguments": {"url": "https://example.com"},
                "result": execute_tool("web_read", {"url": "https://example.com"}),
            },
        ]

    trace = WebToolAgent(gateway=FakeGateway(), run_loop=run_loop).resolve("what changed?")

    assert trace.used is True
    assert "模型联网工具结果" in trace.context_block()
    assert "https://example.com" in trace.context_block()


def test_duckduckgo_parser_keeps_only_public_result_links():
    parser = _DuckDuckGoResultsParser()
    parser.feed(
        '<a class="result__a" href="https://example.com/a">Example result</a>'
        '<a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.org%2Fb">Second</a>'
    )
    assert parser.results == [
        {"title": "Example result", "url": "https://example.com/a"},
        {"title": "Second", "url": "https://example.org/b"},
    ]
