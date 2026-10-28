"""The send budget is enforced inside reserve_call, before any money is reserved.

Layer contract for the Quality-0 preview: experiment 45, arm 20/20/5, round 4/4/1.
Every check happens before a request leaves the process, and an SDK retry is
charged as the extra attempt it is.
"""

from __future__ import annotations

import pytest

from src.application.send_budget import SendBudget
from src.llm_spend_guard import (
    SendLimitExceeded,
    SpendLimitExceeded,
    pre_reserved_send,
    reserve_call,
    reset_spend,
    send_budget_scope,
    spend_identity,
)


@pytest.fixture(autouse=True)
def _clean_guard(monkeypatch):
    for key in (
        "LLM_SPEND_CAP_CNY",
        "LLM_SPEND_EXPERIMENT_ID",
        "LLM_SPEND_EXPERIMENT_CAP_CNY",
        "LLM_SPEND_LEDGER_DB",
        "LLM_SPEND_INPUT_CNY_PER_MTOK",
        "LLM_SPEND_OUTPUT_CNY_PER_MTOK",
    ):
        monkeypatch.delenv(key, raising=False)
    reset_spend()
    yield
    reset_spend()


def _send(request_key: str | None = None, attempts: int = 1) -> None:
    reserve_call(
        prompt_chars=100,
        max_tokens=50,
        attempts=attempts,
        purpose="test",
        request_key=request_key,
    )


def test_without_a_binding_nothing_is_counted(tmp_path):
    budget = SendBudget(tmp_path / "sends.sqlite")
    budget.register({"experiment:q0": 1})

    for _ in range(3):
        _send()

    assert budget.usage("experiment:q0") == 0


def test_the_fifth_send_in_a_round_is_refused_before_sending(tmp_path):
    budget = SendBudget(tmp_path / "sends.sqlite")
    budget.register({"experiment:q0": 45, "arm:current": 20, "round:current:r1": 4})

    with send_budget_scope(
        budget, ["experiment:q0", "arm:current", "round:current:r1"]
    ):
        for index in range(4):
            _send(f"k{index}")
        with pytest.raises(SendLimitExceeded, match="round:current:r1"):
            _send("k4")

    assert budget.usage("round:current:r1") == 4
    assert budget.usage("arm:current") == 4


def test_an_exhausted_arm_does_not_consume_the_other_arm(tmp_path):
    budget = SendBudget(tmp_path / "sends.sqlite")
    budget.register(
        {
            "experiment:q0": 45,
            "arm:current": 1,
            "arm:candidate": 1,
            "round:current:r1": 4,
            "round:candidate:r1": 4,
        }
    )

    with send_budget_scope(budget, ["experiment:q0", "arm:current", "round:current:r1"]):
        _send("c1")
        with pytest.raises(SendLimitExceeded):
            _send("c2")

    with send_budget_scope(
        budget, ["experiment:q0", "arm:candidate", "round:candidate:r1"]
    ):
        _send("d1")

    assert budget.usage("arm:current") == 1
    assert budget.usage("arm:candidate") == 1
    # The refused current send must not have consumed the shared experiment quota.
    assert budget.usage("experiment:q0") == 2


def test_the_experiment_cap_binds_across_arms(tmp_path):
    budget = SendBudget(tmp_path / "sends.sqlite")
    budget.register(
        {
            "experiment:q0": 2,
            "arm:current": 20,
            "arm:candidate": 20,
            "round:current:r1": 4,
            "round:candidate:r1": 4,
        }
    )

    with send_budget_scope(budget, ["experiment:q0", "arm:current", "round:current:r1"]):
        _send("c1")
        _send("c2")

    with send_budget_scope(
        budget, ["experiment:q0", "arm:candidate", "round:candidate:r1"]
    ):
        with pytest.raises(SendLimitExceeded, match="experiment:q0"):
            _send("d1")

    assert budget.usage("arm:candidate") == 0


def test_an_sdk_retry_is_charged_as_extra_attempts(tmp_path):
    budget = SendBudget(tmp_path / "sends.sqlite")
    budget.register({"experiment:q0": 3})

    with send_budget_scope(budget, ["experiment:q0"]):
        _send("k1", attempts=2)  # one call, two possible sends
        with pytest.raises(SendLimitExceeded):
            _send("k2", attempts=2)
        assert budget.usage("experiment:q0") == 2


def test_reusing_a_send_key_is_refused(tmp_path):
    budget = SendBudget(tmp_path / "sends.sqlite")
    budget.register({"experiment:q0": 5})

    with send_budget_scope(budget, ["experiment:q0"]):
        _send("same-key")
        with pytest.raises(SendLimitExceeded, match="already counted"):
            _send("same-key")


def test_unnamed_sends_still_get_their_own_count(tmp_path):
    budget = SendBudget(tmp_path / "sends.sqlite")
    budget.register({"experiment:q0": 2})

    with send_budget_scope(budget, ["experiment:q0"]):
        _send()
        _send()
        with pytest.raises(SendLimitExceeded):
            _send()

    assert budget.usage("experiment:q0") == 2


def test_a_restarted_process_cannot_reopen_the_budget(tmp_path):
    path = tmp_path / "sends.sqlite"
    first = SendBudget(path)
    first.register({"experiment:q0": 1})
    with send_budget_scope(first, ["experiment:q0"]):
        _send("first")

    restarted = SendBudget(path)
    restarted.register({"experiment:q0": 1})
    with send_budget_scope(restarted, ["experiment:q0"]):
        with pytest.raises(SendLimitExceeded):
            _send("second")


# -- nesting: an inner scope narrows the outer one, it does not replace it --------


def test_nested_scopes_charge_every_level_of_one_send(tmp_path):
    """``experiment -> arm -> round`` must charge all three, not just the round."""

    budget = SendBudget(tmp_path / "sends.sqlite")
    budget.register(
        {"experiment:q0": 45, "arm:current": 20, "round:current:r1": 4}
    )

    with send_budget_scope(budget, ["experiment:q0", "arm:current"]):
        with send_budget_scope(budget, ["round:current:r1"]):
            _send("k1")

    assert budget.usage("experiment:q0") == 1
    assert budget.usage("arm:current") == 1
    assert budget.usage("round:current:r1") == 1


def test_an_exhausted_round_does_not_consume_the_wider_scopes(tmp_path):
    budget = SendBudget(tmp_path / "sends.sqlite")
    budget.register(
        {"experiment:q0": 45, "arm:current": 20, "round:current:r1": 1}
    )

    with send_budget_scope(budget, ["experiment:q0", "arm:current"]):
        with send_budget_scope(budget, ["round:current:r1"]):
            _send("k1")
            with pytest.raises(SendLimitExceeded, match="round:current:r1"):
                _send("k2")

    assert budget.usage("round:current:r1") == 1
    assert budget.usage("arm:current") == 1
    assert budget.usage("experiment:q0") == 1


def test_leaving_an_inner_scope_restores_the_outer_one(tmp_path):
    budget = SendBudget(tmp_path / "sends.sqlite")
    budget.register(
        {"experiment:q0": 45, "arm:current": 20, "round:current:r1": 4}
    )

    with send_budget_scope(budget, ["experiment:q0", "arm:current"]):
        with send_budget_scope(budget, ["round:current:r1"]):
            _send("k1")
        _send("k2")  # next round: the round scope is gone, the outer two remain

    assert budget.usage("round:current:r1") == 1
    assert budget.usage("arm:current") == 2
    assert budget.usage("experiment:q0") == 2


def test_nesting_a_second_budget_file_is_refused(tmp_path):
    """No single transaction can vouch for counts split across two ledgers."""

    first = SendBudget(tmp_path / "a.sqlite")
    first.register({"experiment:a": 5})
    second = SendBudget(tmp_path / "b.sqlite")
    second.register({"experiment:b": 5})

    with send_budget_scope(first, ["experiment:a"]):
        with pytest.raises(ValueError, match="must share one file"):
            with send_budget_scope(second, ["experiment:b"]):
                _send("k1")

    assert first.usage("experiment:a") == 0
    assert second.usage("experiment:b") == 0


def test_the_same_file_bound_twice_is_still_one_budget(tmp_path):
    path = tmp_path / "sends.sqlite"
    budget = SendBudget(path)
    budget.register({"experiment:q0": 5, "arm:current": 5})
    reopened = SendBudget(path)

    with send_budget_scope(budget, ["experiment:q0", "arm:current"]):
        with send_budget_scope(reopened, ["experiment:q0"]):
            _send("k1")

    assert budget.usage("experiment:q0") == 1
    assert budget.usage("arm:current") == 1


# -- the production shape: settlement adapter reserves, transport re-checks ------


EXPERIMENT = "preview-q0"


def _configure(monkeypatch, database, *, cap: str = "10") -> None:
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(database.resolve()))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", EXPERIMENT)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", cap)
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")


def _adapter(database):
    from src.application.spend_settlement_adapter import SettlementLedgerAdapter
    from src.infrastructure.sqlite.database import RuntimeDatabase
    from src.infrastructure.sqlite.spend_settlement import SpendSettlementRepository

    RuntimeDatabase(database).initialize()
    return SettlementLedgerAdapter(SpendSettlementRepository(database))


def _reserve_through(adapter, key: str = "key-1"):
    return adapter.reserve(
        key, model="deepseek-chat", max_output_tokens=100, prompt_chars=1_000
    )


def _identity():
    return spend_identity(
        run_id="run1", operation_id="op1", invocation="1", experiment=EXPERIMENT
    )


def test_an_admitted_send_is_counted_exactly_once(monkeypatch, tmp_path):
    """The adapter reserves, the transport re-checks: one physical send, one unit.

    Charging in both places would halve the usable budget; charging in neither
    would leave the preview's 45 unenforced, because every real send travels
    through the pre-reserved-send shortcut.
    """

    from src.application.spend_settlement_adapter import RESERVED

    database = tmp_path / "runtime.sqlite"
    _configure(monkeypatch, database)
    adapter = _adapter(database)
    budget = SendBudget(tmp_path / "sends.sqlite")
    budget.register({f"experiment:{EXPERIMENT}": 2})

    with send_budget_scope(budget, [f"experiment:{EXPERIMENT}"]):
        with _identity():
            assert _reserve_through(adapter) == RESERVED
            authorization = adapter.claim_send_authorization("key-1")
            assert authorization is not None
            with pre_reserved_send(authorization):
                reserve_call(
                    prompt_chars=1_000,
                    max_tokens=100,
                    attempts=1,
                    purpose="chat",
                    model="deepseek-chat",
                    request_key="key-1",
                )

    assert budget.usage(f"experiment:{EXPERIMENT}") == 1
    assert budget.remaining(f"experiment:{EXPERIMENT}") == 1


def test_an_exhausted_send_budget_aborts_instead_of_looking_like_a_cost_refusal(
    monkeypatch, tmp_path
):
    """A stop must not be reported as the per-call refusal the runner tolerates.

    ``cost_ledger_refused`` means "this call did not fit"; the runner then keeps
    the round going. Returning that for an exhausted send budget would record the
    rest of the preview as model behaviour when no model was called.
    """

    from src.application.spend_settlement_adapter import RESERVED

    database = tmp_path / "runtime.sqlite"
    _configure(monkeypatch, database)
    adapter = _adapter(database)
    budget = SendBudget(tmp_path / "sends.sqlite")
    budget.register({f"experiment:{EXPERIMENT}": 1})

    with send_budget_scope(budget, [f"experiment:{EXPERIMENT}"]):
        with _identity():
            assert _reserve_through(adapter, "key-1") == RESERVED
            with pytest.raises(SendLimitExceeded) as excinfo:
                _reserve_through(adapter, "key-2")
            assert excinfo.value.reason == "exhausted"

    assert budget.usage(f"experiment:{EXPERIMENT}") == 1


def test_an_unreadable_send_budget_stops_the_run(monkeypatch, tmp_path):
    """Fail closed: a missing cap is not "unlimited sends"."""

    budget = SendBudget(tmp_path / "sends.sqlite")
    budget.register({"experiment:q0": 1})

    with send_budget_scope(budget, ["experiment:q0", "arm:current"]):
        with pytest.raises(SendLimitExceeded) as excinfo:
            _send("k1")
        assert excinfo.value.reason == "unavailable"


def test_a_money_refusal_still_spends_the_send_unit(monkeypatch, tmp_path):
    """Documented trade-off: the send count is charged before the money check.

    The two budgets live in different files, so no single transaction can cover
    both. Charging the send first can burn a unit on a send that money refused;
    charging money first would leave an unrefundable money reservation behind for
    a send that never happened, which corrupts the spend evidence. The preview
    prefers a slightly smaller usable send budget over inflated spend claims.
    """

    monkeypatch.setenv("LLM_SPEND_CAP_CNY", "0.000001")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1000")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1000")
    budget = SendBudget(tmp_path / "sends.sqlite")
    budget.register({"experiment:q0": 1})

    with send_budget_scope(budget, ["experiment:q0"]):
        with pytest.raises(SpendLimitExceeded):
            _send("k1")

    assert budget.usage("experiment:q0") == 1
