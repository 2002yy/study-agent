"""M3-QD-2d: one production turn - start, cancel, disconnect, settle once.

These drive the real ``OwnedConversationBinding`` over real SQLite snapshots and a real
SDK pointed at fake HTTP, because the question under test is precisely whether the host
lifecycle keeps its books when the *real* loop does the spending. A stand-in loop would
answer a different question.

What is faked and why: the spend port. Its only production implementation is #259, which
is still an open draft on a stacked base, so the recording double here is the *absence* of
that ledger made observable - not a second ledger.
"""

import asyncio
from contextlib import aclosing
from dataclasses import replace
import json

import httpx
import pytest

from src.application.conversation_action_dispatch import ActionBudget
from src.application.conversation_decision import ConversationAction
from src.application.conversation_decision_runner import (
    COST_LEDGER_REFUSED,
    DecisionBudget,
)
from src.application.conversation_deepseek_service import DeepSeekConversationService
from src.application.conversation_owned_binding import (
    ConversationContextInputs,
    OwnedConversationBinding,
    OwnedRunResources,
    SQLiteChatSnapshotReader,
)
from src.application.conversation_spend_gate import SpendGatedAdmission
from src.application.conversation_turn_lifecycle import (
    CANCELLED,
    MAX_TURN_SECONDS,
    TurnDeadline,
    TurnLifecycle,
    TurnSettlement,
    turn_identities,
)
from src.application.conversation_bounded_loop import LoopLimits, LoopStopped
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository
from src.web import semantic_admission
from tests.test_conversation_decision_context import snapshots
from tests.test_conversation_deepseek_session import factory, response, settings


# --- doubles ---------------------------------------------------------------------------


class RecordingSpend:
    """A ``LedgerPort`` that records instead of keeping money.

    ``refuse`` makes the cost track stricter than the logical one, which is the case Q-10
    says must stop the request rather than let the looser track win.
    """

    def __init__(self, *, refuse: bool = False):
        self.refuse = refuse
        self.reserved: list[tuple[str, str, int]] = []
        self.settled: list[tuple[str, str, int]] = []

    def reserve(self, request_id, *, model, max_output_tokens, prompt_chars):
        self.reserved.append((request_id, model, max_output_tokens))
        return "refused" if self.refuse else "reserved"

    def settle(
        self,
        request_id,
        *,
        outcome,
        cost_micros,
        cost_basis=None,
        evidence_ref="",
    ):
        self.settled.append((request_id, outcome, cost_micros))

    @property
    def outcomes(self):
        return [outcome for _, outcome, _ in self.settled]

    def settled_ids(self):
        return [rid for rid, outcome, _ in self.settled if outcome == "settled"]


class CancelAfter:
    """Answers ``False`` to the first ``n`` probes, then ``True``.

    Counting probes rather than time keeps the test about *where* the check happens, which
    is the property under test. A full turn probes three times in this order: the host
    before it starts, the loop before the first decision, the loop before the dispatch.
    """

    def __init__(self, n):
        self.n = n
        self.probes = 0

    def __call__(self):
        self.probes += 1
        return self.probes > self.n


def decision(action="answer", tool=None):
    def build(request_id):
        return json.dumps(
            {
                "schema": "conversation-decision-v1",
                "request_id": request_id,
                "action": action,
                "relation": "continuation",
                "reason": "继续本轮分析",
                "focus": "考虑Agent编辑",
                "tool": tool,
                "target_run_id": None,
                "target_revision": None,
                "active_run_disposition": "none",
            },
            ensure_ascii=False,
        )

    return build


def setup(tmp_path, *, script, spend=None, inputs=None, loop_limits=None, handlers=None):
    path = tmp_path / "turn lifecycle.sqlite"
    repository = RuntimeRepository(RuntimeDatabase(path))
    thread, turn, turns = snapshots()
    repository.create_chat_thread(thread)
    for item in turns:
        repository.add_chat_turn(item)

    calls: list[dict] = []
    scripted = list(script)

    def http(req):
        wire = json.loads(req.content)
        calls.append(wire)
        if "response_format" in wire:
            context = json.loads(wire["messages"][1]["content"])
            step = scripted.pop(0) if scripted else decision()
            return httpx.Response(200, json=response(step(context["request_id"])))
        return httpx.Response(200, json=response("来自服务端上下文的回答"))

    spend = spend or RecordingSpend()
    gate = SpendGatedAdmission(
        DecisionBudget(8, 1_000_000, 20_000),
        spend=spend,
        model="configured-deepseek-model",
        price_micros=lambda tokens: tokens * 3,
    )

    def resources(snapshot):
        return OwnedRunResources(
            gate, ActionBudget(6, 4), handlers or {}, loop_limits or LoopLimits()
        )

    service = DeepSeekConversationService(settings(), factory(http, [], []))
    binding = OwnedConversationBinding(
        service,
        SQLiteChatSnapshotReader(path),
        resources,
        inputs
        or (
            lambda snapshot: ConversationContextInputs(
                available_tools=("web_search",), remaining_tool_calls=3
            )
        ),
    )
    snapshot = SQLiteChatSnapshotReader(path)(thread.id, turn.id)
    return binding, snapshot, gate, spend, calls


def lifecycle(binding, gate, *, cancel=lambda: False, deadline=None):
    return TurnLifecycle(
        binding,
        gate=gate,
        deadline=deadline or TurnDeadline(),
        should_cancel=cancel,
    )


async def drain(stream):
    return [event async for event in stream]


class ToolHandler:
    """A USE_TOOL handler that records whether it ran. It never should when cancelled."""

    def __init__(self):
        self.invocations = 0

    async def __call__(self, invocation):
        self.invocations += 1
        return "工具观察"


# --- the four things the host owns -----------------------------------------------------


def test_a_turn_cancelled_before_it_starts_buys_nothing(tmp_path):
    async def run():
        binding, snapshot, gate, spend, calls = setup(
            tmp_path, script=[decision()]
        )
        turn = lifecycle(binding, gate, cancel=lambda: True)

        events = await drain(turn.stream(snapshot))

        assert events == [LoopStopped(CANCELLED, 0, 0, False, "before_start")]
        # The whole point: no model call, no reservation, nothing to settle.
        assert calls == []
        assert spend.reserved == [] and spend.settled == []
        assert turn.settlement == TurnSettlement()

    asyncio.run(run())


def test_a_cancel_that_arrives_between_start_and_the_first_decision_buys_nothing(
    tmp_path,
):
    async def run():
        binding, snapshot, gate, spend, calls = setup(
            tmp_path, script=[decision("answer")]
        )
        # The host let the turn begin; the cancel landed before the loop admitted anything.
        turn = lifecycle(binding, gate, cancel=CancelAfter(1))

        events = await drain(turn.stream(snapshot))

        assert events == [LoopStopped(CANCELLED, 0, 0, False, "before_decision")]
        assert calls == []
        assert spend.reserved == []
        assert turn.settlement == TurnSettlement()

    asyncio.run(run())


def test_a_cancel_after_the_decision_stops_before_the_tool_runs(tmp_path):
    async def run():
        tool = ToolHandler()
        binding, snapshot, gate, spend, calls = setup(
            tmp_path,
            script=[decision("use_tool", "web_search")],
            handlers={ConversationAction.USE_TOOL: tool},
        )
        turn = lifecycle(binding, gate, cancel=CancelAfter(2))

        events = await drain(turn.stream(snapshot))

        # Exactly one decision was bought; the tool stage never reached the handler, so the
        # cancel saved both a tool slot and everything the tool would have spent.
        assert len(calls) == 1
        assert tool.invocations == 0
        assert events[-1].reason == CANCELLED
        assert events[-1].detail == "use_tool"
        # Money that was spent is booked as spent, not refunded and not left open.
        assert len(spend.settled_ids()) == 1
        assert turn.settlement.unresolved == ()

    asyncio.run(run())


def test_a_successful_turn_settles_both_the_decision_and_the_answer(tmp_path):
    async def run():
        binding, snapshot, gate, spend, calls = setup(
            tmp_path, script=[decision("answer")]
        )
        turn = lifecycle(binding, gate)

        events = await drain(turn.stream(snapshot))

        assert isinstance(events[-1], LoopStopped)
        assert events[-1].reason == "answered"
        # One decision reservation + one answer reservation, both closed as settled.
        assert len(spend.reserved) == 2
        assert len(spend.settled) == 2
        assert spend.outcomes == ["settled", "settled"]
        assert any(rid.startswith("answer:") for rid in spend.settled_ids())
        assert turn.settlement.complete
        # Every settled id was also recorded on the turn receipt, in order.
        assert set(turn.settlement.settled) == set(spend.settled_ids())

    asyncio.run(run())


def test_a_disconnect_closes_the_turn_and_cannot_settle_twice(tmp_path):
    async def run():
        binding, snapshot, gate, spend, calls = setup(
            tmp_path, script=[decision("use_tool", "web_search")]
        )
        turn = lifecycle(binding, gate)

        events = []
        async with aclosing(turn.stream(snapshot)) as stream:
            async for event in stream:
                events.append(event)
                # Read one event, then behave like a browser tab that closed: stop
                # consuming and close. The turn must still close its books.
                break

        assert events, "the first decision should have been produced before the disconnect"
        settled_after_disconnect = list(spend.settled)
        assert len(settled_after_disconnect) == 1
        assert turn.settlement.unresolved == ()

        # A second close is a no-op, not a second settlement of the same call.
        await turn.stream(snapshot).aclose()
        assert spend.settled == settled_after_disconnect

    asyncio.run(run())


def test_an_admitted_call_that_never_reported_is_closed_as_unresolved(tmp_path):
    async def run():
        binding, snapshot, gate, spend, calls = setup(
            tmp_path, script=[decision("answer")]
        )
        # An earlier call on this turn was admitted and never came back. Settling it as
        # "refunded" would report money that was probably spent as money never spent.
        assert gate.reserve("reselect:stranded", 10, 20) == "reserved"
        assert gate.open_request_ids == ("reselect:stranded",)

        turn = lifecycle(binding, gate)
        await drain(turn.stream(snapshot))

        assert ("reselect:stranded", "unresolved", None) in spend.settled
        assert turn.settlement.unresolved == ("reselect:stranded",)
        assert not turn.settlement.complete
        assert gate.open_request_ids == ()

    asyncio.run(run())


# --- Q-10: the stricter track wins -----------------------------------------------------


def test_a_refused_cost_track_stops_the_call_before_the_provider(tmp_path):
    async def run():
        binding, snapshot, gate, spend, calls = setup(
            tmp_path, script=[decision("answer")], spend=RecordingSpend(refuse=True)
        )
        turn = lifecycle(binding, gate)

        events = await drain(turn.stream(snapshot))

        # Nothing reached the model, and the receipt says *which* track refused instead of
        # collapsing into the generic "admission_unavailable".
        assert calls == []
        assert events[-1].reason == "decision_failed"
        assert events[-1].detail == COST_LEDGER_REFUSED
        assert spend.settled == []
        assert turn.settlement == TurnSettlement()

    asyncio.run(run())


def test_the_cost_track_verdict_is_the_same_string_as_the_research_gate_uses():
    # Two modules name the same refusal. If they drift, a cost refusal in the research
    # round and a cost refusal in a chat turn would be reported under different keys.
    assert semantic_admission.REJECTED_LEDGER == COST_LEDGER_REFUSED


# --- time: research may not spend the answer's window ----------------------------------


def test_the_loop_window_is_the_turn_minus_the_answer_and_settlement_reserves():
    deadline = TurnDeadline(
        total_seconds=30.0, answer_reserve_seconds=4.0, settlement_reserve_seconds=1.0
    )
    assert deadline.research_seconds == 25.0
    assert deadline.loop_limits().timeout_seconds == 25.0
    # The per-action window is still bounded by the action policy, not widened by the turn.
    assert deadline.action_policy().research_seconds == 25.0


def test_a_deadline_that_leaves_no_research_time_is_refused_before_anything_runs():
    deadline = TurnDeadline(
        total_seconds=10.0, answer_reserve_seconds=8.0, settlement_reserve_seconds=2.0
    )
    with pytest.raises(ValueError, match="turn_leaves_no_time_for_research"):
        deadline.research_seconds


def test_a_deadline_beyond_the_loop_ceiling_is_refused():
    with pytest.raises(ValueError, match="turn_total_seconds_out_of_range"):
        TurnDeadline(total_seconds=MAX_TURN_SECONDS + 1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"total_seconds": 0},
        {"answer_reserve_seconds": 0},
        {"settlement_reserve_seconds": -1},
        {"total_seconds": float("inf")},
    ],
)
def test_zero_or_negative_reserves_are_refused_at_construction(kwargs):
    # Refused before the turn exists, so there is no window in which the loop is built
    # with a budget that cannot pay for anything.
    with pytest.raises(ValueError):
        TurnDeadline(**kwargs)


def test_the_lifecycle_refuses_to_build_on_a_deadline_with_no_research_time(tmp_path):
    binding, snapshot, gate, spend, calls = setup(tmp_path, script=[decision()])

    class Broken(TurnDeadline):
        @property
        def research_seconds(self):
            raise ValueError("turn_leaves_no_time_for_research")

    with pytest.raises(ValueError, match="turn_leaves_no_time_for_research"):
        TurnLifecycle(binding, gate=gate, deadline=Broken())
    assert calls == []


# --- identities come from the real turn, not from the host -----------------------------


def test_identities_are_read_off_the_prepared_turn(tmp_path):
    binding, snapshot, gate, spend, calls = setup(tmp_path, script=[decision()])

    identities = turn_identities(snapshot)

    assert identities.thread_id == snapshot.thread.id
    assert identities.turn_id == snapshot.turn.id
    assert identities.operation_id == snapshot.turn.operation_id


def test_a_turn_from_another_thread_is_refused(tmp_path):
    binding, snapshot, gate, spend, calls = setup(tmp_path, script=[decision()])
    foreign = replace(snapshot, thread=replace(snapshot.thread, id="chat-foreign"))

    with pytest.raises(ValueError, match="prepared_turn_not_owned_by_thread"):
        turn_identities(foreign)


def test_something_that_is_not_a_prepared_turn_is_refused():
    with pytest.raises(ValueError, match="not_a_prepared_turn"):
        turn_identities(object())


def test_failed_completed_settlement_keeps_identity_for_safe_retry():
    class FlakySpend(RecordingSpend):
        def __init__(self):
            super().__init__()
            self.fail_once = True

        def settle(
            self, request_id, *, outcome, cost_micros, cost_basis=None, evidence_ref=""
        ):
            if self.fail_once:
                self.fail_once = False
                raise OSError("ledger_unavailable")
            super().settle(
                request_id,
                outcome=outcome,
                cost_micros=cost_micros,
                cost_basis=cost_basis,
                evidence_ref=evidence_ref,
            )

    spend = FlakySpend()
    gate = SpendGatedAdmission(
        DecisionBudget(4, 1000, 1000),
        spend=spend,
        model="m",
        price_micros=lambda tokens: tokens,
    )
    assert gate.reserve("a", 1, 4) == "reserved"
    with pytest.raises(OSError, match="ledger_unavailable"):
        gate.settle_completed("a", evidence_ref="worker_receipt:a#test")
    assert gate.open_request_ids == ("a",)
    assert gate.settle_completed("a", evidence_ref="worker_receipt:a#test") is True
    assert gate.settle_completed("a", evidence_ref="worker_receipt:a#test") is False
    assert spend.settled == [("a", "settled", 4)]


def test_failed_unresolved_settlement_keeps_pending_requests_for_retry():
    class FlakySpend(RecordingSpend):
        def __init__(self):
            super().__init__()
            self.fail_once = True

        def settle(
            self, request_id, *, outcome, cost_micros, cost_basis=None, evidence_ref=""
        ):
            if self.fail_once:
                self.fail_once = False
                raise OSError("ledger_unavailable")
            super().settle(
                request_id,
                outcome=outcome,
                cost_micros=cost_micros,
                cost_basis=cost_basis,
                evidence_ref=evidence_ref,
            )

    spend = FlakySpend()
    gate = SpendGatedAdmission(
        DecisionBudget(4, 1000, 1000),
        spend=spend,
        model="m",
        price_micros=lambda tokens: tokens,
    )
    assert gate.reserve("a", 1, 4) == "reserved"
    assert gate.reserve("b", 1, 4) == "reserved"
    with pytest.raises(OSError, match="ledger_unavailable"):
        gate.settle_unresolved()
    assert gate.open_request_ids == ("a", "b")
    assert gate.settle_unresolved() == ("a", "b")
    assert gate.open_request_ids == ()
    assert spend.settled == [("a", "unresolved", None), ("b", "unresolved", None)]


def test_a_reserve_only_ledger_is_refused_rather_than_inventing_settlement():
    class NoSettlement:
        def reserve(self, request_id, *, model, max_output_tokens):
            return "reserved"

    with pytest.raises(ValueError, match="invalid spend port"):
        SpendGatedAdmission(
            DecisionBudget(4, 1000, 1000),
            spend=NoSettlement(),
            model="m",
            price_micros=lambda tokens: tokens,
        )


def test_the_gate_stops_reserving_once_the_turn_closes(tmp_path):
    spend = RecordingSpend()
    gate = SpendGatedAdmission(
        DecisionBudget(4, 1000, 1000),
        spend=spend,
        model="m",
        price_micros=lambda tokens: tokens,
    )
    assert gate.reserve("a", 1, 1) == "reserved"
    assert gate.settle_completed("a", evidence_ref="worker_receipt:a#test") is True
    assert gate.settle_completed("a", evidence_ref="worker_receipt:a#test") is False
    assert gate.settle_unresolved() == ()
    assert gate.open_request_ids == ()
