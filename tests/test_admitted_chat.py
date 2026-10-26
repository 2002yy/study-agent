"""CL-M3-S2-B1-2b: chat-shaped admission, including the streaming boundary.

The transport below is fake; everything else is real: the two SQLite stores, the
logical quota, the cost reservation, the single-use authorization and the
settlement observation. Each test asserts the same contract from a different
angle - one send, one reservation, one observation - and the streaming tests
also assert the part a non-streaming test cannot see: a stream that is closed
early is `unresolved`, not quietly settled.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.application.admitted_chat import (
    admitted_async_stream_chat,
    admitted_chat,
    admitted_stream_chat,
)
from src.application.spend_admission_factory import (
    ASSEMBLY_FLAG,
    build_settlement_admission,
)
from src.llm_spend_guard import reset_spend, reserve_call, spend_identity
from src.infrastructure.sqlite.database import RuntimeDatabase

EXPERIMENT = "chat-chain"
MODEL = "deepseek-chat"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reset_spend()
    for name in (
        ASSEMBLY_FLAG,
        "LLM_SPEND_CAP_CNY",
        "LLM_SPEND_INPUT_CNY_PER_MTOK",
        "LLM_SPEND_OUTPUT_CNY_PER_MTOK",
        "LLM_SPEND_DEFAULT_MAX_TOKENS",
        "LLM_SPEND_EXPERIMENT_ID",
        "LLM_SPEND_EXPERIMENT_CAP_CNY",
        "LLM_SPEND_LEDGER_DB",
        "LLM_EXPERIMENT_ALLOWED_MODELS",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    reset_spend()


def _chain(monkeypatch, tmp_path: Path):
    database = tmp_path / "runtime.sqlite"
    RuntimeDatabase(database).initialize()
    monkeypatch.setenv(ASSEMBLY_FLAG, "1")
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(database.resolve()))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", EXPERIMENT)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "10")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")
    admission = build_settlement_admission(
        model=MODEL, kind="chat", scope_id="turn-1"
    )
    assert admission is not None
    return admission


def _rows(admission) -> int:
    return admission.settlements._connect().execute(
        "SELECT COUNT(*) FROM llm_spend_reservations"
    ).fetchone()[0]


def _transport_call(task_name: str) -> None:
    reserve_call(
        prompt_chars=10,
        max_tokens=100,
        purpose="chat",
        model=MODEL,
        request_key=task_name,
    )


def test_a_non_streaming_chat_call_closes_its_own_loop(monkeypatch, tmp_path):
    admission = _chain(monkeypatch, tmp_path)
    seen: list[str] = []

    def base_chat(messages, *, task_name=None, timeout=None, **kwargs):
        _transport_call(task_name)
        seen.append(task_name)
        return "hello"

    call = admitted_chat(base_chat, admission, scope="turn-1")
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        assert call([{"role": "user", "content": "hi"}], task_name="chat") == "hello"

    assert seen == ["turn-1#r1#chat"]
    assert _rows(admission) == 1
    record = admission.settlements.current(EXPERIMENT, "turn-1#r1#chat")
    assert record is not None and record.settled is True


def test_an_empty_message_list_is_not_admitted_and_not_reserved(monkeypatch, tmp_path):
    admission = _chain(monkeypatch, tmp_path)

    def base_chat(messages, **_kwargs):
        return ""

    call = admitted_chat(base_chat, admission, scope="turn-1")
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        assert call([]) == ""

    assert _rows(admission) == 0
    assert admission.logical.usage().calls == 0


def test_a_consumed_stream_is_settled(monkeypatch, tmp_path):
    admission = _chain(monkeypatch, tmp_path)

    def base_stream(messages, *, task_name=None, timeout=None, **kwargs):
        _transport_call(task_name)
        yield from ("a", "b", "c")

    call = admitted_stream_chat(base_stream, admission, scope="turn-1")
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        assert list(call([{"role": "user", "content": "hi"}], task_name="chat")) == [
            "a",
            "b",
            "c",
        ]

    record = admission.settlements.current(EXPERIMENT, "turn-1#r1#chat")
    assert record is not None and record.settled is True
    assert _rows(admission) == 1


def test_a_stream_closed_early_stays_unresolved(monkeypatch, tmp_path):
    admission = _chain(monkeypatch, tmp_path)

    def base_stream(messages, *, task_name=None, timeout=None, **kwargs):
        _transport_call(task_name)
        yield "a"
        yield "b"

    call = admitted_stream_chat(base_stream, admission, scope="turn-1")
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        stream = call([{"role": "user", "content": "hi"}], task_name="chat")
        assert next(stream) == "a"
        stream.close()

    record = admission.settlements.current(EXPERIMENT, "turn-1#r1#chat")
    assert record is not None
    assert record.outcome == "unresolved"
    assert record.cost_micros is None
    # The money is still reserved; unknown is not a refund.
    assert _rows(admission) == 1


def test_an_async_stream_is_settled(monkeypatch, tmp_path):
    admission = _chain(monkeypatch, tmp_path)

    async def base_stream(messages, *, task_name=None, timeout=None, **kwargs):
        _transport_call(task_name)
        for token in ("a", "b"):
            yield token

    call = admitted_async_stream_chat(base_stream, admission, scope="turn-1")

    async def consume():
        collected = []
        with spend_identity(
            run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
        ):
            async for token in call([{"role": "user", "content": "hi"}], task_name="chat"):
                collected.append(token)
        return collected

    assert asyncio.run(consume()) == ["a", "b"]
    record = admission.settlements.current(EXPERIMENT, "turn-1#r1#chat")
    assert record is not None and record.settled is True


def test_the_send_identity_is_round_scoped_even_for_a_bare_stage(monkeypatch, tmp_path):
    admission = _chain(monkeypatch, tmp_path)
    seen: list[str] = []

    def base_chat(messages, *, task_name=None, timeout=None, **kwargs):
        _transport_call(task_name)
        seen.append(task_name)
        return "ok"

    call = admitted_chat(base_chat, admission, scope="turn-1")
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        call([{"role": "user", "content": "hi"}], task_name="op-1#r9#answer")

    assert seen == ["op-1#r9#answer"]


def test_chat_service_routes_a_turn_through_the_chain(monkeypatch, tmp_path):
    """The wiring, not just the wrapper: ChatService builds the per-turn chain."""

    from types import SimpleNamespace

    from src.application.chat_service import ChatDependencies, ChatService
    from src.llm_client import get_model_name

    database = tmp_path / "runtime.sqlite"
    RuntimeDatabase(database).initialize()
    monkeypatch.setenv(ASSEMBLY_FLAG, "1")
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(database.resolve()))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", EXPERIMENT)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "10")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("OPENAI_MODEL_FLASH_NAME", "deepseek-chat")
    monkeypatch.setenv("OPENAI_MODEL_PRO_NAME", "deepseek-reasoner")

    seen: list[str] = []

    def base_chat(messages, *, task_name=None, timeout=None, **kwargs):
        reserve_call(
            prompt_chars=10,
            max_tokens=100,
            purpose="answer",
            model=get_model_name("flash"),
            request_key=task_name,
        )
        seen.append(task_name)
        return "ok"

    service = ChatService(
        repository=object(),  # not touched by the scoped call
        dependencies=ChatDependencies(chat=base_chat),
    )
    prepared = SimpleNamespace(
        turn=SimpleNamespace(id="turn-9", operation_id="op-9"),
        route={"model_profile": "flash"},
    )

    with spend_identity(
        run_id="turn-9", operation_id="op-9", invocation="1", experiment=EXPERIMENT
    ):
        assert service._chat_within_scope(prepared)(
            [{"role": "user", "content": "hi"}], task_name="chat"
        ) == "ok"

    assert seen == ["turn-9#r1#chat"]
    from src.infrastructure.sqlite.spend_ledger import SpendLedger

    assert SpendLedger(database).experiment_spend(EXPERIMENT)["calls"] == 1


def test_a_research_session_uses_the_operation_quota(monkeypatch, tmp_path):
    """Research: one operation, its own quota file, round-scoped stage names."""

    import json
    import time

    from src.application.admitted_chat import admitted_completion_for
    from src.web.semantic_recovery import ResearchSemanticSession

    database = tmp_path / "runtime.sqlite"
    RuntimeDatabase(database).initialize()
    monkeypatch.setenv(ASSEMBLY_FLAG, "1")
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(database.resolve()))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", EXPERIMENT)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "10")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")
    admission = build_settlement_admission(
        model=MODEL, kind="research", scope_id="op-1"
    )
    assert admission is not None
    assert _rows(admission) == 0

    def base_completion(*, messages, timeout, task_name, **kwargs):
        reserve_call(
            prompt_chars=10,
            max_tokens=100,
            purpose="research",
            model=MODEL,
            request_key=task_name,
        )
        return json.dumps({"intent": "ANSWER"})

    admitted = admitted_completion_for(
        base_completion, admission, estimate_output_tokens=100
    )
    session = ResearchSemanticSession(
        admitted,
        deadline=time.monotonic() + 5.0,
        should_cancel=lambda: False,
        task_identity=lambda stage: f"op-1#r1#{stage}",
    )
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        assert session.request("research_turn_interpretation", "x", {}) == {
            "intent": "ANSWER"
        }

    assert _rows(admission) == 1
    record = admission.settlements.current(
        EXPERIMENT, "op-1#r1#research_turn_interpretation"
    )
    assert record is not None and record.settled is True
    assert admission.logical.usage().calls == 1


def test_a_stream_reservation_covers_the_transport_request(monkeypatch, tmp_path):
    """S2-C0: the bound is the transport's, not just the message bodies."""

    from src.llm_spend_guard import serialized_request_chars

    admission = _chain(monkeypatch, tmp_path)

    def base_stream(messages, *, task_name=None, timeout=None, **kwargs):
        transport_chars = serialized_request_chars(
            [
                {
                    "model": MODEL,
                    "messages": messages,
                    "temperature": 0.7,
                    "stream": True,
                    "timeout": 30.0,
                    "max_tokens": kwargs.get("max_tokens"),
                    "response_format": {"type": "text"},
                    "extra_body": {"trace": "x" * 500},
                }
            ]
        )
        reserve_call(
            prompt_chars=transport_chars,
            max_tokens=kwargs.get("max_tokens") or 100,
            model=MODEL,
            request_key=task_name,
        )
        yield "a"

    call = admitted_stream_chat(base_stream, admission, scope="turn-1")
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        assert list(
            call(
                [{"role": "user", "content": "hi"}],
                task_name="chat",
                max_tokens=100,
            )
        ) == ["a"]

    record = admission.settlements.current(EXPERIMENT, "turn-1#r1#chat")
    assert record is not None and record.settled is True


def test_a_stream_beyond_the_reserved_bound_is_still_refused(monkeypatch, tmp_path):
    """The fix widens the bound to the transport's unit, not past the check."""

    from src.llm_spend_guard import (
        SpendAuthorizationError,
        serialized_request_chars,
    )

    admission = _chain(monkeypatch, tmp_path)

    def base_stream(messages, *, task_name=None, timeout=None, **kwargs):
        transport_chars = serialized_request_chars(
            [{"model": MODEL, "messages": messages, "extra_body": {"x": "y" * 200_000}}]
        )
        reserve_call(
            prompt_chars=transport_chars,
            max_tokens=100,
            model=MODEL,
            request_key=task_name,
        )
        yield "a"

    call = admitted_stream_chat(base_stream, admission, scope="turn-1")
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        with pytest.raises(SpendAuthorizationError) as refused:
            list(call([{"role": "user", "content": "hi"}], task_name="chat"))
    assert refused.value.reason == "send_authorization_bound_exceeded"
    # One reservation exists (the send was admitted), but nothing was settled as
    # complete; the unknown outcome is recorded as unresolved.
    assert _rows(admission) == 1
    record = admission.settlements.current(EXPERIMENT, "turn-1#r1#chat")
    assert record is not None and record.outcome == "unresolved"


def test_chat_service_keeps_the_old_path_when_the_flag_is_off(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from src.application.chat_service import ChatDependencies, ChatService

    database = tmp_path / "runtime.sqlite"
    RuntimeDatabase(database).initialize()
    monkeypatch.setenv(ASSEMBLY_FLAG, "0")
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(database.resolve()))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", EXPERIMENT)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "10")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")

    seen: list[str] = []

    def base_chat(messages, *, task_name=None, timeout=None, **kwargs):
        seen.append(task_name)
        return "plain"

    service = ChatService(
        repository=object(), dependencies=ChatDependencies(chat=base_chat)
    )
    prepared = SimpleNamespace(
        turn=SimpleNamespace(id="turn-9", operation_id="op-9"),
        route={"model_profile": "flash"},
    )
    with spend_identity(
        run_id="turn-9", operation_id="op-9", invocation="1", experiment=EXPERIMENT
    ):
        assert service._chat_within_scope(prepared)(
            [{"role": "user", "content": "hi"}], task_name="chat"
        ) == "plain"

    assert seen == ["chat"]
