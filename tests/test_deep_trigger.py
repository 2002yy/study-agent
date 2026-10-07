"""Deep-3T: durable discovery and the non-blocking trigger runner.

The controls that matter: the database facts are the queue, so discovery must recover both a
completed Standard artifact with no Deep terminal and a pending Deep terminal; the worker must
be idempotent, scan immediately on start, and never run work on the caller's thread; and no
callback failure may leave a durable mark or stop the worker.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from src.application.deep_trigger import (
    ARM_BATCH,
    PENDING_BATCH,
    SCAN_INTERVAL_SECONDS,
    DeepTriggerRunner,
)
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.deep_trigger_repository import (
    ARM,
    PENDING,
    DeepTriggerItem,
    DeepTriggerRepository,
)

THREAD = "thread-1"


def _continuation(*, gaps=("release_date",), stop_reason="ready_for_binding", authority=False):
    return {
        "schema_version": "standard-auto-continuation-v1",
        "child_run_id": "standard-child",
        "source_run_id": "source-run",
        "handoff_sha256": "h" * 64,
        "publication_authority": authority,
        "result": {
            "stop_reason": stop_reason,
            "unresolved_gaps": list(gaps),
            "publication_authority": False,
        },
    }


def _deep_terminal(*, status="pending"):
    return {
        "schema_version": "standard-deep-terminal-v1",
        "state": "ESCALATE_DEEP",
        "reason": "unresolved_after_standard",
        "dispatch_status": status,
        "owner": {"thread_id": THREAD, "turn_id": "turn-x", "run_id": "source-run"},
        "handoff": {"payload_sha256": "h" * 64},
        "child_run_id": "deep-child",
    }


def _arm_snapshot(**overrides):
    snapshot = {
        "lookup_terminal": {"state": "ESCALATE_STANDARD", "dispatch_status": "completed"},
        "standard_continuation": _continuation(),
    }
    snapshot.update(overrides)
    return snapshot


@pytest.fixture
def db(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.sqlite")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO chat_threads (id, status, created_at, updated_at) VALUES (?,?,?,?)",
            (THREAD, "active", "2026-10-07T00:00:00+00:00", "2026-10-07T00:00:00+00:00"),
        )
    return database


def add_turn(database, turn_id, snapshot, *, status="completed", thread_id=THREAD):
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO chat_turns
              (id, thread_id, user_message, assistant_message, status, rag_snapshot,
               created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                turn_id,
                thread_id,
                "q",
                "a",
                status,
                json.dumps(snapshot),
                "2026-10-07T00:00:00+00:00",
                "2026-10-07T00:00:00+00:00",
            ),
        )


def kinds(items):
    return [item.kind for item in items]


def ids(items):
    return [item.parent_turn_id for item in items]


# --- T1 / T2 / T3 / T4: ARM discovery ---------------------------------------------


def test_t1_a_valid_arm_parent_is_discovered(db):
    add_turn(db, "turn-1", _arm_snapshot())
    items = DeepTriggerRepository(db).discover()
    assert kinds(items) == [ARM]
    assert ids(items) == ["turn-1"]
    assert items[0].thread_id == THREAD


def test_t2_no_gap_is_not_discovered(db):
    add_turn(db, "turn-1", _arm_snapshot(standard_continuation=_continuation(gaps=())))
    assert DeepTriggerRepository(db).discover() == ()


def test_t3_a_non_upgrade_stop_is_not_discovered(db):
    for stop in ("cancelled", "planner_invalid", "planner_failed", "result_unknown"):
        add_turn(
            db,
            f"turn-{stop}",
            _arm_snapshot(standard_continuation=_continuation(stop_reason=stop)),
        )
    assert DeepTriggerRepository(db).discover() == ()


def test_t4_an_unknown_stop_with_a_gap_is_discovered(db):
    add_turn(db, "turn-1", _arm_snapshot(standard_continuation=_continuation(stop_reason="odd")))
    items = DeepTriggerRepository(db).discover()
    assert kinds(items) == [ARM]


def test_a_published_continuation_is_not_discovered(db):
    add_turn(db, "turn-1", _arm_snapshot(standard_continuation=_continuation(authority=True)))
    assert DeepTriggerRepository(db).discover() == ()


def test_an_incomplete_standard_terminal_is_not_discovered(db):
    snapshot = _arm_snapshot(
        lookup_terminal={"state": "ESCALATE_STANDARD", "dispatch_status": "pending"}
    )
    add_turn(db, "turn-1", snapshot)
    assert DeepTriggerRepository(db).discover() == ()


def test_a_turn_with_a_deep_terminal_is_not_an_arm_candidate(db):
    add_turn(db, "turn-1", _arm_snapshot(deep_terminal=_deep_terminal()))
    items = DeepTriggerRepository(db).discover()
    assert kinds(items) == [PENDING]


# --- T5 / T6 / T7: PENDING discovery ----------------------------------------------


def test_t5_a_pending_deep_terminal_is_discovered(db):
    add_turn(db, "turn-1", {"deep_terminal": _deep_terminal()})
    items = DeepTriggerRepository(db).discover()
    assert kinds(items) == [PENDING]
    assert ids(items) == ["turn-1"]


def test_t6_t7_completed_and_blocked_terminals_are_not_discovered(db):
    add_turn(db, "turn-c", {"deep_terminal": _deep_terminal(status="completed")})
    add_turn(db, "turn-b", {"deep_terminal": _deep_terminal(status="blocked")})
    assert DeepTriggerRepository(db).discover() == ()


def test_a_malformed_terminal_is_not_discovered_and_not_repaired(db):
    add_turn(db, "turn-1", {"deep_terminal": "garbage"})
    add_turn(db, "turn-2", {"deep_terminal": {"schema_version": "wrong"}})
    assert DeepTriggerRepository(db).discover() == ()


def test_a_non_completed_turn_is_not_discovered(db):
    add_turn(db, "turn-1", _arm_snapshot(), status="running")
    assert DeepTriggerRepository(db).discover() == ()


def test_arm_candidates_come_before_pending(db):
    add_turn(db, "turn-arm", _arm_snapshot())
    add_turn(db, "turn-pending", {"deep_terminal": _deep_terminal()})
    assert kinds(DeepTriggerRepository(db).discover()) == [ARM, PENDING]


# --- T20: bounded batches ----------------------------------------------------------


def test_t20_batches_are_respected(db):
    for n in range(5):
        add_turn(db, f"arm-{n}", _arm_snapshot())
    for n in range(7):
        add_turn(db, f"pending-{n}", {"deep_terminal": _deep_terminal()})
    items = DeepTriggerRepository(db).discover(arm_limit=2, pending_limit=3)
    assert kinds(items) == [ARM, ARM, PENDING, PENDING, PENDING]


# --- runner -----------------------------------------------------------------------


def _runner(db, **kwargs):
    return DeepTriggerRunner(DeepTriggerRepository(db), interval_seconds=0.05, **kwargs)


def test_t9_start_scans_immediately_without_waiting_the_interval(db):
    add_turn(db, "turn-1", {"deep_terminal": _deep_terminal()})
    seen: list[str] = []
    done = threading.Event()

    def consume(parent_turn_id, thread_id):
        seen.append(parent_turn_id)
        done.set()

    runner = _runner(db, consume=consume)
    runner.start()
    try:
        assert done.wait(timeout=5.0), "start() must scan before the first interval"
        assert seen == ["turn-1"]
    finally:
        runner.stop()


def test_t8_start_twice_creates_one_worker(db):
    runner = _runner(db)
    runner.start()
    try:
        first = runner._thread
        runner.start()
        assert runner._thread is first
        assert sum(1 for t in threading.enumerate() if t.name == "deep-trigger") == 1
    finally:
        runner.stop()


def test_t10_wake_does_not_run_the_callback_inline(db):
    add_turn(db, "turn-1", {"deep_terminal": _deep_terminal()})
    seen: list[str] = []
    runner = _runner(db, consume=lambda p, t: seen.append(p))
    # Never started: wake() must only signal, so no work happens on this thread.
    runner.wake()
    assert seen == []


def test_t11_wake_triggers_a_scan_promptly(db):
    seen: list[str] = []
    done = threading.Event()

    def consume(parent_turn_id, thread_id):
        seen.append(parent_turn_id)
        done.set()

    runner = DeepTriggerRunner(
        DeepTriggerRepository(db), interval_seconds=30.0, consume=consume
    )
    runner.start()
    try:
        time.sleep(0.2)
        add_turn(db, "turn-1", {"deep_terminal": _deep_terminal()})
        runner.wake()
        assert done.wait(timeout=5.0), "wake() must not wait for the next interval"
        assert seen == ["turn-1"]
    finally:
        runner.stop()


def test_t12_a_prepared_arm_is_consumed_in_the_same_scan(db):
    add_turn(db, "turn-1", _arm_snapshot())
    order: list[str] = []

    def arm(parent_turn_id, thread_id):
        order.append("arm")
        # The handoff the real callback would persist.
        with db.connect() as connection:
            connection.execute(
                "UPDATE chat_turns SET rag_snapshot = ? WHERE id = ?",
                (json.dumps({"deep_terminal": _deep_terminal()}), parent_turn_id),
            )

        class Outcome:
            status = "prepared"

        return Outcome()

    def consume(parent_turn_id, thread_id):
        order.append("consume")

    runner = _runner(db, arm=arm, consume=consume)
    runner.scan_once()
    assert order == ["arm", "consume"]


def test_t13_t14_a_non_prepared_arm_does_not_consume(db):
    add_turn(db, "turn-1", _arm_snapshot())
    consumed: list[str] = []

    class Outcome:
        def __init__(self, status):
            self.status = status

    for status in ("not_requested", "blocked"):
        runner = _runner(
            db,
            arm=lambda p, t, s=status: Outcome(s),
            consume=lambda p, t: consumed.append(p),
        )
        runner.scan_once()
    assert consumed == []


def test_t17_a_raising_callback_does_not_stop_the_runner(db):
    add_turn(db, "turn-1", {"deep_terminal": _deep_terminal()})
    calls: list[str] = []

    def consume(parent_turn_id, thread_id):
        calls.append(parent_turn_id)
        raise RuntimeError("boom")

    runner = _runner(db, consume=consume)
    assert runner.scan_once() == 1
    assert runner.scan_once() == 1
    assert len(calls) == 2
    # Durable state is untouched: the item is still discoverable.
    assert kinds(DeepTriggerRepository(db).discover()) == [PENDING]


def test_t15_a_deferred_item_is_rediscovered(db):
    add_turn(db, "turn-1", {"deep_terminal": _deep_terminal()})
    runner = _runner(db, consume=lambda p, t: None)
    assert runner.scan_once() == 1
    assert ids(DeepTriggerRepository(db).discover()) == ["turn-1"]


def test_t16_a_completed_item_is_not_rediscovered(db):
    add_turn(db, "turn-1", {"deep_terminal": _deep_terminal()})
    runner = _runner(db, consume=lambda p, t: None)
    runner.scan_once()
    with db.connect() as connection:
        connection.execute(
            "UPDATE chat_turns SET rag_snapshot = ? WHERE id = ?",
            (json.dumps({"deep_terminal": _deep_terminal(status="completed")}), "turn-1"),
        )
    assert DeepTriggerRepository(db).discover() == ()


def test_t18_a_restart_rediscovers_the_same_item(db):
    add_turn(db, "turn-1", {"deep_terminal": _deep_terminal()})
    first = _runner(db, consume=lambda p, t: None)
    first.scan_once()
    # A fresh runner stands in for a process restart: durable truth is the only input.
    second = _runner(db, consume=lambda p, t: None)
    assert ids(DeepTriggerRepository(db).discover()) == ["turn-1"]
    assert second.scan_once() == 1


def test_t19_stop_does_not_mutate_durable_state(db):
    add_turn(db, "turn-1", {"deep_terminal": _deep_terminal()})
    before = None
    with db.connect() as connection:
        before = connection.execute(
            "SELECT rag_snapshot FROM chat_turns WHERE id = ?", ("turn-1",)
        ).fetchone()["rag_snapshot"]
    runner = _runner(db, consume=lambda p, t: time.sleep(0.3))
    runner.start()
    time.sleep(0.05)
    runner.stop()
    with db.connect() as connection:
        after = connection.execute(
            "SELECT rag_snapshot FROM chat_turns WHERE id = ?", ("turn-1",)
        ).fetchone()["rag_snapshot"]
    assert after == before


def test_t31_shutdown_is_bounded_even_mid_call(db):
    started = threading.Event()

    def consume(parent_turn_id, thread_id):
        started.set()
        time.sleep(5.0)

    add_turn(db, "turn-1", {"deep_terminal": _deep_terminal()})
    runner = DeepTriggerRunner(
        DeepTriggerRepository(db), interval_seconds=30.0, consume=consume
    )
    runner.start()
    assert started.wait(timeout=5.0)
    began = time.monotonic()
    runner.stop()
    assert time.monotonic() - began < 2.0, "stop() must not wait out a long Deep call"


def test_t21_two_runners_do_not_write_anything(db):
    add_turn(db, "turn-1", {"deep_terminal": _deep_terminal()})
    with db.connect() as connection:
        before = connection.execute(
            "SELECT rag_snapshot FROM chat_turns WHERE id = ?", ("turn-1",)
        ).fetchone()["rag_snapshot"]
    first = _runner(db, consume=lambda p, t: None)
    second = _runner(db, consume=lambda p, t: None)
    first.scan_once()
    second.scan_once()
    with db.connect() as connection:
        after = connection.execute(
            "SELECT rag_snapshot FROM chat_turns WHERE id = ?", ("turn-1",)
        ).fetchone()["rag_snapshot"]
    assert after == before


def test_t22_no_queue_table_exists(db):
    with db.connect() as connection:
        names = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert not [name for name in names if name.startswith("deep_")]


def test_the_frozen_v1_constants_are_unchanged():
    assert SCAN_INTERVAL_SECONDS == 15.0
    assert ARM_BATCH == 8
    assert PENDING_BATCH == 16


def test_a_runner_without_callbacks_is_inert(db):
    add_turn(db, "turn-1", {"deep_terminal": _deep_terminal()})
    runner = _runner(db)
    assert runner.scan_once() == 1
    assert runner.running is False


def test_discovery_items_are_immutable():
    item = DeepTriggerItem(ARM, "turn-1", THREAD)
    with pytest.raises(Exception):
        item.kind = PENDING  # type: ignore[misc]


def test_periodic_rescan_recovers_without_a_wake(db):
    """A lost wake must be harmless: the interval alone has to recover the work."""

    seen: list[str] = []
    done = threading.Event()

    def consume(parent_turn_id, thread_id):
        seen.append(parent_turn_id)
        done.set()

    runner = DeepTriggerRunner(
        DeepTriggerRepository(db), interval_seconds=0.05, consume=consume
    )
    runner.start()
    try:
        time.sleep(0.3)  # the startup scan runs with nothing to do
        add_turn(db, "turn-1", {"deep_terminal": _deep_terminal()})
        assert done.wait(timeout=5.0), "periodic rescan must recover work with no wake"
        assert seen == ["turn-1"]
    finally:
        runner.stop()
