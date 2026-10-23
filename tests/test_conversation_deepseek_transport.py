"""Offline DeepSeek wire contract; no environment or live provider access."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from src.application.conversation_answer_runner import ModelAnswerRequest
from src.application.conversation_decision_runner import ModelDecisionRequest
from src.application.conversation_deepseek_transport import (
    DeepSeekConversationTransport,
)


class Client:
    max_retries = 0

    def __init__(self, response=None, failure=None):
        self.options, self.calls = [], []
        self.response, self.failure = response or reply(), failure
        self.chat = NS(completions=NS(create=self.create))

    def with_options(self, **options):
        self.options.append(options)
        return self

    async def create(self, **options):
        self.calls.append(options)
        if self.failure:
            raise self.failure
        return self.response


def reply(**changes):
    message = NS(content="回答", refusal=None, tool_calls=None)
    choice = NS(message=message, finish_reason="stop")
    for name, value in changes.items():
        setattr(choice if name == "finish_reason" else message, name, value)
    return NS(choices=[choice])


def request(kind=ModelAnswerRequest):
    return kind("call-1", (("system", "规则"), ("user", "问题")), 1, 800)


@pytest.mark.parametrize("kind", [ModelAnswerRequest, ModelDecisionRequest])
def test_exact_single_attempt_wire_contract(kind):
    client = Client()
    transport = DeepSeekConversationTransport(client, "configured-deepseek-model")
    assert asyncio.run(transport(request(kind))) == "回答"
    assert client.options == [{"max_retries": 0, "timeout": 1}]
    wire = client.calls[0]
    assert wire["model"] == "configured-deepseek-model"
    assert wire["messages"] == [
        {"role": "system", "content": "规则"},
        {"role": "user", "content": "问题"},
    ]
    assert wire["max_tokens"] == 800 and wire["timeout"] == 1
    assert wire["stream"] is False
    assert wire["extra_body"] == {"thinking": {"type": "disabled"}}
    assert (wire.get("response_format") == {"type": "json_object"}) is (
        kind is ModelDecisionRequest
    )
    assert not {"tools", "tool_choice", "metadata", "user"} & wire.keys()


@pytest.mark.parametrize(
    "change",
    [
        {"max_attempts": 2},
        {"max_attempts": True},
        {"max_output_tokens": True},
        {"max_output_tokens": 4001},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": 31},
        {"timeout_seconds": True},
        {"call_id": ""},
        {"messages": ()},
        {"messages": (("tool", "untrusted"),)},
        {"messages": (("user", "x" * 128001),)},
        {"messages": (("user", ""),)},
    ],
)
def test_invalid_requests_never_touch_sdk(change):
    client = Client()
    with pytest.raises(ValueError):
        asyncio.run(
            DeepSeekConversationTransport(client, "model")(replace(request(), **change))
        )
    assert not client.options and not client.calls


@pytest.mark.parametrize(
    "change",
    [
        {"finish_reason": "length"},
        {"finish_reason": "tool_calls"},
        {"content": None},
        {"content": "x" * 8001},
        {"content": " "},
        {"refusal": "refused"},
        {"tool_calls": ["unexpected"]},
    ],
)
def test_incomplete_or_unexpected_response_is_rejected_without_retry(change):
    client = Client(reply(**change))
    with pytest.raises(ValueError):
        asyncio.run(DeepSeekConversationTransport(client, "model")(request()))
    assert len(client.calls) == 1


def test_nonconforming_client_cannot_restore_hidden_retries():
    client = Client()
    client.max_retries = 2
    with pytest.raises(ValueError, match="hidden retries"):
        asyncio.run(DeepSeekConversationTransport(client, "model")(request()))
    assert not client.calls


def test_cancellation_propagates_without_provider_retry():
    client = Client(failure=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(DeepSeekConversationTransport(client, "model")(request()))
    assert len(client.calls) == 1


def test_transport_errors_propagate_to_existing_sanitizing_runner():
    client = Client(failure=RuntimeError("provider detail"))
    with pytest.raises(RuntimeError):
        asyncio.run(DeepSeekConversationTransport(client, "model")(request()))
    assert len(client.calls) == 1
