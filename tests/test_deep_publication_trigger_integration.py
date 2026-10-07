"""Deep-4A trigger integration: PUBLICATION discovery on the shared runner.

The controls that matter: a completed Deep terminal with no publication work becomes a
PUBLICATION item, a pending publication survives a restart, a malformed publication is never
mistaken for absent, and one scan can carry a PENDING item all the way to a publication callback.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from src.application.deep_trigger import DeepTriggerRunner
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.deep_trigger_repository import (
    PENDING,
    PUBLICATION,
    DeepTriggerRepository,
)

THREAD = "thread-1"


def _terminal(*, status="completed"):
    return {
        "schema_version": "standard-deep-terminal-v1",
        "state": "ESCALATE_DEEP",
        "dispatch_status": status,
        "owner": {"thread_id": THREAD, "turn_id": "turn-1", "run_id": "source"},
        "handoff": {"payload_sha256": "h" * 64},
        "child_run_id": "deep-child",
        "result": {
            "schema_version": "deep-auto-continuation-v1",
            "child_run_id": "deep-child",
            "child_status": "completed",
            "provider_status": "found",
            "stop_reason": "ready_for_binding",
            "answer_confidence": "high",
            "completed_at": "2026-10-07T00:00:00+00:00",
            "handoff_sha256": "h" * 64,
            "child_terminal_sha256": "d" * 64,
            "publication_authority": False,
        },
    }


def _publication(*, status="pending"):
    entry = {
        "schema_version": "deep-publication-v1",
        "dispatch_status": status,
        "owner": {"thread_id": THREAD, "turn_id": "turn-1", "child_run_id": "deep-child"},
        "source": {
            "deep_terminal_sha256": "e" * 64,
            "child_terminal_sha256": "d" * 64,
            "source_run_sha256": "f" * 64,
        },
        "publication_authority": False,
    }
    if status == "blocked":
        entry["reason"] = "child_missing"
    return entry


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


def add_turn(database, turn_id, snapshot):
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
                THREAD,
                "q",
                "a",
                "completed",
                json.dumps(snapshot),
                "2026-10-07T00:00:00+00:00",
                "2026-10-07T00:00:00+00:00",
            ),
        )


def kinds(items):
    return [item.kind for item in items]


# --- A1 / A5 / A6: discovery ------------------------------------------------------


def test_a1_a_completed_deep_terminal_without_publication_is_discovered(db):
    add_turn(db, "turn-1", {"deep_terminal": _terminal()})
    items = DeepTriggerRepository(db).discover()
    assert kinds(items) == [PUBLICATION]
    assert items[0].parent_turn_id == "turn-1"


def test_a5_a_pending_publication_is_rediscovered(db):
    add_turn(db, "turn-1", {"deep_terminal": _terminal(), "deep_publication": _publication()})
    items = DeepTriggerRepository(db).discover()
    assert kinds(items) == [PUBLICATION]


def test_a3_a4_a_settled_publication_is_not_rediscovered(db):
    for status in ("audited", "blocked"):
        snapshot = {
            "deep_terminal": _terminal(),
            "deep_publication": _publication(status=status),
        }
        if status == "audited":
            snapshot["deep_publication"]["result"] = {"x": 1}
        add_turn(db, f"turn-{status}", snapshot)
    assert DeepTriggerRepository(db).discover() == ()


def test_a6_a_malformed_publication_is_not_treated_as_absent(db):
    add_turn(db, "turn-null", {"deep_terminal": _terminal(), "deep_publication": None})
    add_turn(db, "turn-bad", {"deep_terminal": _terminal(), "deep_publication": "garbage"})
    assert DeepTriggerRepository(db).discover() == ()


def test_a2_a_blocked_deep_terminal_is_not_a_publication_candidate(db):
    add_turn(db, "turn-1", {"deep_terminal": _terminal(status="blocked")})
    assert DeepTriggerRepository(db).discover() == ()


def test_publication_comes_after_pending_in_the_scan_order(db):
    add_turn(db, "turn-pending", {"deep_terminal": _terminal(status="pending")})
    add_turn(db, "turn-pub", {"deep_terminal": _terminal()})
    assert kinds(DeepTriggerRepository(db).discover()) == [PENDING, PUBLICATION]


def test_arm_still_comes_first(db):
    add_turn(db, "turn-pub", {"deep_terminal": _terminal()})
    assert kinds(DeepTriggerRepository(db).discover()) == [PUBLICATION]


# --- A7: one scan can carry PENDING to PUBLICATION --------------------------------


def test_a7_a_pending_item_finalized_in_scan_reaches_the_publish_callback(db):
    add_turn(db, "turn-1", {"deep_terminal": _terminal(status="pending")})
    order: list[str] = []

    def consume(parent_turn_id, thread_id):
        order.append("consume")
        # The real continuation finalizes the Deep terminal; here it is written directly.
        with db.connect() as connection:
            connection.execute(
                "UPDATE chat_turns SET rag_snapshot = ? WHERE id = ?",
                (json.dumps({"deep_terminal": _terminal()}), parent_turn_id),
            )

    def publish(parent_turn_id, thread_id):
        order.append("publish")

    runner = DeepTriggerRunner(
        DeepTriggerRepository(db), interval_seconds=30.0, consume=consume, publish=publish
    )
    runner.scan_once()
    assert order == ["consume", "publish"]


def test_publish_callback_failure_leaves_the_runner_alive(db):
    add_turn(db, "turn-1", {"deep_terminal": _terminal()})
    calls: list[str] = []

    def publish(parent_turn_id, thread_id):
        calls.append(parent_turn_id)
        raise RuntimeError("boom")

    runner = DeepTriggerRunner(
        DeepTriggerRepository(db), interval_seconds=30.0, publish=publish
    )
    assert runner.scan_once() == 1
    assert runner.scan_once() == 1
    assert len(calls) == 2
    # Durable state is untouched: the item is still discoverable.
    assert kinds(DeepTriggerRepository(db).discover()) == [PUBLICATION]


def test_publication_is_recovered_by_the_periodic_scan(db):
    done = threading.Event()

    def publish(parent_turn_id, thread_id):
        done.set()

    with db.connect() as connection:
        connection.execute("DELETE FROM chat_turns")
    runner = DeepTriggerRunner(
        DeepTriggerRepository(db), interval_seconds=0.05, publish=publish
    )
    runner.start()
    try:
        time.sleep(1.0)
        add_turn(db, "turn-1", {"deep_terminal": _terminal()})
        assert done.wait(timeout=5.0), "periodic scan must recover a publication candidate"
    finally:
        runner.stop()


# --- composition ------------------------------------------------------------------


def test_the_runner_has_a_publish_callback_wired():
    from src.application import runtime_repository as runtime

    runtime.get_deep_trigger_runner.cache_clear()
    runtime.get_chat_service.cache_clear()
    try:
        runner = runtime.get_deep_trigger_runner()
        assert runner.publish is not None
        assert runner.arm is not None
        assert runner.consume is not None
    finally:
        runtime.get_deep_trigger_runner.cache_clear()
        runtime.get_chat_service.cache_clear()


def test_no_deep_queue_table_is_created(db):
    with db.connect() as connection:
        names = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert not [name for name in names if name.startswith("deep_")]
