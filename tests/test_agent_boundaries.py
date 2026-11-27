"""P1 boundaries: answer reserve, read tier, partial cancel, checkpoint error."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import src.llm_client as llm_client
from src.tools.persistent_web_agent import (
    AUTONOMOUS_RESEARCH_FLAG,
    autonomous_budget,
)
from src.tools.web_agent import WebToolAgent

from tests.test_autonomous_research import (
    FakeRunLoop,
    FakeService,
    _agent,
)


def _read_call(url: str = "https://docs.example.org/a") -> dict:
    return {
        "name": "web_read",
        "arguments": {"url": url},
        "result": {"ok": True, "url": url, "content": "body"},
    }


def test_autonomous_answer_deadline_keeps_a_generation_reserve(monkeypatch):
    monkeypatch.setenv(AUTONOMOUS_RESEARCH_FLAG, "1")
    monkeypatch.setenv("WEB_AUTONOMOUS_MAX_SECONDS", "30")
    trace = _agent(FakeRunLoop()).resolve("research topic", research_intent=True)

    assert trace.answer_deadline is not None
    assert trace.answer_deadline - time.monotonic() >= 85  # 30s window + 60s writable


def test_page_read_timeout_uses_the_resource_tier_not_the_whole_window():
    captured: list[float] = []

    class Gateway:
        def read(self, url, **kwargs):
            captured.append(kwargs["timeout"])
            return {"ok": True, "url": url, "content": "x"}

    agent = WebToolAgent(gateway=Gateway())  # type: ignore[arg-type]
    agent._read_tool({"url": "https://example.org/story"}, timeout=500)
    agent._read_tool({"url": "https://docs.example.org/guide"}, timeout=500)
    agent._read_tool({"url": "https://example.org/paper.pdf"}, timeout=500)
    agent._read_tool(
        {"url": "https://example.org/video", "mode": "video"}, timeout=500
    )

    assert captured == [15.0, 30.0, 60.0, 330.0]


def test_mid_batch_cancel_keeps_the_completed_batch(monkeypatch):
    calls = [
        SimpleNamespace(
            id=f"c{i}",
            function=SimpleNamespace(
                name="web_read",
                arguments=json.dumps({"url": f"https://{i}.example/doc"}),
            ),
        )
        for i in range(1, 6)
    ]
    responses = iter([
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=None, tool_calls=calls)
                )
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="done", tool_calls=[])
                )
            ]
        ),
    ])

    class Completions:
        def create(self, **_kwargs):
            return next(responses)

    monkeypatch.setattr(
        "src.llm_client.get_client",
        lambda **_kwargs: SimpleNamespace(
            chat=SimpleNamespace(completions=Completions())
        ),
    )
    monkeypatch.setattr(
        "src.llm_client.get_model_name",
        lambda *_args, **_kwargs: "test-model",
    )

    executed: list[str] = []
    stop: dict = {}

    def execute(_name, arguments):
        executed.append(arguments["url"])
        return {"ok": True, "url": arguments["url"]}

    evidence = llm_client.run_tool_loop(
        [{"role": "user", "content": "read"}],
        tools=[{"type": "function", "function": {"name": "web_read"}}],
        execute_tool=execute,
        max_rounds=2,
        max_parallel_tools=3,
        parallel_safe=lambda name, _arguments: name == "web_read",
        should_cancel=lambda: len(executed) >= 3,
        return_partial_on_cancel=True,
        stop_state=stop,
        timeout=5.0,
    )

    assert len(evidence) == 3
    assert stop["reason"] == "cancelled"


def test_request_construction_failure_returns_partial_evidence(monkeypatch):
    calls = [
        SimpleNamespace(
            id="c1",
            function=SimpleNamespace(
                name="web_read",
                arguments=json.dumps({"url": "https://a.example/doc"}),
            ),
        )
    ]
    responses = iter([
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=None, tool_calls=calls)
                )
            ]
        )
    ])

    class Completions:
        def create(self, **_kwargs):
            return next(responses)

    monkeypatch.setattr(
        "src.llm_client.get_client",
        lambda **_kwargs: SimpleNamespace(
            chat=SimpleNamespace(completions=Completions())
        ),
    )
    monkeypatch.setattr(
        "src.llm_client.get_model_name",
        lambda *_args, **_kwargs: "test-model",
    )
    real_build = llm_client._build_request_kwargs

    attempts = {"count": 0}

    def fail_on_second_call(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] >= 2:
            raise RuntimeError("ledger admission failed")
        return real_build(*args, **kwargs)

    monkeypatch.setattr(llm_client, "_build_request_kwargs", fail_on_second_call)

    stop: dict = {}
    evidence = llm_client.run_tool_loop(
        [{"role": "user", "content": "read"}],
        tools=[{"type": "function", "function": {"name": "web_read"}}],
        execute_tool=lambda _name, _arguments: {"ok": True},
        max_rounds=2,
        return_partial_on_error=True,
        stop_state=stop,
        timeout=5.0,
    )

    assert len(evidence) == 1
    assert stop["reason"] == "provider_error"
    assert "ledger admission failed" in stop["error"]


def test_checkpoint_error_is_reported(monkeypatch):
    monkeypatch.setenv(AUTONOMOUS_RESEARCH_FLAG, "1")
    service = FakeService()

    def broken_record(*_args, **_kwargs):
        raise RuntimeError("checkpoint offline")

    service.record_tool_trace = broken_record

    class OneRoundLoop(FakeRunLoop):
        def __call__(self, messages, **kwargs):
            kwargs["on_round"]([_read_call()])
            return [_read_call()]

    trace = _agent(OneRoundLoop(), service).resolve(
        "research topic", research_intent=True
    )

    assert "checkpoint offline" in trace.error


def test_autonomous_max_model_calls_is_capped_at_five(monkeypatch):
    monkeypatch.setenv("WEB_AUTONOMOUS_MAX_MODEL_CALLS", "9")
    assert autonomous_budget(deep=True).max_model_calls == 5
    assert autonomous_budget(deep=False).max_model_calls == 5


def test_autonomous_admits_successful_public_reads_without_discovery(monkeypatch):
    monkeypatch.setenv(AUTONOMOUS_RESEARCH_FLAG, "1")
    service = FakeService()
    user_url = "https://user.example/doc"
    followed_url = "https://docs.example.org/latest/guide"
    failed_url = "https://dead.example/y"
    calls = [
        {
            "name": "web_read",
            "arguments": {"url": user_url},
            "result": {"ok": True, "url": user_url, "content": "user body"},
        },
        {
            "name": "web_read",
            "arguments": {"url": followed_url},
            "result": {
                "ok": True,
                "url": followed_url,
                "content": "followed body",
            },
        },
        {
            "name": "web_read",
            "arguments": {"url": failed_url},
            "result": {"ok": False, "url": failed_url, "error": "timeout"},
        },
    ]

    class Loop(FakeRunLoop):
        def __call__(self, messages, **kwargs):
            return calls

    trace = _agent(Loop(), service).resolve(
        f"请研究 {user_url}", research_intent=True
    )

    assert [row["result"]["url"] for row in trace.evidence_calls] == [
        user_url,
        followed_url,
    ]
    assert trace.rejected_evidence == (
        {"url": failed_url, "reason": "read_failed"},
    )
    assert "user.example" in trace.context_block()
    assert "docs.example.org" in trace.context_block()
    assert "dead.example" not in trace.context_block()
    assert service.traces[-1][1]["user_urls"] == (user_url,)
    assert service.traces[-1][1]["require_discovery"] is False
