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
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        self.requests.append(dict(kwargs))
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


def test_planner_request_uses_a_4096_output_ceiling(monkeypatch) -> None:
    client = _Client([_tool_call(), _text_only()])
    _install(monkeypatch, client)
    run_tool_loop(
        [{"role": "user", "content": "research"}],
        tools=_tools(),
        execute_tool=lambda _name, _arguments: {"ok": True},
        max_model_calls=5,
        timeout=1.0,
    )
    assert client.requests[0]["max_tokens"] == 4096


def test_spend_headroom_stops_before_it_eats_the_answer_reserve(monkeypatch) -> None:
    client = _Client([_tool_call()])
    _install(monkeypatch, client)
    monkeypatch.setattr("src.llm_spend_guard.remaining_budget_cny", lambda: 0.10)
    monkeypatch.setattr(
        "src.llm_spend_guard.reservation_cny", lambda **_kwargs: 0.05
    )
    stop: dict = {}
    result = run_tool_loop(
        [{"role": "user", "content": "research"}],
        tools=_tools(),
        execute_tool=lambda _name, _arguments: {"ok": True},
        max_model_calls=5,
        spend_reserve_cny=0.20,
        stop_state=stop,
        timeout=1.0,
    )
    assert result == []
    assert client.calls == 0
    assert stop["reason"] == "spend_reserve"


def test_turn_ceiling_is_configurable_and_not_six(monkeypatch) -> None:
    from src.application.chat_research_publication import _turn_model_call_ceiling

    monkeypatch.delenv("RESEARCH_TURN_MAX_MODEL_CALLS", raising=False)
    assert _turn_model_call_ceiling() == 64
    monkeypatch.setenv("RESEARCH_TURN_MAX_MODEL_CALLS", "16")
    assert _turn_model_call_ceiling() == 16
    monkeypatch.setenv("RESEARCH_TURN_MAX_MODEL_CALLS", "1")
    assert _turn_model_call_ceiling() == 8


def test_autonomous_budget_leaves_a_wide_answer_window() -> None:
    from src.tools.persistent_web_agent import (
        ANSWER_GENERATION_RESERVE_SECONDS,
        _answer_spend_reserve_cny,
        autonomous_budget,
    )

    normal = autonomous_budget(deep=False)
    deep = autonomous_budget(deep=True)
    assert normal.max_model_calls == 12
    assert deep.max_model_calls == 30
    assert normal.max_seconds == 300
    assert deep.max_seconds == 1800
    assert ANSWER_GENERATION_RESERVE_SECONDS >= 180
    assert _answer_spend_reserve_cny(deep=True) > _answer_spend_reserve_cny(deep=False)


def test_standard_research_read_budget_is_wider() -> None:
    from src.web.research_recovery import STANDARD_BUDGET

    assert STANDARD_BUDGET.hard_seconds == 300
    assert STANDARD_BUDGET.max_reads == 20
    assert STANDARD_BUDGET.max_queries == 12
