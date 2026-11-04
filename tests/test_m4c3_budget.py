"""No network: batch limits share the existing experiment's SQLite transaction."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.infrastructure.sqlite.spend_ledger import (
    SpendAdmissionRefused,
    SpendCapExceeded,
    SpendLedger,
    SpendLedgerConflict,
)
from tools.m4c3_budget import EXPERIMENT, PREFIX, reserve_batch_call

NOW = "2026-11-04T00:00:00Z"


def opened(tmp_path, cap=30_000_000):
    path = tmp_path / "spend.db"
    RuntimeDatabase(path).initialize()
    ledger = SpendLedger(path)
    ledger.ensure_experiment(
        EXPERIMENT, cap_micros=cap, pricing_fingerprint="fake", now=NOW
    )
    return ledger


def seed(ledger, key, amount):
    ledger.reserve(
        EXPERIMENT,
        request_key=key,
        amount_micros=amount,
        purpose="fake",
        model="fake",
        identity="fake",
        now=NOW,
    )


@pytest.mark.parametrize("amount", [0, -1, 1_000_001, True, 1.5])
def test_per_call_limit_rejects_before_reserving(tmp_path, amount):
    ledger = opened(tmp_path)
    with pytest.raises(ValueError):
        reserve_batch_call(ledger, task_id="J01", amount_micros=amount, now=NOW)
    assert ledger.experiment_spend(EXPERIMENT)["calls"] == 0


def test_restart_cannot_repeat_a_first_attempt(tmp_path):
    ledger = opened(tmp_path)
    reserve_batch_call(ledger, task_id="J01", amount_micros=100, now=NOW)
    with pytest.raises(SpendLedgerConflict):
        reserve_batch_call(
            SpendLedger(ledger.database_path), task_id="J01", amount_micros=100, now=NOW
        )
    assert ledger.experiment_spend(EXPERIMENT)["calls"] == 1


@pytest.mark.parametrize("cap", [29_000_000, 31_000_000])
def test_cannot_silently_change_shared_cap(tmp_path, cap):
    ledger = opened(tmp_path, cap)
    with pytest.raises(SpendAdmissionRefused, match="shared_cap_mismatch"):
        reserve_batch_call(ledger, task_id="J01", amount_micros=100, now=NOW)


def test_other_work_consumes_shared_cap_but_not_batch_count(tmp_path):
    ledger = opened(tmp_path)
    seed(ledger, "other-experiment-work", 29_500_000)
    with pytest.raises(SpendCapExceeded):
        reserve_batch_call(ledger, task_id="J01", amount_micros=1_000_000, now=NOW)
    reserve_batch_call(ledger, task_id="J01", amount_micros=500_000, now=NOW)


def test_batch_money_limit_is_independent_of_shared_balance(tmp_path):
    ledger = opened(tmp_path)
    seed(ledger, PREFIX + "prior", 12_000_000)
    with pytest.raises(SpendAdmissionRefused, match="batch_budget"):
        reserve_batch_call(ledger, task_id="J01", amount_micros=1, now=NOW)


def test_two_connections_cannot_both_take_the_last_call(tmp_path):
    ledger = opened(tmp_path)
    for i in range(11):
        seed(ledger, PREFIX + f"prior-{i}", 1)
    barrier = Barrier(2)

    def reserve(task):
        other = SpendLedger(ledger.database_path)
        barrier.wait(timeout=5)
        try:
            reserve_batch_call(other, task_id=task, amount_micros=1, now=NOW)
            return "reserved"
        except SpendAdmissionRefused as error:
            return error.reason

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ["J01", "J02"]))
    assert sorted(results) == ["m4c3_call_limit", "reserved"]
    assert ledger.experiment_spend(EXPERIMENT)["calls"] == 12
