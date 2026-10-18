"""Durable experiment budget: cross-process, restart-safe, fail-closed.

The acceptance run's ¥10 cap only means something if it survives a restart, is
shared by every process that opens the same database, and refuses rather than
guesses. These controls exercise the storage directly (and the guard on top of
it) with real SQLite files and, where it matters, real separate processes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.infrastructure.sqlite.spend_ledger import (
    MICROS_PER_CNY,
    SpendCapExceeded,
    SpendLedger,
    SpendLedgerConflict,
    SpendLedgerError,
    SpendLedgerUnavailable,
    cny_to_micros,
)

NOW = "2026-10-19T00:00:00+00:00"
EXPERIMENT = "ia1a-samples-20261019"
PRICING = "pricing-v1"
CAP = 10 * MICROS_PER_CNY


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "runtime.db"
    RuntimeDatabase(path).initialize()
    return path


def _ledger(tmp_path: Path) -> SpendLedger:
    return SpendLedger(_database(tmp_path))


def _opened(tmp_path: Path, *, cap: int = CAP, pricing: str = PRICING) -> SpendLedger:
    ledger = _ledger(tmp_path)
    ledger.ensure_experiment(
        EXPERIMENT, cap_micros=cap, pricing_fingerprint=pricing, now=NOW
    )
    return ledger


def _reserve(ledger: SpendLedger, key: str, amount: int, *, model: str = "deepseek-flash"):
    return ledger.reserve(
        EXPERIMENT,
        request_key=key,
        amount_micros=amount,
        purpose="chat:deep_planner",
        model=model,
        identity="run=run1 op=op1 inv=1",
        now=NOW,
    )


# -- money ------------------------------------------------------------------
def test_money_is_integer_micros_and_rounds_up():
    assert MICROS_PER_CNY == 1_000_000
    assert cny_to_micros(10) == 10_000_000
    # Never round down: an under-counted reservation is an unenforced cap.
    assert cny_to_micros(0.0000001) == 1


# -- experiment identity ----------------------------------------------------
def test_the_experiment_cap_is_written_once_and_cannot_be_widened(tmp_path):
    ledger = _opened(tmp_path)
    again = ledger.ensure_experiment(
        EXPERIMENT, cap_micros=CAP, pricing_fingerprint=PRICING, now=NOW
    )
    assert again.cap_micros == CAP
    # A later process that configured a bigger cap is a configuration error.
    with pytest.raises(SpendLedgerConflict):
        ledger.ensure_experiment(
            EXPERIMENT, cap_micros=20 * MICROS_PER_CNY, pricing_fingerprint=PRICING, now=NOW
        )


def test_a_different_pricing_configuration_is_detected(tmp_path):
    ledger = _opened(tmp_path)
    with pytest.raises(SpendLedgerConflict):
        ledger.ensure_experiment(
            EXPERIMENT, cap_micros=CAP, pricing_fingerprint="pricing-v2", now=NOW
        )


def test_an_unknown_experiment_is_refused_rather_than_guessed(tmp_path):
    ledger = _ledger(tmp_path)
    with pytest.raises(SpendLedgerError) as excinfo:
        _reserve(ledger, "k1", 1000)
    assert "no durable budget" in str(excinfo.value)


# -- persistence and restart ------------------------------------------------
def test_reservations_survive_a_new_process_connection(tmp_path):
    ledger = _opened(tmp_path)
    _reserve(ledger, "k1", 3_000_000)
    # A restart: new object, new connection, same file.
    reopened = SpendLedger(_database(tmp_path))
    spend = reopened.experiment_spend(EXPERIMENT)
    assert spend["reserved_micros"] == 3_000_000
    assert spend["remaining_micros"] == CAP - 3_000_000
    assert spend["calls"] == 1


def test_a_crash_after_reserving_does_not_return_the_budget(tmp_path):
    ledger = _opened(tmp_path)
    _reserve(ledger, "k1", 4_000_000)
    del ledger  # the process dies before the request is even sent
    spend = _ledger(tmp_path).experiment_spend(EXPERIMENT)
    assert spend["reserved_micros"] == 4_000_000


# -- idempotency ------------------------------------------------------------
def test_the_same_key_can_never_be_reserved_twice(tmp_path):
    ledger = _opened(tmp_path)
    _reserve(ledger, "k1", 1_000_000)
    with pytest.raises(SpendLedgerConflict):
        _reserve(ledger, "k1", 1_000_000)
    assert ledger.experiment_spend(EXPERIMENT)["reserved_micros"] == 1_000_000


def test_the_same_key_with_a_different_request_is_refused(tmp_path):
    ledger = _opened(tmp_path)
    _reserve(ledger, "k1", 1_000_000, model="deepseek-flash")
    with pytest.raises(SpendLedgerConflict):
        _reserve(ledger, "k1", 2_000_000, model="deepseek-pro")
    with pytest.raises(SpendLedgerConflict):
        _reserve(ledger, "k1", 1_000_000, model="deepseek-pro")


def test_two_runs_using_the_same_task_never_collide():
    from src.llm_spend_guard import SpendIdentity, compose_request_key

    first = compose_request_key(
        purpose="chat:deep_planner",
        identity=SpendIdentity(run_id="run1", operation_id="op1", invocation="1"),
    )
    second = compose_request_key(
        purpose="chat:deep_planner",
        identity=SpendIdentity(run_id="run2", operation_id="op1", invocation="1"),
    )
    assert first != second
    # A retry of a request that was already sent must move the attempt.
    retry = compose_request_key(
        purpose="chat:deep_planner",
        attempt="2",
        identity=SpendIdentity(run_id="run1", operation_id="op1", invocation="1"),
    )
    assert retry != first


# -- boundary and cap -------------------------------------------------------
def test_the_cap_boundary_is_exact_and_inclusive(tmp_path):
    ledger = _opened(tmp_path, cap=5_000_000)
    _reserve(ledger, "k1", 5_000_000)
    with pytest.raises(SpendCapExceeded):
        _reserve(ledger, "k2", 1)
    assert ledger.experiment_spend(EXPERIMENT)["remaining_micros"] == 0


def test_each_experiment_keeps_its_own_budget(tmp_path):
    ledger = _opened(tmp_path)
    ledger.ensure_experiment(
        "other-experiment", cap_micros=2_000_000, pricing_fingerprint=PRICING, now=NOW
    )
    _reserve(ledger, "k1", 5_000_000)
    ledger.reserve(
        "other-experiment",
        request_key="k1",
        amount_micros=2_000_000,
        purpose="chat:x",
        model="m",
        identity="i",
        now=NOW,
    )
    assert ledger.experiment_spend(EXPERIMENT)["reserved_micros"] == 5_000_000
    assert ledger.experiment_spend("other-experiment")["reserved_micros"] == 2_000_000


# -- unavailability ---------------------------------------------------------
def test_a_missing_ledger_schema_is_refused(tmp_path):
    plain = tmp_path / "plain.db"
    import sqlite3

    sqlite3.connect(plain).close()  # exists, but has no ledger tables
    with pytest.raises(SpendLedgerUnavailable):
        SpendLedger(plain).ensure_experiment(
            EXPERIMENT, cap_micros=CAP, pricing_fingerprint=PRICING, now=NOW
        )


# -- cross-process ----------------------------------------------------------
_CHILD = """
import os, sys
sys.path.insert(0, r"{root}")
from src.infrastructure.sqlite.spend_ledger import SpendCapExceeded, SpendLedger
ledger = SpendLedger(r"{db}")
try:
    ledger.reserve(
        r"{experiment}",
        request_key=sys.argv[1],
        amount_micros={amount},
        purpose="chat:deep_planner",
        model="m",
        identity="i",
        now="2026-10-19T00:00:00+00:00",
    )
except SpendCapExceeded:
    print("REFUSED")
else:
    print("RESERVED")
"""


def _run_child(root: Path, db: Path, key: str, amount: int) -> str:
    script = _CHILD.format(root=str(root), db=str(db), experiment=EXPERIMENT, amount=amount)
    env = {**os.environ, "PYTHONPATH": str(root)}
    result = subprocess.run(
        [sys.executable, "-c", script, key],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


def test_a_second_process_cannot_cross_a_boundary_the_first_used(tmp_path):
    """Cross-process persistence, run sequentially.

    The genuine *simultaneous* race is covered in
    `tests/test_spend_production_wiring.py`; this control keeps the simple
    cross-process property (a second process sees the first process's spend)
    deterministic.
    """

    root = Path(__file__).resolve().parents[1]
    ledger = _opened(tmp_path, cap=6_000_000)
    _reserve(ledger, "already", 2_000_000)  # 4_000_000 left, two 3_000_000 wants
    database = Path(ledger.database_path)
    first = _run_child(root, database, "child-a", 3_000_000)
    second = _run_child(root, database, "child-b", 3_000_000)
    outcomes = sorted([first, second])
    assert outcomes == ["REFUSED", "RESERVED"], outcomes
    spend = _ledger(tmp_path).experiment_spend(EXPERIMENT)
    assert spend["reserved_micros"] == 5_000_000
    assert spend["reserved_micros"] <= spend["cap_micros"]


def test_two_databases_are_not_one_budget(tmp_path):
    first = _opened(tmp_path / "one")
    second = _opened(tmp_path / "two")
    _reserve(first, "k1", 6_000_000)
    # Same experiment id, different file: neither can see the other's spend, so
    # the cap is only real when every process points at the same absolute path.
    assert first.experiment_spend(EXPERIMENT)["reserved_micros"] == 6_000_000
    assert second.experiment_spend(EXPERIMENT)["reserved_micros"] == 0
