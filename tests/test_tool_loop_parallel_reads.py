"""Independent page reads may share a turn; everything else keeps its order."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from src.llm_client import run_tool_loop
from src.web.tool_gateway import GeneralWebGateway


def _call(index: int, name: str, arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"call_{index}",
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _run(monkeypatch, calls, execute_tool, **kwargs):
    responses = iter(
        [
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
        ]
    )

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
    return run_tool_loop(
        [{"role": "user", "content": "read three pages"}],
        tools=[{"type": "function", "function": {"name": "web_read"}}],
        execute_tool=execute_tool,
        max_rounds=2,
        timeout=5.0,
        **kwargs,
    )


def test_consecutive_page_reads_really_overlap(monkeypatch):
    calls = [
        _call(1, "web_read", {"url": "https://a.example/doc"}),
        _call(2, "web_read", {"url": "https://b.example/doc"}),
        _call(3, "web_read", {"url": "https://c.example/doc"}),
    ]
    barrier = threading.Barrier(3, timeout=5)

    def execute(name, arguments):
        # Block until all three readers are in flight. A sequential loop would
        # break the barrier and turn this into an explicit failure.
        barrier.wait()
        return {"ok": True, "url": arguments["url"]}

    evidence = _run(
        monkeypatch,
        calls,
        execute,
        max_parallel_tools=3,
        parallel_safe=lambda name, _arguments: name == "web_read",
    )

    assert [item["arguments"]["url"] for item in evidence] == [
        "https://a.example/doc",
        "https://b.example/doc",
        "https://c.example/doc",
    ]
    assert all(item["result"]["ok"] for item in evidence)


def test_one_failing_read_does_not_cancel_its_neighbours(monkeypatch):
    calls = [
        _call(1, "web_read", {"url": "https://a.example/doc"}),
        _call(2, "web_read", {"url": "https://b.example/doc"}),
        _call(3, "web_read", {"url": "https://c.example/doc"}),
    ]

    def execute(_name, arguments):
        if arguments["url"].startswith("https://b."):
            raise RuntimeError("backend exploded")
        return {"ok": True, "url": arguments["url"]}

    evidence = _run(
        monkeypatch,
        calls,
        execute,
        max_parallel_tools=3,
        parallel_safe=lambda name, _arguments: name == "web_read",
    )

    assert evidence[0]["result"]["ok"] is True
    assert evidence[1]["result"] == {"error": "RuntimeError: backend exploded"}
    assert evidence[2]["result"]["ok"] is True


def test_without_the_predicate_reads_stay_sequential(monkeypatch):
    calls = [
        _call(1, "web_read", {"url": "https://a.example/doc"}),
        _call(2, "web_read", {"url": "https://b.example/doc"}),
    ]
    active = 0
    peak = 0
    lock = threading.Lock()

    def execute(_name, arguments):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        threading.Event().wait(0.05)
        with lock:
            active -= 1
        return {"ok": True, "url": arguments["url"]}

    _run(monkeypatch, calls, execute, max_parallel_tools=3)

    assert peak == 1


@pytest.fixture
def browse_off(monkeypatch):
    monkeypatch.setattr(
        "src.web.tool_gateway._browse_read_available", lambda: False
    )
    monkeypatch.delenv("WEB_BROWSE_READ_ENABLED", raising=False)


def test_http_reads_are_parallel_safe(browse_off):
    gateway = GeneralWebGateway(search_strategy="research")

    assert gateway.can_read_in_parallel("http", "https://example.org/a") is True
    assert gateway.can_read_in_parallel("auto", "https://example.org/a") is True


def test_browser_or_media_reads_never_join_a_parallel_group(monkeypatch):
    gateway = GeneralWebGateway(search_strategy="research")
    monkeypatch.setenv("WEB_BROWSE_READ_ENABLED", "1")

    assert gateway.can_read_in_parallel("auto", "https://example.org/a") is False
    assert gateway.can_read_in_parallel("browse", "https://example.org/a") is False
    assert gateway.can_read_in_parallel("video", "https://example.org/a") is False
    assert gateway.can_read_in_parallel("audio", "https://example.org/a") is False

    monkeypatch.delenv("WEB_BROWSE_READ_ENABLED", raising=False)
    assert gateway.can_read_in_parallel("auto", "https://example.org/ep.mp3") is False


def test_browser_first_strategy_keeps_reads_sequential(monkeypatch):
    monkeypatch.setattr(
        "src.web.tool_gateway._browse_read_available", lambda: True
    )
    monkeypatch.delenv("WEB_BROWSE_READ_ENABLED", raising=False)
    gateway = GeneralWebGateway(search_strategy="browser_first")

    assert gateway.can_read_in_parallel("auto", "https://example.org/a") is False
    assert gateway.can_read_in_parallel("http", "https://example.org/a") is True
