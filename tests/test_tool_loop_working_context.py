"""Working-context compression keeps recent rounds and shrinks old ones."""

from __future__ import annotations

import json
from types import SimpleNamespace

from src.llm_client import run_tool_loop
from src.llm_context import STATE_NOTE


def _tool_call(call_id: str, url: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(
            name="web_read", arguments=json.dumps({"url": url})
        ),
    )


def _message(calls=()) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=list(calls))
            )
        ]
    )


class FakeCompletions:
    def __init__(self, responses) -> None:
        self.responses = iter(responses)
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return next(self.responses)


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


def _body(label: str, size: int = 5000) -> str:
    return (label * (size // len(label) + 1))[:size]


def _run(monkeypatch, completions, execute, **kwargs):
    _patch_client(monkeypatch, completions)
    kwargs.setdefault("timeout", 5.0)
    return run_tool_loop(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "research"},
        ],
        tools=[{"type": "function", "function": {"name": "web_read"}}],
        execute_tool=execute,
        max_rounds=4,
        **kwargs,
    )


def _tool_messages(request: dict) -> list[dict]:
    return [row for row in request["messages"] if row.get("role") == "tool"]


def test_older_rounds_are_compressed_and_the_recent_one_is_not(monkeypatch):
    completions = FakeCompletions(
        [
            _message([_tool_call("c1", "https://a.example/1"), _tool_call("c2", "https://a.example/2")]),
            _message([_tool_call("c3", "https://b.example/3")]),
            _message(),
        ]
    )

    def execute(_name, arguments):
        return {"ok": True, "url": arguments["url"], "content": _body(arguments["url"])}

    evidence = _run(
        monkeypatch,
        completions,
        execute,
        context_budget=6000,
        context_keep_rounds=1,
    )

    later = _tool_messages(completions.requests[2])
    first_round = later[:2]
    second_round = later[2:]
    assert all('"_compressed": true' in row["content"] for row in first_round)
    assert all('"content_chars": 5000' in row["content"] for row in first_round)
    assert all(len(row["content"]) < 2000 for row in first_round)
    assert "content" in second_round[0]["content"]
    assert [row["tool_call_id"] for row in later] == ["c1", "c2", "c3"]
    # Evidence is untouched: compression only changes what the model re-reads.
    assert [len(row["result"]["content"]) for row in evidence] == [5000, 5000, 5000]


def test_the_original_system_and_user_messages_are_never_rewritten(monkeypatch):
    completions = FakeCompletions(
        [
            _message([_tool_call("c1", "https://a.example/1")]),
            _message([_tool_call("c2", "https://a.example/2")]),
            _message(),
        ]
    )
    _patch_client(monkeypatch, completions)

    def execute(_name, arguments):
        return {"ok": True, "url": arguments["url"], "content": _body("x")}

    run_tool_loop(
        [{"role": "system", "content": "system"}, {"role": "user", "content": "research"}],
        tools=[{"type": "function", "function": {"name": "web_read"}}],
        execute_tool=execute,
        max_rounds=4,
        timeout=5.0,
        context_budget=4000,
        context_keep_rounds=1,
    )

    third = completions.requests[2]["messages"]
    assert third[0] == {"role": "system", "content": "system"}
    assert third[1] == {"role": "user", "content": "research"}


def test_a_large_budget_leaves_the_transcript_untouched(monkeypatch):
    completions = FakeCompletions(
        [
            _message([_tool_call("c1", "https://a.example/1")]),
            _message([_tool_call("c2", "https://a.example/2")]),
            _message(),
        ]
    )

    def execute(_name, arguments):
        return {"ok": True, "url": arguments["url"], "content": _body("y")}

    _run(
        monkeypatch,
        completions,
        execute,
        context_budget=10_000_000,
        context_keep_rounds=1,
    )

    for row in _tool_messages(completions.requests[2]):
        assert '"_compressed"' not in row["content"]


def test_superseded_state_blocks_collapse_to_a_note(monkeypatch):
    completions = FakeCompletions(
        [
            _message([_tool_call("c1", "https://a.example/1")]),
            _message([_tool_call("c2", "https://a.example/2")]),
            _message([_tool_call("c3", "https://a.example/3")]),
            _message(),
        ]
    )

    def execute(_name, arguments):
        return {"ok": True, "url": arguments["url"], "content": _body("z")}

    _run(
        monkeypatch,
        completions,
        execute,
        context_budget=3000,
        context_keep_rounds=1,
        state_provider=lambda _evidence, _round: "研究状态" * 400,
    )

    fourth = completions.requests[3]["messages"]
    states = [
        row
        for row in fourth
        if row.get("role") == "user" and row.get("content") != "research"
    ]
    assert states[0]["content"] == STATE_NOTE
    assert states[-1]["content"].startswith("研究状态")


def test_metadata_only_when_one_pass_is_still_over_budget(monkeypatch):
    completions = FakeCompletions(
        [
            _message(
                [_tool_call(f"c{index}", f"https://a.example/{index}") for index in range(4)]
            ),
            _message([_tool_call("c9", "https://a.example/9")]),
            _message(),
        ]
    )

    def execute(_name, arguments):
        return {"ok": True, "url": arguments["url"], "content": _body("w")}

    _run(
        monkeypatch,
        completions,
        execute,
        context_budget=1200,
        context_keep_rounds=1,
    )

    old = _tool_messages(completions.requests[2])[:4]
    assert all('"excerpt"' not in row["content"] for row in old)
    assert all('"content_chars": 5000' in row["content"] for row in old)
