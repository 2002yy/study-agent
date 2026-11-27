"""Tool-loop lifecycle: hard deadline, partial evidence, model-call cap."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.llm_client import run_tool_loop


def _tool_call(call_id: str = "c1", name: str = "web_search") -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(
            name=name, arguments=json.dumps({"query": "q"})
        ),
    )


def _message(calls=None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=calls or [])
            )
        ]
    )


class FakeCompletions:
    def __init__(self, responses) -> None:
        self.responses = iter(responses)
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


def _patch_client(monkeypatch, completions: FakeCompletions) -> None:
    monkeypatch.setattr(
        "src.llm_client.get_client",
        lambda **_kwargs: SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        ),
    )
    monkeypatch.setattr(
        "src.llm_client.get_model_name",
        lambda *_args, **_kwargs: "test-model",
    )


def _run(monkeypatch, completions, execute, **kwargs):
    _patch_client(monkeypatch, completions)
    kwargs.setdefault("timeout", 5.0)
    return run_tool_loop(
        [{"role": "user", "content": "research"}],
        tools=[{"type": "function", "function": {"name": "web_search"}}],
        execute_tool=execute,
        max_rounds=4,
        **kwargs,
    )


def test_deadline_prevents_any_model_call(monkeypatch):
    completions = FakeCompletions([])
    stop: dict = {}

    evidence = _run(
        monkeypatch,
        completions,
        lambda _name, _args: {"ok": True},
        deadline=10.0,
        clock=lambda: 10.0,
        stop_state=stop,
    )

    assert evidence == []
    assert completions.requests == []
    assert stop["reason"] == "deadline"


def test_deadline_after_a_round_keeps_that_round(monkeypatch):
    clock = [0.0]
    completions = FakeCompletions([_message([_tool_call()])])
    stop: dict = {}

    evidence = _run(
        monkeypatch,
        completions,
        lambda _name, _args: (clock.__setitem__(0, 200.0), {"ok": True})[1],
        deadline=100.0,
        clock=lambda: clock[0],
        stop_state=stop,
    )

    assert len(evidence) == 1
    assert evidence[0]["result"] == {"ok": True}
    assert len(completions.requests) == 1
    assert stop["reason"] == "deadline"
    assert stop["model_calls"] == 1


def test_provider_error_returns_partial_evidence_when_asked(monkeypatch):
    completions = FakeCompletions(
        [_message([_tool_call()]), RuntimeError("provider down")]
    )
    stop: dict = {}

    evidence = _run(
        monkeypatch,
        completions,
        lambda _name, _args: {"ok": True},
        return_partial_on_error=True,
        stop_state=stop,
    )

    assert len(evidence) == 1
    assert stop["reason"] == "provider_error"
    assert "provider down" in stop["error"]


def test_provider_error_still_raises_by_default(monkeypatch):
    completions = FakeCompletions(
        [_message([_tool_call()]), RuntimeError("provider down")]
    )

    with pytest.raises(RuntimeError, match="provider"):
        _run(monkeypatch, completions, lambda _name, _args: {"ok": True})


def test_cancel_during_a_round_keeps_that_round(monkeypatch):
    cancelled = [False]
    completions = FakeCompletions([_message([_tool_call()])])
    stop: dict = {}

    def execute(_name, _args):
        cancelled[0] = True
        return {"ok": True}

    evidence = _run(
        monkeypatch,
        completions,
        execute,
        should_cancel=lambda: cancelled[0],
        return_partial_on_cancel=True,
        stop_state=stop,
    )

    assert len(evidence) == 1
    assert stop["reason"] == "cancelled"


def test_model_call_cap_stops_before_another_request(monkeypatch):
    completions = FakeCompletions([_message([_tool_call()])])
    stop: dict = {}

    evidence = _run(
        monkeypatch,
        completions,
        lambda _name, _args: {"ok": True},
        max_model_calls=1,
        stop_state=stop,
    )

    assert len(evidence) == 1
    assert len(completions.requests) == 1
    assert stop["reason"] == "model_call_budget"


def test_round_checkpoint_callback_receives_evidence(monkeypatch):
    completions = FakeCompletions([
        _message([_tool_call("c1")]),
        _message(),
    ])
    seen: list[list[dict]] = []

    evidence = _run(
        monkeypatch,
        completions,
        lambda _name, _args: {"ok": True},
        on_round=lambda rows: seen.append(rows),
    )

    assert len(evidence) == 1
    assert len(seen) == 1
    assert seen[0][0]["result"] == {"ok": True}


def test_request_timeout_is_clamped_to_the_deadline(monkeypatch):
    clock = [0.0]
    completions = FakeCompletions([_message()])

    _run(
        monkeypatch,
        completions,
        lambda _name, _args: {"ok": True},
        timeout=30.0,
        deadline=5.0,
        clock=lambda: clock[0],
    )

    assert completions.requests[0]["timeout"] == 5.0


def test_cancel_between_tool_groups_keeps_completed_calls(monkeypatch):
    cancelled = [False]
    completions = FakeCompletions([_message([_tool_call("c1"), _tool_call("c2")])])
    stop: dict = {}

    def execute(_name, _args):
        cancelled[0] = True
        return {"ok": True}

    evidence = _run(
        monkeypatch,
        completions,
        execute,
        should_cancel=lambda: cancelled[0],
        return_partial_on_cancel=True,
        stop_state=stop,
    )

    assert [row["result"] for row in evidence] == [{"ok": True}]
    assert stop["reason"] == "cancelled"


def test_cancel_between_tool_groups_still_raises_without_partial(monkeypatch):
    cancelled = [False]
    completions = FakeCompletions([_message([_tool_call("c1"), _tool_call("c2")])])

    def execute(_name, _args):
        cancelled[0] = True
        return {"ok": True}

    with pytest.raises(RuntimeError, match="tool_loop_cancelled"):
        _run(
            monkeypatch,
            completions,
            execute,
            should_cancel=lambda: cancelled[0],
        )


def test_a_text_only_reply_records_what_the_model_said(monkeypatch):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content="我先列出子问题，不调用工具。", tool_calls=[]),
            )
        ]
    )
    completions = FakeCompletions([response])
    stop: dict = {}

    evidence = _run(
        monkeypatch,
        completions,
        lambda _name, _args: {"ok": True},
        stop_state=stop,
    )

    assert evidence == []
    assert stop["reason"] == "completed"
    assert stop["final_text"] == "我先列出子问题，不调用工具。"
    assert stop["finish_reason"] == "stop"


def test_an_empty_reply_keeps_its_finish_reason(monkeypatch):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="length",
                message=SimpleNamespace(content="", tool_calls=[]),
            )
        ]
    )
    completions = FakeCompletions([response])
    stop: dict = {}

    evidence = _run(
        monkeypatch,
        completions,
        lambda _name, _args: {"ok": True},
        stop_state=stop,
    )

    assert evidence == []
    assert stop["final_text"] == ""
    assert stop["finish_reason"] == "length"


def test_planner_disables_thinking_when_the_provider_supports_it(monkeypatch):
    completions = FakeCompletions([_message()])

    _run(
        monkeypatch,
        completions,
        lambda _name, _args: {"ok": True},
        provider_profile="deepseek",
    )

    assert completions.requests[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_planner_keeps_the_default_transport_for_other_providers(monkeypatch):
    completions = FakeCompletions([_message()])

    _run(
        monkeypatch,
        completions,
        lambda _name, _args: {"ok": True},
        provider_profile="openai",
    )

    assert "extra_body" not in completions.requests[0]
