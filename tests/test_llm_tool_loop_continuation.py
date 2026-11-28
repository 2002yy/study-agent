from __future__ import annotations

from types import SimpleNamespace

from src.llm_client import run_tool_loop


def _text_only(text: str = "summary") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=text, tool_calls=[]),
            )
        ]
    )


def _tool_call(name: str = "web_search", arguments: str = '{"query":"q"}') -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content="",
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            function=SimpleNamespace(name=name, arguments=arguments),
                        )
                    ],
                ),
            )
        ]
    )


class _Client:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_kwargs):
        self.calls += 1
        return self.responses.pop(0)

    def with_options(self, *, max_retries: int):
        return self

    def __call__(self, **_kwargs):
        return self


def _install(monkeypatch, client: _Client) -> None:
    monkeypatch.setattr("src.llm_client.get_client", lambda **_kwargs: client)
    monkeypatch.setattr(
        "src.llm_client.get_model_name",
        lambda *_args, **_kwargs: "test-model",
    )


def _tools() -> list[dict]:
    return [{"type": "function", "function": {"name": "web_search", "parameters": {}}}]


def test_a_text_only_reply_can_be_continued_without_losing_evidence(monkeypatch) -> None:
    client = _Client([_text_only("I could not find it."), _tool_call(), _text_only("Final")])
    _install(monkeypatch, client)
    executed: list[str] = []
    stop: dict = {}

    def check(evidence, _text, _finish):
        return "Read an unread candidate." if not evidence else None

    result = run_tool_loop(
        [{"role": "user", "content": "research"}],
        tools=_tools(),
        execute_tool=lambda name, _arguments: executed.append(name) or {"ok": True},
        completion_check=check,
        max_model_calls=6,
        stop_state=stop,
        timeout=1.0,
    )

    assert executed == ["web_search"]
    assert result and result[0]["name"] == "web_search"
    assert stop["continuations"] == 1
    assert stop["reason"] == "completed"
    assert stop["completion_gap"] == "Read an unread candidate."


def test_a_continuation_never_consumes_the_reserved_final_call(monkeypatch) -> None:
    client = _Client([_text_only()])
    _install(monkeypatch, client)
    stop: dict = {}

    run_tool_loop(
        [{"role": "user", "content": "research"}],
        tools=_tools(),
        execute_tool=lambda _name, _arguments: {"ok": True},
        completion_check=lambda *_args: "continue",
        max_model_calls=1,
        stop_state=stop,
        timeout=1.0,
    )

    assert client.calls == 1
    assert "continuations" not in stop
    assert stop["reason"] == "completed"


def test_continuations_are_bounded(monkeypatch) -> None:
    client = _Client([_text_only(), _text_only(), _text_only(), _text_only()])
    _install(monkeypatch, client)
    stop: dict = {}

    run_tool_loop(
        [{"role": "user", "content": "research"}],
        tools=_tools(),
        execute_tool=lambda _name, _arguments: {"ok": True},
        completion_check=lambda *_args: "continue",
        max_model_calls=10,
        max_continuations=2,
        stop_state=stop,
        timeout=1.0,
    )

    assert client.calls == 3
    assert stop["continuations"] == 2
    assert stop["reason"] == "completed"


def test_a_broken_completion_check_does_not_end_the_loop(monkeypatch) -> None:
    client = _Client([_text_only()])
    _install(monkeypatch, client)
    stop: dict = {}

    run_tool_loop(
        [{"role": "user", "content": "research"}],
        tools=_tools(),
        execute_tool=lambda _name, _arguments: {"ok": True},
        completion_check=lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")),
        max_model_calls=10,
        stop_state=stop,
        timeout=1.0,
    )

    assert stop["reason"] == "completed"
    assert stop["completion_check_error"] == "RuntimeError: boom"
