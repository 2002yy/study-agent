"""M3-QC acceptance: one admission gate, two independent accounting tracks, no re-buy.

Maps to Q-10 / Q-11 of ``docs/CL_M3_CAPABILITY_CONTRACT.md``. The negative controls matter
more than the happy path: "refused" and "spent" must not be confusable, and an unknown
outcome must not be reported as a refund.
"""

from __future__ import annotations

import pytest

from src.web.semantic_admission import (
    FAILED,
    REJECTED_LEDGER,
    SETTLED,
    UNRESOLVED,
    AdmissionRefused,
    AdmittedCompletion,
    request_id_for,
    round_task_name,
    validate_tool_call,
)
from src.web.semantic_planner import PlanningIdentity


class FakeLogical:
    """Stand-in for ``SqliteDecisionAdmission``: same reserve contract, no persistence."""

    def __init__(self, max_calls: int = 3, max_chars: int = 10_000) -> None:
        self.max_calls = max_calls
        self.max_chars = max_chars
        self.seen: list[str] = []
        self.chars = 0

    def reserve(self, request_id: str, prompt_chars: int, output_tokens: int) -> str:
        if request_id in self.seen:
            return "already_attempted"
        if len(self.seen) >= self.max_calls or self.chars + prompt_chars > self.max_chars:
            return "budget_exhausted"
        self.seen.append(request_id)
        self.chars += prompt_chars
        return "reserved"


class FakeLedger:
    """Real-cost port. Records every reservation and settlement, refunds nothing."""

    def __init__(self, refuse: bool = False) -> None:
        self.refuse = refuse
        self.reserved: list[str] = []
        self.settled: list[tuple[str, str, int]] = []

    def reserve(self, request_id: str, *, model: str, max_output_tokens: int) -> str:
        if self.refuse:
            return "refused"
        self.reserved.append(request_id)
        return "reserved"

    def settle(self, request_id: str, *, outcome: str, cost_micros: int) -> None:
        self.settled.append((request_id, outcome, cost_micros))


def messages(text: str = "查询计划") -> list[dict[str, str]]:
    return [{"role": "user", "content": text}]


def build(completion, *, logical=None, ledger=None, estimate=1400):
    logical = logical or FakeLogical()
    ledger = ledger or FakeLedger()
    return (
        AdmittedCompletion(
            completion,
            logical=logical,
            ledger=ledger,
            model="deepseek-chat",
            price_micros=lambda tokens: tokens * 2,
            estimate_output_tokens=estimate,
        ),
        logical,
        ledger,
    )


def task(round_index: int = 1, operation: str = "op-1") -> str:
    return round_task_name(PlanningIdentity(operation, round_index))


def ok_completion(**_kwargs) -> str:
    return '{"intent": "ANSWER"}'


# --- one shared logical quota across planning, decision and answer ---------------------


def test_a_single_logical_quota_is_shared_by_every_phase_of_the_round():
    """Planning, decision and answering draw on the same counter, not one budget each."""

    logical = FakeLogical(max_calls=2)
    wrapper, _, _ = build(ok_completion, logical=logical)

    wrapper(messages=messages(), timeout=3, task_name=task(0))
    wrapper(messages=messages(), timeout=3, task_name=task(1))
    with pytest.raises(AdmissionRefused, match="budget_exhausted"):
        wrapper(messages=messages(), timeout=3, task_name=task(2))

    assert len(logical.seen) == 2


def test_the_quota_refusal_happens_before_the_provider_is_called():
    called: list[str] = []

    def completion(**kwargs):
        called.append(kwargs["task_name"])
        return "{}"

    wrapper, _, _ = build(completion, logical=FakeLogical(max_calls=1))
    wrapper(messages=messages(), timeout=3, task_name=task(0))
    with pytest.raises(AdmissionRefused):
        wrapper(messages=messages(), timeout=3, task_name=task(1))
    assert called == [task(0)]


# --- the real-cost track is independent and stricter-wins -----------------------------


def test_a_cost_ledger_refusal_blocks_a_call_the_logical_track_allowed():
    called: list[str] = []

    def completion(**kwargs):
        called.append(kwargs["task_name"])
        return "{}"

    wrapper, logical, ledger = build(completion, ledger=FakeLedger(refuse=True))
    with pytest.raises(AdmissionRefused, match=REJECTED_LEDGER):
        wrapper(messages=messages(), timeout=3, task_name=task(0))
    assert called == []                       # the provider never saw the request
    assert ledger.reserved == []
    assert logical.seen == [task(0)]          # the logical track did reserve: tracks are not merged


def test_every_successful_call_is_reserved_and_settled_on_the_cost_track():
    wrapper, _, ledger = build(ok_completion)
    wrapper(messages=messages(), timeout=3, task_name=task(0))
    assert ledger.reserved == [task(0)]
    assert ledger.settled == [(task(0), SETTLED, 2800)]


# --- replay cannot re-buy quota -------------------------------------------------------


def test_replaying_the_same_round_does_not_acquire_quota_twice():
    calls: list[str] = []

    def completion(**kwargs):
        calls.append(kwargs["task_name"])
        return "{}"

    logical = FakeLogical()
    wrapper, _, ledger = build(completion, logical=logical)
    wrapper(messages=messages(), timeout=3, task_name=task(1))
    with pytest.raises(AdmissionRefused, match="already_attempted"):
        wrapper(messages=messages(), timeout=3, task_name=task(1))
    assert calls == [task(1)]
    assert ledger.reserved == [task(1)]       # the cost track was not charged again either


def test_an_unidentifiable_call_is_refused_instead_of_given_a_fresh_identity():
    """A random identity on retry would let the retry spend; refusing is the safe default."""

    called: list[str] = []

    def completion(**kwargs):
        called.append(kwargs["task_name"])
        return "{}"

    wrapper, _, _ = build(completion)
    with pytest.raises(ValueError, match="call_task_name_not_round_scoped"):
        wrapper(messages=messages(), timeout=3, task_name="research_turn_interpretation")
    assert called == []


@pytest.mark.parametrize("name", ["", "op-1", "op-1#r1", "op-1#x1#stage", "#r1#stage", "op-1#r#stage"])
def test_round_scoped_names_are_required(name: str):
    with pytest.raises(ValueError, match="call_task_name_not_round_scoped"):
        request_id_for(name)


# --- unknown is not free --------------------------------------------------------------


def test_a_timeout_keeps_the_reservation_and_is_never_reported_as_a_refund():
    def timing_out(**_kwargs):
        raise TimeoutError("provider_slow")

    wrapper, _, ledger = build(timing_out)
    with pytest.raises(TimeoutError):
        wrapper(messages=messages(), timeout=1, task_name=task(0))
    assert ledger.settled == [(task(0), UNRESOLVED, 0)]
    assert wrapper.calls[-1].outcome == UNRESOLVED


@pytest.mark.parametrize(
    "error",
    [
        ConnectionResetError("connection_lost_after_send"),
        RuntimeError("sdk_response_parse_error"),
        TimeoutError("sdk_custom_timeout"),
    ],
)
def test_a_provider_error_without_a_presend_receipt_keeps_money_reserved(error):
    """Exceptions alone cannot prove the provider never received the request."""

    def broken(**_kwargs):
        raise error

    wrapper, _, ledger = build(broken)
    with pytest.raises(type(error)):
        wrapper(messages=messages(), timeout=1, task_name=task(0))
    assert ledger.settled == [(task(0), UNRESOLVED, 0)]
    assert wrapper.calls[-1].outcome == UNRESOLVED


def test_settlement_happens_exactly_once_per_call():
    wrapper, _, ledger = build(ok_completion)
    wrapper(messages=messages(), timeout=3, task_name=task(0))
    wrapper(messages=messages(), timeout=3, task_name=task(1))
    assert len(ledger.settled) == 2
    assert len({row[0] for row in ledger.settled}) == 2


# --- Q-11: USE_TOOL may not bypass the real executor ----------------------------------


REGISTRY = {"web_search": object(), "web_read": object()}
PERMITTED = frozenset({"web_search"})


def test_a_permitted_tool_resolves_to_its_real_executor():
    decision = validate_tool_call(
        action="USE_TOOL", tool="web_search", registry=REGISTRY,
        permitted=PERMITTED, budget_remaining=2, arguments={"query": "二分查找"},
    )
    assert decision.allowed and decision.executor == "web_search"


def test_an_existing_tool_outside_this_action_permission_is_refused():
    """The tool exists; that is not permission. Name existence must never imply access."""

    decision = validate_tool_call(
        action="USE_TOOL", tool="web_read", registry=REGISTRY,
        permitted=PERMITTED, budget_remaining=2,
    )
    assert not decision.allowed and decision.reason == "tool_not_permitted"


def test_an_unknown_tool_is_refused_rather_than_substituted():
    decision = validate_tool_call(
        action="USE_TOOL", tool="web_crawl", registry=REGISTRY,
        permitted=frozenset({"web_crawl", "web_search"}), budget_remaining=2,
    )
    assert not decision.allowed and decision.reason == "unknown_tool"


def test_tool_use_is_refused_for_other_actions_and_for_zero_budget():
    assert not validate_tool_call(
        action="ANSWER", tool="web_search", registry=REGISTRY,
        permitted=PERMITTED, budget_remaining=5,
    ).allowed
    exhausted = validate_tool_call(
        action="USE_TOOL", tool="web_search", registry=REGISTRY,
        permitted=PERMITTED, budget_remaining=0,
    )
    assert not exhausted.allowed and exhausted.reason == "budget_exhausted"
