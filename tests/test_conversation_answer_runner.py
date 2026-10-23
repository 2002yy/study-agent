"""Bounded answer generation, with no real provider or paid call."""

import asyncio
from dataclasses import replace
import json
import time

import pytest

from src.application.conversation_answer_runner import (
    AnswerLimits,
    answer_request_id,
    generate_conversation_answer,
)
from src.application.conversation_decision_admission import SqliteDecisionAdmission
from src.application.conversation_decision_runner import DecisionBudget
from src.application.conversation_observation_trail import ObservationTrail
from tests.test_conversation_answer_input import build
from tests.test_conversation_observation_trail import root


def value():
    ctx = root()
    return build(ctx, ObservationTrail(ctx))


def ledger():
    return DecisionBudget(4, 400000, 10000)


def run(transport, *, item=None, budget=None, current=None, limits=AnswerLimits()):
    item = item or value()
    return asyncio.run(
        generate_conversation_answer(
            item,
            current_context=current or (lambda: item.context),
            transport=transport,
            budget=budget or ledger(),
            limits=limits,
        )
    )


def test_single_attempt_exact_prompt_accounting_and_separate_namespace():
    item, budget, calls = value(), ledger(), []
    assert budget.reserve(item.context.request_id, 1, 1) == "reserved"

    async def transport(request):
        calls.append(request)
        assert request.messages == item.messages
        assert request.call_id == answer_request_id(item)
        assert request.max_attempts == 1
        assert request.max_output_tokens == 1200
        assert 0 < request.timeout_seconds <= 5
        assert json.loads(request.messages[1][1])["phase"] == "final"
        return "  完整回答\n"

    result = run(transport, item=item, budget=budget)
    assert (result.status, result.answer) == ("completed", "  完整回答\n")
    assert result.attempted and not result.outcome_unknown
    assert budget._prompt_chars == item.prompt_chars + 1
    assert budget._output_tokens == 1201
    assert run(transport, item=item, budget=budget).status == "already_attempted"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_seconds": True},
        {"timeout_seconds": 0},
        {"timeout_seconds": 31},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": float("inf")},
        {"max_output_tokens": False},
        {"max_output_tokens": 4001},
        {"max_response_chars": 8001},
        {"max_response_chars": 0},
    ],
)
def test_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        AnswerLimits(**kwargs)


@pytest.mark.parametrize("raw", ["", " \n ", "x" * 8001, None, {"text": "answer"}])
def test_reject_invalid_output_without_retry(raw):
    calls = []

    async def transport(request):
        calls.append(request)
        return raw

    budget = ledger()
    result = run(transport, budget=budget)
    assert result.status == "invalid_response" and result.answer == ""
    assert result.attempted
    assert run(transport, budget=budget).status == "already_attempted"
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["calls", "chars", "tokens"])
def test_budget_denial_never_invokes_transport(kind):
    budget = DecisionBudget(
        0 if kind == "calls" else 1,
        0 if kind == "chars" else 100000,
        0 if kind == "tokens" else 2000,
    )

    async def transport(request):
        pytest.fail("denied request sent")

    result = run(transport, budget=budget)
    assert result.status == "budget_exhausted" and not result.attempted


@pytest.mark.parametrize("bad", [None, "unknown", {"reserved": True}])
def test_unknown_admission_fails_closed(bad):
    class Bad:
        def reserve(self, *args):
            return bad

    async def transport(request):
        pytest.fail("invalid admission sent")

    assert run(transport, budget=Bad()).status == "admission_unavailable"


def test_admission_exception_and_unavailable_context_are_sanitized():
    class Bad:
        def reserve(self, *args):
            raise RuntimeError("secret details")

    async def transport(request):
        pytest.fail("failed preflight sent")

    def broken():
        raise RuntimeError("secret details")

    for result in (run(transport, budget=Bad()), run(transport, current=broken)):
        assert not result.attempted and "secret details" not in repr(result)


def test_changed_context_before_admission_and_during_reservation_never_sends():
    item = value()
    changed = replace(item.context, user_message="新的用户意图")

    async def transport(request):
        pytest.fail("stale answer sent")

    budget = ledger()
    assert (
        run(transport, item=item, budget=budget, current=lambda: changed).status
        == "stale_context"
    )
    assert not budget._requests
    state = [item.context]

    class Advances:
        def reserve(self, *args):
            result = budget.reserve(*args)
            state[0] = changed
            return result

    result = run(transport, item=item, budget=Advances(), current=lambda: state[0])
    assert result.status == "stale_context" and not result.attempted
    assert answer_request_id(item) in budget._requests


def test_changed_context_after_response_never_exposes_stale_answer():
    item = value()
    state = [item.context]

    async def transport(request):
        state[0] = replace(item.context, evidence_summary="摘要已变化")
        return "旧回答不应返回"

    result = run(transport, item=item, current=lambda: state[0])
    assert result.status == "stale_context" and result.answer == ""
    assert result.attempted


@pytest.mark.parametrize("failure", ["exception", "self_cancel", "timeout"])
def test_provider_failure_is_sanitized_reserved_and_not_retried(failure):
    calls, budget = [], ledger()

    async def transport(request):
        calls.append(request)
        if failure == "self_cancel":
            raise asyncio.CancelledError
        if failure == "timeout":
            raise TimeoutError("secret details")
        raise RuntimeError("secret details")

    result = run(transport, budget=budget)
    assert result.status == ("timeout" if failure == "timeout" else "provider_error")
    assert result.attempted and result.outcome_unknown and not result.answer
    assert "secret details" not in repr(result)
    assert run(transport, budget=budget).status == "already_attempted"
    assert len(calls) == 1


def test_late_transport_cannot_publish_or_hold_the_timeout_open():
    async def scenario():
        release = asyncio.Event()
        completed = asyncio.Event()

        async def transport(request):
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            completed.set()
            return "迟到的回答"

        item, budget = value(), ledger()
        result = await generate_conversation_answer(
            item,
            current_context=lambda: item.context,
            transport=transport,
            budget=budget,
            limits=AnswerLimits(timeout_seconds=0.01),
        )
        assert (
            result.status == "timeout" and result.outcome_unknown and not result.answer
        )
        assert not completed.is_set()
        release.set()
        await asyncio.wait_for(completed.wait(), 1)
        await asyncio.sleep(0)
        assert result.answer == ""

    asyncio.run(scenario())


def test_caller_cancellation_propagates_and_reservation_stays_consumed():
    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()
        item, budget = value(), ledger()

        async def transport(request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            return "unreachable"

        task = asyncio.create_task(
            generate_conversation_answer(
                item,
                current_context=lambda: item.context,
                transport=transport,
                budget=budget,
            )
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(cancelled.wait(), 1)
        result = await generate_conversation_answer(
            item,
            current_context=lambda: item.context,
            transport=transport,
            budget=budget,
        )
        assert result.status == "already_attempted"

    asyncio.run(scenario())


def test_deadline_exhausted_by_reservation_never_sends():
    item, budget = value(), ledger()

    class Slow:
        def reserve(self, *args):
            result = budget.reserve(*args)
            time.sleep(0.02)
            return result

    async def transport(request):
        pytest.fail("expired answer sent")

    result = run(
        transport, item=item, budget=Slow(), limits=AnswerLimits(timeout_seconds=0.005)
    )
    assert (
        result.status == "timeout"
        and not result.attempted
        and not result.outcome_unknown
    )
    assert answer_request_id(item) in budget._requests


def test_blocking_transport_expiry_does_not_publish():
    async def transport(request):
        time.sleep(0.02)
        return "expired"

    result = run(transport, limits=AnswerLimits(timeout_seconds=0.005))
    assert result.status == "timeout" and not result.answer


def test_slow_completion_snapshot_cannot_publish_after_deadline():
    item = value()
    checks = []

    def current():
        checks.append(True)
        if len(checks) == 3:
            time.sleep(0.02)
        return item.context

    async def transport(request):
        return "expired during validation"

    result = run(
        transport,
        item=item,
        current=current,
        limits=AnswerLimits(timeout_seconds=0.005),
    )
    assert result.status == "timeout" and not result.answer
    assert result.attempted and result.outcome_unknown


@pytest.mark.parametrize("change", ["focus", "phase", "evidence"])
def test_sqlite_reopen_blocks_replay_with_changed_mutable_content(tmp_path, change):
    item = value()
    path = tmp_path / "answer-ledger.sqlite"

    def reopen():
        return SqliteDecisionAdmission(
            path, max_calls=4, max_prompt_chars=400000, max_output_tokens=10000
        )

    calls = []

    async def transport(request):
        calls.append(request)
        return "回答"

    assert run(transport, item=item, budget=reopen()).status == "completed"
    if change == "focus":
        item = replace(
            item,
            invocation=replace(
                item.invocation,
                proposal=replace(item.invocation.proposal, focus="另一措辞"),
            ),
        )
    elif change == "phase":
        item = build(item.context, item.trail, "answer_then_research")
    else:
        ctx = replace(item.context, evidence_summary="另一摘要")
        item = build(ctx, ObservationTrail(ctx))
    assert run(transport, item=item, budget=reopen()).status == "already_attempted"
    assert len(calls) == 1
