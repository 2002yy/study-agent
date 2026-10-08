"""SQLite restart, fencing and crash-window controls for Standard consumption."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest

from src.application.standard_execution import StandardExecution
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.web_lookup_repository import WebLookupRepository
from tests.test_standard_handoff import Gateway, saved_parent as saved_parent


@pytest.fixture
def running(saved_parent):
    repository, runs, parent, created = saved_parent
    clock = [created + timedelta(seconds=3)]
    execution = StandardExecution.start(
        repository,
        runs,
        parent_turn_id=parent.id,
        thread_id=parent.thread_id,
        overall_deadline=created + timedelta(seconds=90),
        clock=lambda: clock[0],
    )
    return execution, clock, repository, runs, parent


def snapshot(running):
    execution, _, _, runs, _ = running
    return runs.get(execution.run_id).research_context["standard"]


def resume(running):
    execution, clock, repository, _, parent = running
    # Reconstruct both service and repository; no Python counter/cache survives.
    return StandardExecution.resume(
        RuntimeRepository(repository.database),
        run_id=execution.run_id,
        thread_id=parent.thread_id,
        clock=lambda: clock[0],
    )


def test_restart_preserves_cached_result_counters_cursor_and_deadline(running):
    execution, _, _, _, _ = running
    gateway = Gateway()
    execution.read(gateway, "https://example.com/new")
    execution.search(gateway, "new gap query")
    before = snapshot(running)
    execution.interrupt()
    after = resume(running)
    result = after.read(gateway, "https://example.com/new")
    result["content"] = "client mutation"
    assert (
        after.read(gateway, "https://example.com/new")["content"] != "client mutation"
    )
    after.search(gateway, "new gap query")
    final = snapshot(running)
    assert gateway.reads == gateway.queries == 1
    assert final["new_reads"] == final["new_queries"] == 1
    assert final["cursor"] == before["cursor"] == 2
    assert final["deadline"] == before["deadline"]
    assert final["publication_authority"] is False


def test_lookup_body_reuse_survives_a_fresh_consumer(running, saved_parent):
    execution, _, _, _, _ = running
    execution.interrupt()
    after = resume(running)
    url = saved_parent[2].rag_snapshot["lookup_terminal"]["handoff"]["usable_sources"][
        0
    ]["arguments"]["url"]
    gateway = Gateway()
    after.read(gateway, url)
    assert gateway.reads == snapshot(running)["new_reads"] == 0
    assert snapshot(running)["reused_reads"] == 1


def test_two_workers_cannot_acquire_one_live_operation(running):
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(resume, running) for _ in range(2)]
    for future in futures:
        with pytest.raises(ValueError, match="already leased"):
            future.result()


def test_simultaneous_start_creates_one_child_and_one_lease(saved_parent):
    repository, runs, parent, created = saved_parent

    def start():
        try:
            return StandardExecution.start(
                repository,
                runs,
                parent_turn_id=parent.id,
                thread_id=parent.thread_id,
                overall_deadline=created + timedelta(seconds=90),
                clock=lambda: created + timedelta(seconds=3),
            )
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: start(), range(2)))
    assert sum(result is not None for result in results) == 1
    assert (
        len([run for run in runs.list_by_owner_turn(parent.id) if run.parent_run_id])
        == 1
    )


@pytest.mark.parametrize("interrupt", [True, False])
def test_crash_after_reservation_never_replays_unknown_network_work(running, interrupt):
    execution, clock, _, _, _ = running
    execution.journal.reserve(
        execution.run_id,
        execution.thread_id,
        execution.operation_id,
        "read",
        "https://example.com/uncertain",
        clock[0],
    )
    if interrupt:
        execution.interrupt()
    else:
        clock[0] += timedelta(seconds=16)
    after = resume(running)
    gateway = Gateway()
    with pytest.raises(ValueError, match="automatic retry forbidden"):
        after.read(gateway, "https://example.com/uncertain")
    assert gateway.reads == 0 and snapshot(running)["new_reads"] == 1
    with pytest.raises(ValueError, match="stale operation"):
        execution.read(gateway, "https://example.com/late")


@pytest.mark.parametrize("kind", ["read", "search"])
def test_failure_and_restart_do_not_reset_or_retry_cost(running, kind):
    execution, _, _, _, _ = running

    class FailedGateway:
        def read(self, *_a, **_k):
            raise OSError("offline")

        search_exact = read

    with pytest.raises(OSError):
        getattr(execution, kind)(FailedGateway(), "failed-target")
    execution.interrupt()
    after = resume(running)
    with pytest.raises(ValueError, match="automatic retry forbidden"):
        getattr(after, kind)(Gateway(), "failed-target")
    counter = "new_reads" if kind == "read" else "new_queries"
    assert snapshot(running)[counter] == 1


@pytest.mark.parametrize("kind,limit", [("read", 5), ("search", 4)])
def test_remaining_budget_stays_bounded_across_restart(running, kind, limit):
    execution, _, _, _, _ = running
    gateway = Gateway()
    getattr(execution, kind)(gateway, "target-0")
    execution.interrupt()
    after = resume(running)
    for index in range(1, limit):
        getattr(after, kind)(gateway, f"target-{index}")
    with pytest.raises(ValueError, match="budget exhausted"):
        getattr(after, kind)(gateway, "over-limit")
    assert getattr(gateway, "reads" if kind == "read" else "queries") == limit


@pytest.mark.parametrize(
    "invalid",
    ["cancel", "deadline", "wrong_thread", "source_changed", "handoff_tampered"],
)
def test_resume_rechecks_saved_authorities(running, invalid):
    execution, clock, repository, runs, _ = running
    if invalid == "cancel":
        runs.request_cancel(execution.run_id)
    elif invalid == "deadline":
        clock[0] += timedelta(seconds=60)
    elif invalid == "source_changed":
        with repository.database.connect() as connection:
            connection.execute(
                "UPDATE web_lookup_runs SET version = version + 1 WHERE id = 'source-run'"
            )
    elif invalid == "handoff_tampered":
        from copy import deepcopy
        from dataclasses import replace

        parent = running[4]
        rag = deepcopy(parent.rag_snapshot)
        rag["lookup_terminal"]["handoff"]["query"] = "tampered but kept digest"
        repository.upsert_chat_turn(replace(parent, rag_snapshot=rag))
    else:
        with pytest.raises(ValueError, match="owner"):
            StandardExecution.resume(
                repository,
                run_id=execution.run_id,
                thread_id="another-thread",
                clock=lambda: clock[0],
            )
        return
    with pytest.raises(ValueError):
        execution.read(Gateway(), "https://example.com/blocked")
    with pytest.raises(ValueError):
        resume(running)


def test_cancellation_blocks_late_worker_result_and_preserves_reserved_charge(running):
    execution, _, _, runs, _ = running
    entered, release = Event(), Event()

    class SlowGateway:
        def read(self, *_a, **_k):
            entered.set()
            release.wait(2)
            return {"content": "late body"}

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execution.read, SlowGateway(), "late-url")
            assert entered.wait(2)
            runs.request_cancel(execution.run_id)
            with pytest.raises(ValueError, match="cancelled"):
                future.result(timeout=2)
    finally:
        release.set()
    entries = snapshot(running)["entries"].values()
    assert any(
        entry["state"] == "reserved" and entry["target"] == "late-url"
        for entry in entries
    )
    assert all(
        (entry.get("result") or {}).get("content") != "late body" for entry in entries
    )
    assert snapshot(running)["new_reads"] == 1


def test_old_token_cannot_be_reacquired_after_interrupt(running):
    execution, clock, _, _, _ = running
    execution.interrupt()
    with pytest.raises(ValueError, match="fresh token"):
        execution.journal.acquire(
            execution.run_id, execution.thread_id, execution.operation_id, clock[0]
        )


def test_oversized_body_cannot_enter_journal(running):
    execution, _, _, _, _ = running

    class Oversized:
        def read(self, *_a, **_k):
            return {"content": "x" * 6001}

    with pytest.raises(ValueError, match="text budget"):
        execution.read(Oversized(), "oversized")
    assert snapshot(running)["new_reads"] == 1
    assert any(
        entry["state"] == "failed" for entry in snapshot(running)["entries"].values()
    )


def test_unknown_schema_is_not_resumed(running):
    execution, _, repository, _, _ = running
    import json

    run = WebLookupRepository(repository.database).get(execution.run_id)
    context = run.research_context
    context["standard"]["schema"] = "future-schema"
    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), execution.run_id),
        )
    with pytest.raises(ValueError, match="journal"):
        resume(running)


def test_stale_owner_cannot_save_a_reserved_result_after_takeover(running):
    execution, clock, _, _, _ = running
    reservation = execution.journal.reserve(
        execution.run_id,
        execution.thread_id,
        execution.operation_id,
        "read",
        "unknown-target",
        clock[0],
    )
    clock[0] += timedelta(seconds=16)
    resume(running)
    with pytest.raises(ValueError, match="stale operation"):
        execution.journal.finish(
            execution.run_id,
            execution.thread_id,
            execution.operation_id,
            reservation["key"],
            clock[0],
            result={"content": "stale"},
        )
    assert snapshot(running)["new_reads"] == 1


def test_initial_deadline_is_not_extended_by_starting_again(running):
    execution, clock, repository, runs, parent = running
    original_deadline = snapshot(running)["deadline"]
    execution.interrupt()
    clock[0] += timedelta(seconds=10)
    StandardExecution.start(
        repository,
        runs,
        parent_turn_id=parent.id,
        thread_id=parent.thread_id,
        overall_deadline=clock[0] + timedelta(seconds=60),
        clock=lambda: clock[0],
    )
    assert snapshot(running)["deadline"] == original_deadline


def test_foreign_operation_cannot_be_overwritten_on_resume(running):
    import json

    execution, _, repository, runs, _ = running
    execution.interrupt()
    run = runs.get(execution.run_id)
    context = run.research_context
    context["operation"]["active_operation_id"] = "foreign-op"
    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), execution.run_id),
        )
    with pytest.raises(ValueError, match="owner mismatch"):
        resume(running)


def test_total_body_budget_survives_restart(running):
    execution, _, _, _, _ = running

    class LargeBody:
        def read(self, *_a, **_k):
            return {"content": "x" * 6000}

    gateway = LargeBody()
    for index in range(3):
        execution.read(gateway, f"body-{index}")
    execution.interrupt()
    after = resume(running)
    with pytest.raises(ValueError, match="text budget"):
        after.read(gateway, "excess-total-body")
    assert snapshot(running)["new_reads"] == 4


def test_provider_timeout_leaves_no_late_result(running, monkeypatch):
    import src.application.standard_execution as module

    execution, _, _, _, _ = running
    release = Event()

    class SlowBody:
        def read(self, *_a, **_k):
            release.wait(2)
            return {"content": "arrived after timeout"}

    class FakeTime:
        calls = 0

        @staticmethod
        def monotonic():
            FakeTime.calls += 1
            return 0.0 if FakeTime.calls == 1 else 9.0

    monkeypatch.setattr(module, "time", FakeTime)
    try:
        with pytest.raises(TimeoutError, match="provider timeout"):
            execution.read(SlowBody(), "timeout-url")
    finally:
        release.set()
    entry = next(
        item
        for item in snapshot(running)["entries"].values()
        if item["target"] == "timeout-url"
    )
    assert entry["state"] == "failed" and entry["error"] == "TimeoutError"
    assert entry["result"] == {} and snapshot(running)["new_reads"] == 1


def test_deadline_between_reservation_and_dispatch_spends_no_network_work(running):
    execution, clock, _, _, _ = running
    original_clock = execution.clock
    calls = 0

    def advancing_clock():
        nonlocal calls
        calls += 1
        return original_clock() if calls == 1 else clock[0] + timedelta(seconds=60)

    execution.clock = advancing_clock
    gateway = Gateway()
    with pytest.raises(ValueError, match="before dispatch"):
        execution.read(gateway, "too-late-target")
    assert gateway.reads == 0 and snapshot(running)["new_reads"] == 1


def test_cancel_between_reservation_and_worker_prevents_network_work(running):
    execution, _, _, runs, _ = running
    original_clock = execution.clock
    calls = 0

    def cancel_before_submit():
        nonlocal calls
        calls += 1
        if calls == 2:
            runs.request_cancel(execution.run_id)
        return original_clock()

    execution.clock = cancel_before_submit
    gateway = Gateway()
    with pytest.raises(ValueError, match="cancelled"):
        execution.read(gateway, "cancel-before-worker")
    assert gateway.reads == 0 and snapshot(running)["new_reads"] == 1


def test_fresh_python_process_reuses_persisted_body_without_network(running):
    import subprocess
    import sys

    execution, clock, repository, _, _ = running
    execution.read(Gateway(), "https://example.com/process-reuse")
    execution.interrupt()
    script = """
from datetime import datetime
import sys
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository
from src.application.standard_execution import StandardExecution
class NoNetwork:
    def read(self, *_a, **_k):
        raise AssertionError('completed work must not dispatch again')
repository = RuntimeRepository(RuntimeDatabase(sys.argv[1]))
consumer = StandardExecution.resume(repository, run_id=sys.argv[2], thread_id=sys.argv[3],
    clock=lambda: datetime.fromisoformat(sys.argv[4]))
assert consumer.read(NoNetwork(), 'https://example.com/process-reuse')['content'] == 'new body; no support authority'
consumer.interrupt()
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(repository.database.path),
            execution.run_id,
            execution.thread_id,
            clock[0].isoformat(),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert snapshot(running)["new_reads"] == 1
    assert snapshot(running)["reused_reads"] == 1
