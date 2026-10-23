"""The model boundary executes, but neither tools nor production routing do."""

import asyncio
from dataclasses import replace
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest
import httpx

from src.application.conversation_decision import ActiveResearch, DecisionContext
from src.application.conversation_decision_runner import (
    DecisionBudget,
    DecisionLimits,
    decide_conversation_action,
)


def context(**changes):
    return replace(DecisionContext("message-1", "解释递归"), **changes)


def response(ctx):
    return json.dumps(
        {
            "schema": "conversation-decision-v1",
            "request_id": ctx.request_id,
            "action": "answer",
            "relation": "new_topic",
            "reason": "已有知识足够",
            "focus": "解释递归",
            "tool": None,
            "target_run_id": None,
            "target_revision": None,
            "active_run_disposition": "keep" if ctx.active_research else "none",
        }
    )


def budget(**changes):
    return DecisionBudget(
        **{
            "max_calls": 2,
            "max_prompt_chars": 100000,
            "max_output_tokens": 1600,
            **changes,
        }
    )


def run(transport, *, ctx=None, ledger=None, latest=None, limits=None):
    ctx = ctx or context()
    return asyncio.run(
        decide_conversation_action(
            ctx,
            transport=transport,
            budget=ledger or budget(),
            current_context=latest or (lambda: ctx),
            limits=limits or DecisionLimits(),
        )
    )


def test_injected_model_receives_bounded_request_and_yields_validated_action():
    calls = []
    ctx = context()

    async def transport(request):
        calls.append(request)
        assert request.call_id == "conversation-decision:message-1"
        assert request.max_attempts == 1
        assert request.max_output_tokens == 800
        assert 0 < request.timeout_seconds <= 5
        assert json.loads(request.messages[1][1])["user_message"] == ctx.user_message
        return response(ctx)

    result = run(transport, ctx=ctx)
    assert result.status == "completed"
    assert result.attempted and not result.outcome_unknown
    assert result.proposal.action == "answer"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "limits",
    [
        {"max_calls": 0},
        {"max_prompt_chars": 1},
        {"max_output_tokens": 799},
    ],
)
def test_admission_rejects_before_transport_for_each_budget_axis(limits):
    async def transport(request):
        pytest.fail("transport must not be invoked")

    result = run(transport, ledger=budget(**limits))
    assert result.status == "budget_exhausted"
    assert not result.attempted


def test_concurrent_requests_cannot_overdraw_shared_admission_budget():
    async def scenario():
        ledger = budget(max_calls=1)
        calls = []

        async def transport(request):
            calls.append(request.call_id)
            await asyncio.sleep(0)
            ctx = context(request_id=request.call_id.split(":", 1)[1])
            return response(ctx)

        async def decide(ctx):
            return await decide_conversation_action(
                ctx, transport=transport, budget=ledger, current_context=lambda: ctx
            )

        results = await asyncio.gather(
            decide(context()), decide(context(request_id="message-2"))
        )
        assert sorted(item.status for item in results) == [
            "budget_exhausted",
            "completed",
        ]
        assert len(calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "```json\n{}\n```",
        "[]",
        "{}",
        "x" * 16001,
        '{"action":"answer","action":"steer"}',
        "[" * 2000 + "]" * 2000,
    ],
)
def test_bad_response_never_retries_or_falls_back_to_research(raw):
    calls = []

    async def transport(request):
        calls.append(request)
        return raw

    result = run(transport)
    assert result.status == "invalid_response"
    assert result.attempted and result.proposal is None
    assert len(calls) == 1


def test_provider_failure_stays_charged_and_does_not_expose_error_content():
    calls = []
    ledger = budget()

    async def transport(request):
        calls.append(request)
        raise RuntimeError("secret provider credential and user prompt")

    result = run(transport, ledger=ledger)
    assert result.status == "provider_error" and result.outcome_unknown
    assert "secret" not in repr(result)
    duplicate = run(transport, ledger=ledger)
    assert duplicate.status == "already_attempted" and not duplicate.attempted
    assert len(calls) == 1


def test_timeout_returns_even_if_transport_suppresses_cancellation_and_late_output_is_ignored():
    async def scenario():
        ledger = budget()
        released = asyncio.Event()
        late_done = asyncio.Event()

        async def transport(request):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await released.wait()
                late_done.set()
                return response(context())

        result = await decide_conversation_action(
            context(),
            transport=transport,
            budget=ledger,
            current_context=context,
            limits=DecisionLimits(timeout_seconds=0.02),
        )
        assert result.status == "timeout" and result.outcome_unknown
        assert result.proposal is None and not late_done.is_set()
        duplicate = await decide_conversation_action(
            context(), transport=transport, budget=ledger, current_context=context
        )
        assert duplicate.status == "already_attempted"
        released.set()
        await asyncio.wait_for(late_done.wait(), timeout=1)
        assert result.proposal is None

    asyncio.run(scenario())


def test_blocking_transport_cannot_publish_a_response_after_deadline():
    async def transport(request):
        time.sleep(0.03)
        return response(context())

    assert (
        run(transport, limits=DecisionLimits(timeout_seconds=0.01)).status == "timeout"
    )


def test_context_read_consuming_deadline_does_not_submit_or_reserve_model_call():
    ledger = budget()

    def slow_context():
        time.sleep(0.03)
        return context()

    async def transport(request):
        pytest.fail("deadline was exhausted before model admission")

    result = run(
        transport,
        ledger=ledger,
        latest=slow_context,
        limits=DecisionLimits(timeout_seconds=0.01),
    )
    assert result.status == "timeout" and not result.attempted
    assert not result.outcome_unknown

    async def valid_transport(request):
        return response(context())

    assert run(valid_transport, ledger=ledger).status == "completed"


def test_event_loop_delay_after_reservation_cannot_start_expired_transport():
    def delayed_context():
        asyncio.get_running_loop().call_soon(time.sleep, 0.03)
        return context()

    async def transport(request):
        pytest.fail("expired transport must not start")

    result = run(
        transport,
        latest=delayed_context,
        limits=DecisionLimits(timeout_seconds=0.01),
    )
    assert result.status == "timeout" and result.proposal is None


def test_external_cancellation_propagates_without_refunding_or_resubmitting():
    async def scenario():
        ledger = budget()
        started = asyncio.Event()
        calls = []

        async def transport(request):
            calls.append(request)
            started.set()
            await asyncio.Event().wait()

        pending = asyncio.create_task(
            decide_conversation_action(
                context(), transport=transport, budget=ledger, current_context=context
            )
        )
        await started.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        result = await decide_conversation_action(
            context(), transport=transport, budget=ledger, current_context=context
        )
        assert result.status == "already_attempted" and len(calls) == 1

    asyncio.run(scenario())


def test_transport_self_cancellation_is_controlled_and_does_not_cancel_caller():
    async def scenario():
        ledger = budget()
        calls = []

        async def transport(request):
            calls.append(request)
            raise asyncio.CancelledError

        result = await decide_conversation_action(
            context(), transport=transport, budget=ledger, current_context=context
        )
        assert result.status == "provider_error" and result.outcome_unknown
        assert result.proposal is None and asyncio.current_task().cancelling() == 0
        duplicate = await decide_conversation_action(
            context(), transport=transport, budget=ledger, current_context=context
        )
        assert duplicate.status == "already_attempted" and len(calls) == 1

    asyncio.run(scenario())


def test_changed_context_before_admission_makes_no_call():
    async def transport(request):
        pytest.fail("stale input must not be submitted")

    result = run(transport, latest=lambda: context(user_message="换题"))
    assert result.status == "stale_context" and not result.attempted


def test_changed_research_during_model_call_cannot_produce_action():
    original = context(active_research=ActiveResearch("run-1", 1, "旧问题", True))
    latest = [original]

    async def transport(request):
        latest[0] = replace(
            original, active_research=ActiveResearch("run-1", 2, "新问题", True)
        )
        return response(original)

    result = run(transport, ctx=original, latest=lambda: latest[0])
    assert result.status == "stale_context" and result.attempted
    assert result.proposal is None


@pytest.mark.parametrize("when", ["before", "after"])
def test_context_read_failure_is_explicit_and_never_publishes_a_proposal(when):
    state = [when == "before"]

    def latest():
        if state[0]:
            raise RuntimeError("private context detail")
        return context()

    async def transport(request):
        state[0] = True
        return response(context())

    result = run(transport, latest=latest)
    assert result.status == "context_unavailable"
    assert result.attempted == (when == "after")
    assert result.proposal is None
    assert "private" not in repr(result)


def test_real_loopback_http_transport_runs_through_same_controlled_boundary():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            data = response(context()).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def transport(request):
        async with httpx.AsyncClient(
            trust_env=False, timeout=request.timeout_seconds
        ) as client:
            reply = await client.post(
                f"http://127.0.0.1:{server.server_port}/decision",
                json={
                    "messages": list(request.messages),
                    "max_tokens": request.max_output_tokens,
                },
            )
            reply.raise_for_status()
            return reply.text

    try:
        result = run(transport)
        assert result.status == "completed"
        assert len(received) == 1 and received[0]["max_tokens"] == 800
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "changes",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": True},
        {"max_output_tokens": 2001},
        {"max_response_chars": True},
    ],
)
def test_invalid_limits_fail_before_model_call(changes):
    with pytest.raises(ValueError):
        DecisionLimits(**changes)
