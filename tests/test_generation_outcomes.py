import asyncio
from types import SimpleNamespace as NS

import httpx
import pytest
from openai import APITimeoutError

from src import llm_client
from src.application.generation_outcome import (
    error_outcome,
    finish_outcome,
    record_finish,
)


@pytest.mark.parametrize("transport", ["chat", "stream_chat", "async_stream_chat"])
@pytest.mark.parametrize("reason", ["stop", "length", "content_filter", None])
def test_provider_end_reason_survives_all_transports(monkeypatch, transport, reason):
    closed = []
    observed = []

    class Response:
        def __iter__(self):
            yield NS(choices=[NS(delta=NS(content="partial"), finish_reason=None)])
            yield NS(choices=[NS(delta=NS(content=None), finish_reason=reason)])
            yield NS(choices=[])  # optional usage-only final chunk

        async def __aiter__(self):
            for chunk in self:
                yield chunk

        def close(self):
            closed.append(True)

    def create(**kwargs):
        assert "on_completion" not in kwargs  # internal callback is never sent to API
        if kwargs.get("stream"):
            return Response()
        return NS(choices=[NS(message=NS(content="partial"), finish_reason=reason)])

    async def async_create(**kwargs):
        return create(**kwargs)

    monkeypatch.setattr(
        llm_client,
        "get_client",
        lambda **kw: NS(chat=NS(completions=NS(create=create))),
    )
    monkeypatch.setattr(
        llm_client,
        "get_async_client",
        lambda **kw: NS(chat=NS(completions=NS(create=async_create))),
    )
    monkeypatch.setattr(
        llm_client, "_build_request_kwargs", lambda **kw: {"stream": kw["stream"]}
    )
    args = ([{"role": "user", "content": "test"}],)
    if transport == "async_stream_chat":

        async def collect():
            return "".join(
                [
                    s
                    async for s in llm_client.async_stream_chat(
                        *args, on_completion=observed.append
                    )
                ]
            )

        result = asyncio.run(collect())
    else:
        result = getattr(llm_client, transport)(*args, on_completion=observed.append)
        if transport == "stream_chat":
            result = "".join(result)
    assert result == "partial"
    assert observed == [reason]
    if transport != "chat":
        assert closed == [True]


def test_timeout_classification_follows_exception_cause_not_message():
    wrapped = RuntimeError("transport error")
    wrapped.__cause__ = APITimeoutError(
        request=httpx.Request("POST", "https://example.invalid")
    )
    assert error_outcome(wrapped)["status"] == "timeout"
    assert (
        error_outcome(RuntimeError("timeout mentioned in unrelated error"))["status"]
        == "error"
    )
    assert finish_outcome(None)["status"] == "unknown"


def test_late_provider_completion_cannot_overwrite_a_timeout():
    route = {"generation": error_outcome(TimeoutError())}
    record_finish(route, "stop")
    assert route["generation"]["status"] == "timeout"
