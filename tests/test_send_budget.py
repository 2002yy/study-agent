"""Durable send budget: one transaction, no reset, no partial charge.

These lock the properties the Quality-0 preview depends on: the cap cannot be
widened by restarting, a refusal never leaves a partial charge, and two writers
racing for the last unit cannot both win.
"""

from __future__ import annotations

import subprocess
import sys
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
