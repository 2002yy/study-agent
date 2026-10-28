"""Durable send budget: one transaction, no reset, no partial charge.

These lock the properties the Quality-0 preview depends on: the cap cannot be
widened by restarting, a refusal never leaves a partial charge, and two writers
racing for the last unit cannot both win.
"""

from __future__ import annotations

import subprocess
import sys
import sqlite3
import threading
from pathlib import Path

import pytest

from src.application.send_budget import (
    SendBudget,
    SendBudgetConflict,
    SendBudgetExceeded,
    SendBudgetUnavailable,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def budget(tmp_path) -> SendBudget:
    instance = SendBudget(tmp_path / "sends.sqlite")
    instance.register(
        {
            "experiment:q0": 5,
            "arm:current": 3,
            "round:current:r1": 2,
        }
    )
    return instance


def test_each_scope_is_counted_independently(budget):
    budget.reserve("k1", ["experiment:q0", "arm:current", "round:current:r1"])

    assert budget.usage("experiment:q0") == 1
    assert budget.usage("arm:current") == 1
    assert budget.usage("round:current:r1") == 1
    assert budget.remaining("experiment:q0") == 4
    assert budget.remaining("round:current:r1") == 1


def test_a_refusal_charges_nothing_anywhere(budget):
    budget.reserve("k1", ["experiment:q0", "arm:current", "round:current:r1"])
    budget.reserve("k2", ["experiment:q0", "arm:current", "round:current:r1"])

    with pytest.raises(SendBudgetExceeded) as excinfo:
        budget.reserve("k3", ["experiment:q0", "arm:current", "round:current:r1"])

    assert excinfo.value.scope == "round:current:r1"
    # The narrower scope refused first, so the wider ones must be untouched.
    assert budget.usage("round:current:r1") == 2
    assert budget.usage("arm:current") == 2
    assert budget.usage("experiment:q0") == 2


def test_one_send_may_charge_the_attempts_it_covers(budget):
    budget.reserve("k1", ["experiment:q0"], units=2)

    assert budget.usage("experiment:q0") == 2
    budget.reserve("k2", ["experiment:q0"], units=3)
    assert budget.remaining("experiment:q0") == 0
    with pytest.raises(SendBudgetExceeded):
        budget.reserve("k3", ["experiment:q0"])


def test_reusing_a_send_key_is_refused(budget):
    budget.reserve("k1", ["experiment:q0"])

    with pytest.raises(SendBudgetConflict, match="already counted"):
        budget.reserve("k1", ["experiment:q0"])

    assert budget.usage("experiment:q0") == 1


def test_an_unknown_scope_is_refused_instead_of_invented(budget):
    with pytest.raises(SendBudgetUnavailable, match="no registered cap"):
        budget.reserve("k1", ["arm:candidate"])


def test_a_cap_cannot_be_widened_later(budget):
    budget.register({"experiment:q0": 5})  # idempotent

    with pytest.raises(SendBudgetConflict, match="refusing to change"):
        budget.register({"experiment:q0": 45})


def test_counts_survive_a_new_instance(tmp_path):
    path = tmp_path / "sends.sqlite"
    first = SendBudget(path)
    first.register({"experiment:q0": 45})
    first.reserve("k1", ["experiment:q0"])

    restarted = SendBudget(path)
    restarted.register({"experiment:q0": 45})
    assert restarted.usage("experiment:q0") == 1

    restarted.reserve("k2", ["experiment:q0"])
    assert first.usage("experiment:q0") == 2


def test_counts_survive_a_restart_in_another_process(tmp_path):
    path = tmp_path / "sends.sqlite"
    budget = SendBudget(path)
    budget.register({"experiment:q0": 2})

    script = (
        "import sys; sys.path.insert(0, r'%s');"
        "from src.application.send_budget import SendBudget;"
        "b = SendBudget(r'%s');"
        "b.reserve('child-1', ['experiment:q0'])"
        % (ROOT, path)
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr

    assert budget.usage("experiment:q0") == 1
    budget.reserve("parent-1", ["experiment:q0"])
    with pytest.raises(SendBudgetExceeded):
        budget.reserve("parent-2", ["experiment:q0"])


def test_two_writers_cannot_both_take_the_last_unit(tmp_path):
    path = tmp_path / "sends.sqlite"
    SendBudget(path).register({"experiment:q0": 1})
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def worker(name: str) -> None:
        writer = SendBudget(path)
        barrier.wait()
        try:
            writer.reserve(name, ["experiment:q0"])
            outcomes.append("reserved")
        except SendBudgetExceeded:
            outcomes.append("exhausted")

    threads = [
        threading.Thread(target=worker, args=(f"k{index}",)) for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["exhausted", "reserved"]
    assert SendBudget(path).usage("experiment:q0") == 1


def test_two_processes_cannot_both_take_the_last_unit(tmp_path):
    path = tmp_path / "sends.sqlite"
    SendBudget(path).register({"experiment:q0": 1})
    driver = tmp_path / "reserve_once.py"
    driver.write_text(
        "import sys\n"
        f"sys.path.insert(0, r'{ROOT}')\n"
        "from src.application.send_budget import SendBudget, SendBudgetExceeded\n"
        "budget = SendBudget(sys.argv[1])\n"
        "try:\n"
        "    budget.reserve(sys.argv[2], ['experiment:q0'])\n"
        "    print('reserved')\n"
        "except SendBudgetExceeded:\n"
        "    print('exhausted')\n",
        encoding="utf-8",
    )

    processes = [
        subprocess.Popen(
            [sys.executable, str(driver), str(path), f"k{index}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(2)
    ]
    outputs = [process.communicate()[0].strip() for process in processes]

    assert sorted(outputs) == ["exhausted", "reserved"]
    assert SendBudget(path).usage("experiment:q0") == 1


def test_a_directory_that_is_not_a_database_is_refused(tmp_path):
    path = tmp_path / "sends.sqlite"
    path.write_bytes(b"not a database")

    with pytest.raises(SendBudgetUnavailable):
        SendBudget(path)


def _tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }


def test_a_database_owned_by_something_else_is_refused_and_left_alone(tmp_path):
    """A path is not a promise: never add send tables to the runtime database."""

    path = tmp_path / "runtime.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO conversations VALUES ('c1')")

    with pytest.raises(SendBudgetUnavailable, match="does not own"):
        SendBudget(path)

    assert _tables(path) == {"conversations"}


def test_a_partial_ledger_is_not_adopted(tmp_path):
    """Half a ledger reads as an empty history, which is worse than a refusal."""

    path = tmp_path / "sends.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE send_budget_limits ("
            "scope TEXT PRIMARY KEY, cap INTEGER NOT NULL, created_at TEXT NOT NULL)"
        )

    with pytest.raises(SendBudgetUnavailable, match="partial send budget"):
        SendBudget(path)

    assert _tables(path) == {"send_budget_limits"}


def test_a_table_with_the_right_name_but_the_wrong_shape_is_refused(tmp_path):
    """Adopting a lookalike schema would produce confident, wrong counts."""

    path = tmp_path / "sends.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE send_budget_limits ("
            "scope TEXT PRIMARY KEY, cap INTEGER NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE send_budget_reservations ("
            "scope TEXT NOT NULL, request_key TEXT NOT NULL, reserved_at TEXT NOT NULL, "
            "PRIMARY KEY (scope, request_key))"
        )

    with pytest.raises(SendBudgetUnavailable, match="missing"):
        SendBudget(path)


def test_a_lookalike_schema_without_the_composite_key_is_refused(tmp_path):
    """Same table and column names, none of the rules that make counts mean anything."""

    path = tmp_path / "sends.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE send_budget_limits ("
            "scope TEXT, cap INTEGER, created_at TEXT)"
        )
        connection.execute(
            "CREATE TABLE send_budget_reservations ("
            "scope TEXT, request_key TEXT, units INTEGER, reserved_at TEXT)"
        )

    with pytest.raises(SendBudgetUnavailable, match="primary key"):
        SendBudget(path)


def test_a_lookalike_schema_without_the_positive_checks_is_refused(tmp_path):
    """A CHECK constraint is invisible to every pragma, so identity needs the DDL."""

    path = tmp_path / "sends.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE send_budget_limits ("
            "scope TEXT PRIMARY KEY, cap INTEGER, created_at TEXT)"
        )
        connection.execute(
            "CREATE TABLE send_budget_reservations ("
            "scope TEXT, request_key TEXT, units INTEGER, reserved_at TEXT, "
            "PRIMARY KEY (scope, request_key))"
        )

    with pytest.raises(SendBudgetUnavailable, match="constraints differ"):
        SendBudget(path)


def test_the_database_itself_refuses_a_negative_cap_and_a_duplicate_count(tmp_path):
    """The verified constraints have to be real, not just present in our DDL text."""

    path = tmp_path / "sends.sqlite"
    budget = SendBudget(path)
    budget.register({"experiment:q0": 5})
    budget.reserve("k1", ["experiment:q0"])

    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO send_budget_limits(scope, cap, created_at) "
                "VALUES ('experiment:negative', -1, 'now')"
            )
    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO send_budget_reservations"
                "(scope, request_key, units, reserved_at) "
                "VALUES ('experiment:q0', 'k1', 1, 'now')"
            )


def test_reopening_a_ledger_this_class_created_is_allowed(tmp_path):
    """Ownership must not become so strict that a restart cannot reopen."""

    path = tmp_path / "sends.sqlite"
    first = SendBudget(path)
    first.register({"experiment:q0": 2})
    first.reserve("k1", ["experiment:q0"])

    reopened = SendBudget(path)
    reopened.register({"experiment:q0": 2})
    assert reopened.usage("experiment:q0") == 1
    assert _tables(path) == {"send_budget_limits", "send_budget_reservations"}
