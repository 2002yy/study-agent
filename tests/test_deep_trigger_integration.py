"""Deep-3 integration: the response path signals Deep, and Deep never blocks it.

The controls that matter: the chat wrapper only wakes the runner, the request returns without
waiting for a slow Deep consumer, the production composition reuses the existing singletons, and
a failing callback cannot turn a completed answer into an error.
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from src.application.deep_chat_service import DeepContinuationChatService
from src.application.deep_trigger import DeepTriggerRunner
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.deep_trigger_repository import DeepTriggerRepository


def _terminal_snapshot(thread_id="thread-1"):
    return {
        "deep_terminal": {
            "schema_version": "standard-deep-terminal-v1",
            "state": "ESCALATE_DEEP",
            "dispatch_status": "pending",
            "owner": {"thread_id": thread_id, "turn_id": "turn-1", "run_id": "source"},
            "handoff": {"payload_sha256": "h" * 64},
            "child_run_id": "deep-child",
        }
    }


@pytest.fixture
def db(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.sqlite")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO chat_threads (id, status, created_at, updated_at) VALUES (?,?,?,?)",
            ("thread-1", "active", "2026-10-07T00:00:00+00:00", "2026-10-07T00:00:00+00:00"),
        )
        connection.execute(
            """
            INSERT INTO chat_turns
              (id, thread_id, user_message, assistant_message, status, rag_snapshot,
               created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                "turn-1",
                "thread-1",
                "q",
                "the safe answer",
                "completed",
                json.dumps(_terminal_snapshot()),
                "2026-10-07T00:00:00+00:00",
                "2026-10-07T00:00:00+00:00",
            ),
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
                "thread-1",
                "q",
                "a",
                "completed",
                json.dumps(snapshot),
                "2026-10-07T00:00:00+00:00",
                "2026-10-07T00:00:00+00:00",
            ),
        )


# --- F31: the chat wrapper only wakes ---------------------------------------------


def test_f31_complete_turn_only_wakes_the_runner():
    from src.application import policy_chat_service as pcs

    completed = SimpleNamespace(id="turn-1", thread_id="thread-1", assistant_message="safe")
    calls: list[str] = []

    class Runner:
        def wake(self):
            calls.append("wake")

        def scan_once(self):
            calls.append("scan_once")

    class NeverDeep:
        def continue_pending(self, **_kwargs):
            raise AssertionError("the response path must not run Deep")

        def execute(self, **_kwargs):
            raise AssertionError("the response path must not run Deep")

    original = pcs.ExternalDataPolicyChatService.complete_turn
    pcs.ExternalDataPolicyChatService.complete_turn = lambda self, p, s: completed
    try:
        chat = DeepContinuationChatService.__new__(DeepContinuationChatService)
        chat._standard_continuation = NeverDeep()
        chat._deep_runner = Runner()
        result = chat.complete_turn(prepared=None, suffix="")
    finally:
        pcs.ExternalDataPolicyChatService.complete_turn = original

    assert result is completed
    assert calls == ["wake"]
    assert "scan_once" not in calls, "the response path must not run Deep inline"


def test_a_missing_runner_is_a_no_op():
    from src.application import policy_chat_service as pcs

    completed = SimpleNamespace(id="turn-1", thread_id="thread-1", assistant_message="safe")
    original = pcs.ExternalDataPolicyChatService.complete_turn
    pcs.ExternalDataPolicyChatService.complete_turn = lambda self, p, s: completed
    try:
        chat = DeepContinuationChatService.__new__(DeepContinuationChatService)
        chat._standard_continuation = None
        chat._deep_runner = None
        assert chat.complete_turn(prepared=None, suffix="") is completed
    finally:
        pcs.ExternalDataPolicyChatService.complete_turn = original


# --- F36: a failing callback cannot fail the answer --------------------------------


def test_f36_a_failing_wake_does_not_fail_the_answer():
    from src.application import policy_chat_service as pcs

    completed = SimpleNamespace(id="turn-1", thread_id="thread-1", assistant_message="safe")

    class Exploding:
        def wake(self):
            raise RuntimeError("runner is broken")

    original = pcs.ExternalDataPolicyChatService.complete_turn
    pcs.ExternalDataPolicyChatService.complete_turn = lambda self, p, s: completed
    try:
        chat = DeepContinuationChatService.__new__(DeepContinuationChatService)
        chat._standard_continuation = None
        chat._deep_runner = Exploding()
        assert chat.complete_turn(prepared=None, suffix="") is completed
    finally:
        pcs.ExternalDataPolicyChatService.complete_turn = original


# --- F32: the request never waits for a slow Deep consumer -------------------------


def test_f32_a_slow_consumer_does_not_block_the_request(db):
    started = threading.Event()

    def consume(parent_turn_id, thread_id):
        started.set()
        time.sleep(2.0)

    runner = DeepTriggerRunner(
        DeepTriggerRepository(db), interval_seconds=30.0, consume=consume
    )
    runner.start()
    try:
        assert started.wait(timeout=5.0)
        began = time.monotonic()
        runner.wake()
        elapsed = time.monotonic() - began
        assert elapsed < 0.5, "wake() must return immediately even while a consumer runs"
    finally:
        runner.stop()


# --- F33: a lost wake is recovered by the periodic scan ---------------------------


def test_f33_a_lost_wake_is_recovered_by_the_periodic_scan(db):
    done = threading.Event()

    def consume(parent_turn_id, thread_id):
        done.set()

    # Start from an empty queue: the fixture's own turn would otherwise be found by the
    # startup scan, and this control must isolate periodic recovery.
    with db.connect() as connection:
        connection.execute("DELETE FROM chat_turns WHERE id = ?", ("turn-1",))
    runner = DeepTriggerRunner(
        DeepTriggerRepository(db), interval_seconds=0.05, consume=consume
    )
    runner.start()
    try:
        time.sleep(1.0)  # let the startup scan finish with nothing to do
        add_turn(db, "turn-2", _terminal_snapshot())
        # No wake at all: only periodic recovery can find it.
        assert done.wait(timeout=5.0), "the periodic scan must recover the durable work"
    finally:
        runner.stop()


# --- composition ------------------------------------------------------------------


def test_the_production_composition_reuses_the_existing_singletons(monkeypatch):
    from src.application import runtime_repository as runtime

    runtime.get_chat_service.cache_clear()
    runtime.get_deep_trigger_runner.cache_clear()
    try:
        service = runtime.get_chat_service()
        assert isinstance(service, DeepContinuationChatService)
        runner = service._deep_runner
        assert runner is runtime.get_deep_trigger_runner()
        # One repository and one dispatcher, shared with everything else.
        assert runner.repository.database is runtime.get_runtime_repository().database
        assert (
            runtime.get_web_lookup_service() is runtime.get_web_lookup_service()
        )
    finally:
        runtime.get_chat_service.cache_clear()
        runtime.get_deep_trigger_runner.cache_clear()


def test_the_runner_callbacks_adapt_keyword_only_services(monkeypatch, db):
    """The services are keyword-only, so the composition must adapt rather than pass them raw."""

    from src.application import runtime_repository as runtime

    seen: dict[str, dict] = {}

    class Handoff:
        def __init__(self, *_a, **_k):
            pass

        def prepare(self, *, parent_turn_id, thread_id):
            seen["arm"] = {"parent": parent_turn_id, "thread": thread_id}
            return SimpleNamespace(status="not_requested")

    class Continuation:
        def __init__(self, *_a, **_k):
            pass

        def continue_pending(self, *, parent_turn_id, thread_id):
            seen["consume"] = {"parent": parent_turn_id, "thread": thread_id}
            return SimpleNamespace(status="completed")

    monkeypatch.setattr("src.application.deep_handoff.DeepHandoffService", Handoff)
    monkeypatch.setattr("src.application.deep_continuation.DeepContinuationService", Continuation)

    runtime.get_deep_trigger_runner.cache_clear()
    try:
        runner = runtime.get_deep_trigger_runner()
        runner.arm("turn-1", "thread-1")
        runner.consume("turn-1", "thread-1")
    finally:
        runtime.get_deep_trigger_runner.cache_clear()

    assert seen["arm"] == {"parent": "turn-1", "thread": "thread-1"}
    assert seen["consume"] == {"parent": "turn-1", "thread": "thread-1"}


# --- F39 / F40: no migration, no publication --------------------------------------


def test_f39_no_deep_migration_or_new_table(db):
    with db.connect() as connection:
        names = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert not [name for name in names if name.startswith("deep_")]


def test_f40_the_deep_layer_never_regenerates_the_answer():
    import io
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    for name in (
        "src/application/deep_continuation.py",
        "src/application/deep_chat_service.py",
        "src/repositories/deep_continuation_repository.py",
    ):
        text = io.open(root / name, encoding="utf-8").read()
        for forbidden in (
            "assistant_message =",
            "answer_generation",
            "pedagogy",
            "learning_state",
            "publication_authority\": True",
        ):
            assert forbidden not in text, f"{name} must not touch {forbidden}"


# --- review round 1: the runner singleton must not survive a cache reset -------------


def test_the_runner_is_dropped_by_the_runtime_cache_reset():
    from src.application import runtime_repository as runtime

    runtime.get_chat_service.cache_clear()
    runtime.get_deep_trigger_runner.cache_clear()
    try:
        old = runtime.get_deep_trigger_runner()
        runtime.reset_runtime_repository_cache()
        new = runtime.get_deep_trigger_runner()
        assert new is not old
        # The new runner captures the current singletons.
        assert new.repository.database is runtime.get_runtime_repository().database
    finally:
        runtime.get_deep_trigger_runner.cache_clear()
        runtime.get_chat_service.cache_clear()


def test_a_running_runner_is_stopped_by_the_cache_reset():
    from src.application import runtime_repository as runtime

    runtime.get_chat_service.cache_clear()
    runtime.get_deep_trigger_runner.cache_clear()
    try:
        old = runtime.get_deep_trigger_runner()
        old.start()
        assert old.running is True
        runtime.reset_runtime_repository_cache()
        assert old.running is False, "a reset must not leave an old worker scanning"
    finally:
        runtime.get_deep_trigger_runner.cache_clear()
        runtime.get_chat_service.cache_clear()
