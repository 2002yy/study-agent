"""Real SDK over in-memory fake HTTP; all credentials/configuration are fake."""

import asyncio
import json

import httpx
from openai import AsyncOpenAI
import pytest

from src.application.conversation_answer_runner import (
    AnswerLimits,
    generate_conversation_answer,
)
from src.application.conversation_decision_runner import DecisionBudget
from src.application.conversation_deepseek_session import (
    DeepSeekConversationSession,
    DeepSeekConversationSettings,
)
from tests.test_conversation_answer_runner import value
from tests.test_conversation_bounded_loop import collect, scenario
from tests.test_conversation_deepseek_transport import Client, request


def settings():
    return DeepSeekConversationSettings(
        "fake-deepseek-test-credential", "configured-deepseek-model"
    )


def response(text):
    return {
        "id": "fake-response",
        "object": "chat.completion",
        "created": 1,
        "model": "configured-deepseek-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": text},
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def factory(handler, clients, arguments):
    def build(**kwargs):
        arguments.append(kwargs)
        client = AsyncOpenAI(
            **kwargs,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        clients.append(client)
        return client

    return build


def test_configuration_is_deepseek_only_with_no_openai_fallback():
    foreign = {
        "OPENAI_API_KEY": "foreign-fake",
        "OPENAI_BASE_URL": "https://api.openai.com/v1",
        "MODEL_FLASH_NAME": "foreign-model",
    }
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        DeepSeekConversationSettings.from_environment(foreign)
    foreign["DEEPSEEK_API_KEY"] = "deepseek-fake"
    with pytest.raises(ValueError, match="DEEPSEEK_MODEL_FLASH_NAME"):
        DeepSeekConversationSettings.from_environment(foreign)
    foreign.update(
        DEEPSEEK_MODEL_FLASH_NAME="flash-model", DEEPSEEK_MODEL_PRO_NAME="pro-model"
    )
    parsed = DeepSeekConversationSettings.from_environment(foreign)
    assert parsed.base_url == "https://api.deepseek.com/v1"
    assert parsed.model == "flash-model"
    assert (
        DeepSeekConversationSettings.from_environment(
            foreign, model_profile="pro"
        ).model
        == "pro-model"
    )
    assert "deepseek-fake" not in repr(parsed)


@pytest.mark.parametrize(
    "base",
    [
        "https://api.deepseek.com/",
        "https://api.deepseek.com//",
        "https://api.deepseek.com/v1/",
        "https://api.deepseek.com/v1//",
    ],
)
def test_accepted_base_url_is_canonical_before_sdk_receives_it(base):
    parsed = DeepSeekConversationSettings("fake", "model", base)
    assert parsed.base_url == base.rstrip("/")


@pytest.mark.parametrize(
    "base",
    [
        "https://api.openai.com/v1",
        "http://api.deepseek.com/v1",
        "https://api.deepseek.com.evil/v1",
        "https://api.deepseek.com@elsewhere/v1",
        "https://api.deepseek.com/v1?key=x",
        "http://127.0.0.1/v1",
    ],
)
def test_other_endpoints_cannot_be_selected(base):
    with pytest.raises(ValueError):
        DeepSeekConversationSettings("fake", "model", base)


@pytest.mark.parametrize(
    "base", ["https://api.deepseek.com/v1", "https://api.deepseek.com/v1//"]
)
def test_sdk_serializes_bounded_request_and_owned_client_closes(monkeypatch, base):
    monkeypatch.setenv("OPENAI_ORG_ID", "foreign-test-org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "foreign-test-project")

    async def run():
        wires, clients, arguments = [], [], []

        def http(req):
            wires.append(req)
            return httpx.Response(200, json=response("SDK回答"))

        session = DeepSeekConversationSession(
            DeepSeekConversationSettings(settings().api_key, settings().model, base),
            client_factory=factory(http, clients, arguments),
        )
        with pytest.raises(RuntimeError):
            _ = session.transport
        async with session:
            transport = session.transport
            assert await transport(request()) == "SDK回答"
            assert arguments[0]["max_retries"] == 0
            assert arguments[0]["api_key"] == settings().api_key
            assert str(wires[0].url) == "https://api.deepseek.com/v1/chat/completions"
            data = json.loads(wires[0].content)
            assert data["thinking"] == {"type": "disabled"}
            assert data["max_tokens"] == 800 and data["stream"] is False
            assert "response_format" not in data
            # The SDK emits empty headers for explicit empty values. Neither
            # foreign environment value may be inherited into the request.
            assert wires[0].headers.get("OpenAI-Organization", "") == ""
            assert wires[0].headers.get("OpenAI-Project", "") == ""
        assert clients[0].is_closed()
        with pytest.raises(RuntimeError):
            await transport(request())
        with pytest.raises(RuntimeError):
            await session.__aenter__()
        await session.aclose()
        assert len(wires) == 1

    asyncio.run(run())


def test_default_owned_http_client_disables_redirects_and_ambient_proxies(monkeypatch):
    async def run():
        arguments = []

        class Fake(Client):
            async def close(self):
                pass

        def construct(**kwargs):
            arguments.append(kwargs)
            return Fake()

        monkeypatch.setattr("openai.AsyncOpenAI", construct)
        async with DeepSeekConversationSession(settings()):
            owned = arguments[0]["http_client"]
            assert owned.follow_redirects is False
            assert owned.trust_env is False
            assert arguments[0]["organization"] == arguments[0]["project"] == ""
        assert owned.is_closed

    asyncio.run(run())


def test_sdk_does_not_follow_redirect_to_another_provider():
    async def run():
        wires, clients, arguments = [], [], []

        def http(req):
            wires.append(req)
            return httpx.Response(
                307, headers={"location": "https://api.openai.com/v1/chat/completions"}
            )

        async with DeepSeekConversationSession(
            settings(), client_factory=factory(http, clients, arguments)
        ) as session:
            item = value()
            result = await generate_conversation_answer(
                item,
                current_context=lambda: item.context,
                transport=session.transport,
                budget=DecisionBudget(1, 400000, 5000),
            )
            assert result.status == "provider_error"
        assert len(wires) == 1 and wires[0].url.host == "api.deepseek.com"

    asyncio.run(run())


def test_full_loop_with_real_sdk_keeps_json_decision_and_text_answer_separate():
    async def run():
        wires, clients, arguments = [], [], []

        def http(req):
            data = json.loads(req.content)
            wires.append(data)
            if data.get("response_format"):
                payload = json.loads(data["messages"][1]["content"])
                text = json.dumps(
                    {
                        "schema": "conversation-decision-v1",
                        "request_id": payload["request_id"],
                        "action": "answer",
                        "relation": "new_topic",
                        "reason": "已有依据",
                        "focus": "回答",
                        "tool": None,
                        "target_run_id": None,
                        "target_revision": None,
                        "active_run_disposition": "none",
                    }
                )
            else:
                text = "整合回答"
            return httpx.Response(200, json=response(text))

        async with DeepSeekConversationSession(
            settings(), client_factory=factory(http, clients, arguments)
        ) as session:
            shared = DecisionBudget(4, 400000, 10000)
            # scenario injects its model seam; use the actual SDK transport there.
            _, _, calls, stream = scenario(
                ("answer",),
                model=session.transport,
                decision_budget=shared,
                answer_generator=session.answer_generator(shared),
            )
            events = await collect(stream)
            assert events[-1].reason == "answered"
            assert events[-2].observation == "整合回答"
            assert calls == ["model"] and len(wires) == 2
            assert wires[0]["response_format"] == {"type": "json_object"}
            assert "response_format" not in wires[1]
            assert len(shared._requests) == 2
        assert clients[0].is_closed()

    asyncio.run(run())


def test_sdk_503_is_attempted_once_despite_default_sdk_retry_policy():
    async def run():
        wires, clients, arguments = [], [], []

        def http(req):
            wires.append(req)
            return httpx.Response(
                503, json={"error": {"message": "private-test-detail"}}
            )

        item, ledger = value(), DecisionBudget(2, 400000, 5000)
        async with DeepSeekConversationSession(
            settings(), client_factory=factory(http, clients, arguments)
        ) as session:
            result = await generate_conversation_answer(
                item,
                current_context=lambda: item.context,
                transport=session.transport,
                budget=ledger,
            )
            assert result.status == "provider_error" and result.outcome_unknown
            assert "private-test-detail" not in repr(result)
            again = await generate_conversation_answer(
                item,
                current_context=lambda: item.context,
                transport=session.transport,
                budget=ledger,
            )
            assert again.status == "already_attempted"
        assert len(wires) == 1

    asyncio.run(run())


def test_sdk_http_wait_cancels_at_runner_deadline():
    async def run():
        entered, cancelled = asyncio.Event(), asyncio.Event()
        clients, arguments = [], []

        async def http(req):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            return httpx.Response(200, json=response("unreachable"))

        item = value()
        async with DeepSeekConversationSession(
            settings(), client_factory=factory(http, clients, arguments)
        ) as session:
            result = await generate_conversation_answer(
                item,
                current_context=lambda: item.context,
                transport=session.transport,
                budget=DecisionBudget(1, 400000, 5000),
                limits=AnswerLimits(timeout_seconds=0.05),
            )
            assert entered.is_set()
            assert result.status == "timeout" and not result.answer
            await asyncio.wait_for(cancelled.wait(), 1)
        assert clients[0].is_closed()

    asyncio.run(run())


def test_invalid_client_is_closed_on_entry_failure():
    async def run():
        closed = []

        class Invalid:
            async def close(self):
                closed.append(True)

        session = DeepSeekConversationSession(
            settings(), client_factory=lambda **kw: Invalid()
        )
        with pytest.raises(ValueError):
            await session.__aenter__()
        assert closed == [True]

    asyncio.run(run())


def test_closing_owned_session_does_not_close_unrelated_client():
    async def run():
        client, shared = Client(), Client()
        closed = []

        async def close():
            closed.append(True)

        client.close = close
        async with DeepSeekConversationSession(
            settings(), client_factory=lambda **kw: client
        ):
            pass
        assert closed == [True] and not shared.options and not shared.calls

    asyncio.run(run())
