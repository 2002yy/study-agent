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
    reserve_call,
    reset_spend,
    send_budget_scope,
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
