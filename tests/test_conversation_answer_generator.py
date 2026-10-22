"""Native bounded generation inside the opt-in loop, using offline transports."""

import asyncio
from dataclasses import replace
import json

import pytest

from src.application.conversation_answer_generator import (
    AnswerGenerationError,
    BoundedAnswerGenerator,
)
from src.application.conversation_answer_runner import AnswerLimits
from src.application.conversation_bounded_loop import LoopLimits
from src.application.conversation_decision_admission import SqliteDecisionAdmission
from src.application.conversation_decision_runner import DecisionBudget
from tests.test_conversation_answer_runner import value
from tests.test_conversation_bounded_loop import collect, scenario


def budget():
    return DecisionBudget(8, 1000000, 20000)


def test_native_generator_gets_all_observations_and_projected_fresh_identity():
    async def run():
        requests, shared = [], budget()

        async def transport(request):
            requests.append(request)
            data = json.loads(request.messages[1][1])
            return "阶段比较" if data["phase"] == "preliminary" else "综合结论"

        generator = BoundedAnswerGenerator(transport, shared)
        _, _, calls, stream = scenario(
            ("answer_then_research", "answer"),
            tools=1,
            answer_generator=generator,
            decision_budget=shared,
        )
        events = await collect(stream)
        assert events[-1].reason == "answered"
        assert calls == ["model", "use_tool", "model"]
        assert events[-2].observation == "综合结论"
        data = [json.loads(request.messages[1][1]) for request in requests]
        assert [item["phase"] for item in data] == ["preliminary", "final"]
        assert data[0]["observations"]["entries"] == []
        assert [entry["content"] for entry in data[1]["observations"]["entries"]] == [
            "阶段比较",
            "5",
        ]
        assert data[0]["context"]["request_id"] == "loop-1"
        assert data[1]["context"]["request_id"].startswith("observation:")
        assert len(shared._requests) == 4  # two decisions, two answer stages
        assert requests[0].call_id != requests[1].call_id
        assert all(request.max_attempts == 1 for request in requests)

    asyncio.run(run())


def test_answer_admission_denial_stops_before_tool_and_provider():
    async def run():
        async def transport(request):
            pytest.fail("denied provider call")

        generator = BoundedAnswerGenerator(transport, DecisionBudget(0, 0, 0))
        _, _, calls, stream = scenario(
            ("answer_then_research",), answer_generator=generator
        )
        events = await collect(stream)
        assert events[-1].reason == "action_failed"
        assert calls == ["model"]

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["raise", "self_cancel", "empty", "oversize"])
def test_failed_generated_answer_is_not_shown_and_never_starts_tool(failure):
    async def run():
        requests = []

        async def transport(request):
            requests.append(request)
            if failure == "raise":
                raise RuntimeError("private provider details")
            if failure == "self_cancel":
                raise asyncio.CancelledError
            return "" if failure == "empty" else "x" * 8001

        _, _, calls, stream = scenario(
            ("answer_then_research",),
            answer_generator=BoundedAnswerGenerator(transport, budget()),
        )
        events = await collect(stream)
        assert events[-1].reason == "action_failed"
        assert calls == ["model"] and len(requests) == 1
        assert "private provider details" not in repr(events)
        assert all(not getattr(event, "observation", "") for event in events)

    asyncio.run(run())


def test_reservation_changes_intent_before_provider_never_sends():
    async def run():
        state = []

        class Advances:
            def reserve(self, *args):
                state[0] = replace(state[0], user_message="用户已换题")
                return "reserved"

        async def transport(request):
            pytest.fail("changed intent reached provider")

        _, actual, calls, stream = scenario(
            ("answer_then_research",),
            answer_generator=BoundedAnswerGenerator(transport, Advances()),
        )
        state = actual
        events = await collect(stream)
        assert events[-1].reason == "action_failed"
        assert calls == ["model"]

    asyncio.run(run())


def test_outer_stage_deadline_cancels_nested_generation_without_late_delivery():
    async def run():
        release, done = asyncio.Event(), asyncio.Event()

        async def transport(request):
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            done.set()
            return "迟到的正文"

        generator = BoundedAnswerGenerator(
            transport, budget(), AnswerLimits(timeout_seconds=5)
        )
        _, _, calls, stream = scenario(
            ("answer_then_research",),
            answer_generator=generator,
            limits=LoopLimits(action_timeout_seconds=0.01),
        )
        events = await collect(stream)
        assert events[-1].reason == "action_failed"
        assert events[-1].detail == "timeout" and events[-1].outcome_unknown
        assert calls == ["model"]
        release.set()
        await asyncio.wait_for(done.wait(), 1)
        assert "迟到的正文" not in repr(events)

    asyncio.run(run())


def test_closing_after_generated_preliminary_stops_tool():
    async def run():
        async def transport(request):
            return "初步分析"

        _, _, calls, stream = scenario(
            ("answer_then_research",),
            answer_generator=BoundedAnswerGenerator(transport, budget()),
        )
        await anext(stream)
        assert (await anext(stream)).observation == "初步分析"
        await stream.aclose()
        assert calls == ["model"]

    asyncio.run(run())


def test_reopened_answer_admission_prevents_duplicate_loop_generation(tmp_path):
    async def run():
        path = tmp_path / "native-answer.sqlite"
        requests = []

        def reopen():
            return SqliteDecisionAdmission(
                path, max_calls=4, max_prompt_chars=400000, max_output_tokens=10000
            )

        async def transport(request):
            requests.append(request)
            return "一次回答"

        for expected in ("answered", "action_failed"):
            _, _, calls, stream = scenario(
                ("answer",),
                answer_generator=BoundedAnswerGenerator(transport, reopen()),
            )
            assert (await collect(stream))[-1].reason == expected
            assert calls == ["model"]
        assert len(requests) == 1

    asyncio.run(run())


def test_direct_adapter_exposes_sanitized_failure_receipt_to_trusted_caller():
    async def run():
        item = value()

        async def transport(request):
            raise RuntimeError("private provider details")

        generator = BoundedAnswerGenerator(transport, budget())
        with pytest.raises(AnswerGenerationError) as caught:
            await generator.generate(item, current_context=lambda: item.context)
        assert caught.value.result.status == "provider_error"
        assert caught.value.result.attempted and caught.value.result.outcome_unknown
        assert not caught.value.result.answer
        assert "private provider details" not in str(caught.value)

    asyncio.run(run())


def test_mutually_exclusive_adapters_fail_before_model():
    async def run():
        async def answer(value):
            pytest.fail("conflicting handler invoked")

        async def transport(request):
            pytest.fail("conflicting generator invoked")

        _, _, calls, stream = scenario(
            answer_handler=answer,
            answer_generator=BoundedAnswerGenerator(transport, budget()),
        )
        with pytest.raises(ValueError, match="conflicting"):
            await anext(stream)
        assert not calls

    asyncio.run(run())


@pytest.mark.parametrize(
    "kwargs", [{"transport": None}, {"budget": object()}, {"limits": object()}]
)
def test_invalid_generator_configuration(kwargs):
    async def transport(request):
        return "unused"

    with pytest.raises(ValueError):
        BoundedAnswerGenerator(**{"transport": transport, "budget": budget(), **kwargs})
