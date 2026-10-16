"""Async Deep-1B evidence: worker scheduling, takeover and recovery (1B-4).

Six focused negative controls.  Two of them use **real separate processes** (claim
race and restart after a send), because thread-level simulation cannot prove either
the cross-process claim or the process-exit recovery contract.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src import llm_spend_guard as guard
from src.application.async_research_worker import AsyncResearchWorker
from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.async_research_discovery import (
    AsyncResearchDiscovery,
    ClaimRefused,
)
from src.repositories.llm_spend_ledger_repository import SpendLedgerRepository
from src.repositories.research_authorization_repository import (
    ResearchAuthorizationRepository,
    cny_to_micros,
)
from src.repositories.web_lookup_repository import LeaseLost, WebLookupRepository

CNY = cny_to_micros
ROOT = Path(__file__).resolve().parents[1]


class _Gateway:
    def search(self, query, *, max_items=10):
        return []

    def read(self, url, *, max_chars=6000):
        return {"ok": False, "url": url, "error": "unused"}

    def warnings(self):
        return []


@pytest.fixture()
def env(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = WebLookupRepository(database)
    service = WebLookupService(repository, _Gateway())
    auth = ResearchAuthorizationRepository(database)
    ledger = SpendLedgerRepository(database)
    ledger.ensure_account(CNY(10))
    discovery = AsyncResearchDiscovery(database, runs=repository, authorizations=auth)
    return database, repository, service, auth, ledger, discovery


def _grant(auth, run_id, *, spend_cny=10, deadline=None):
    return auth.create_grant(
        owner_thread_id="thread-1",
        deadline_at=deadline
        or (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        max_model_calls=24, max_vision_calls=2, max_searches=20, max_reads=30,
        max_spend_micros=CNY(spend_cny), run_id=run_id,
    )


def _paused_authorized_run(service, repository, auth, *, topic="topic"):
    run = service.create(topic, owner_thread_id="thread-1")
    prep = repository.acquire_lease(run.id, holder="prep")
    repository.pause_run(run.id, reason="prep", lease=(prep.holder, prep.epoch))
    _expire_lease(repository.database, run.id)
    grant = _grant(auth, run.id)
    return run, grant


def _expire_lease(database, run_id):
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET lease_expires_at = ? WHERE id = ?", (past, run_id)
        )


def _run_child(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )


# --- 1. two independent processes race for one run -----------------------

_CLAIM_CHILD = """
    import sys, time
    from src.infrastructure.sqlite.database import RuntimeDatabase
    from src.repositories.async_research_discovery import (
        AsyncResearchDiscovery, ClaimRefused,
    )
    from src.repositories.research_authorization_repository import (
        ResearchAuthorizationRepository,
    )
    from src.repositories.web_lookup_repository import WebLookupRepository

    db, run_id, holder = sys.argv[1], sys.argv[2], sys.argv[3]
    database = RuntimeDatabase(db)
    discovery = AsyncResearchDiscovery(
        database,
        runs=WebLookupRepository(database),
        authorizations=ResearchAuthorizationRepository(database),
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            claim = discovery.claim(run_id, holder=holder, ttl_seconds=120)
        except ClaimRefused as exc:
            print(f"REFUSED {exc.reason}", flush=True)
            sys.exit(0)
        print(f"OK {claim.epoch}", flush=True)
        sys.exit(0)
    print("TIMEOUT", flush=True)
"""


def test_two_processes_racing_for_one_run_leave_exactly_one_authority(env, tmp_path):
    database, repository, service, auth, _, _ = env
    run, _ = _paused_authorized_run(service, repository, auth, topic="race")

    processes = [
        subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent(_CLAIM_CHILD), str(database.path), run.id,
             f"worker-{index}"],
            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for index in range(2)
    ]
    outputs = [process.communicate(timeout=180)[0].strip() for process in processes]

    winners = [line for line in outputs if line.startswith("OK")]
    losers = [line for line in outputs if line.startswith("REFUSED")]
    assert len(winners) == 1, f"exactly one process may hold the lease, got {outputs}"
    assert len(losers) == 1, f"the other must be refused, got {outputs}"

    with database.connect() as connection:
        row = connection.execute(
            "SELECT lease_holder, lease_epoch FROM web_lookup_runs WHERE id = ?", (run.id,)
        ).fetchone()
    assert row["lease_holder"] in {"worker-0", "worker-1"}
    assert int(row["lease_epoch"]) >= 1


# --- 2. authorization expiring between discovery and claim ---------------

def test_authorization_expiring_between_discovery_and_claim_refuses_the_claim(env):
    database, repository, service, auth, _, discovery = env
    run, grant = _paused_authorized_run(service, repository, auth, topic="expiring")
    assert [c.run_id for c in discovery.discover()] == [run.id]

    # The grant expires after discovery but before the claim transaction.
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with database.connect() as connection:
        connection.execute(
            "UPDATE research_authorizations SET deadline_at = ? WHERE id = ?",
            (past, grant.id),
        )

    with pytest.raises(ClaimRefused) as refusal:
        discovery.claim(run.id, holder="worker-A")
    assert refusal.value.reason == "authorization_expired"
    # No execution rights were handed out, so no paid work can start.
    with database.connect() as connection:
        row = connection.execute(
            "SELECT lease_holder FROM web_lookup_runs WHERE id = ?", (run.id,)
        ).fetchone()
    assert not row["lease_holder"] or row["lease_holder"] == "prep"


# --- 3. crash after the claim, before any paid call ---------------------

def test_crash_after_claim_before_any_paid_call_allows_recovery(env):
    database, repository, service, auth, ledger, discovery = env
    run, grant = _paused_authorized_run(service, repository, auth, topic="crash-early")

    crash = discovery.claim(run.id, holder="worker-A", ttl_seconds=90)
    assert crash.epoch >= 1
    assert discovery.unconfirmed_calls(run.id) == (), "nothing was ever sent"

    # The process dies; the lease is never released or heart-beaten.
    _expire_lease(database, run.id)
    takeover = discovery.claim(run.id, holder="worker-B", ttl_seconds=90)
    assert takeover.epoch == crash.epoch + 1, "takeover must advance the fencing epoch"
    assert ledger.state(  # no paid call exists to be ambiguous about
        guard.stable_call_id(run_id=run.id, purpose="planner", step="round-1")
    ) is None


# --- 4. process exit after marking the call sent ------------------------

_SEND_CHILD = """
    import sys
    from src import llm_spend_guard as guard
    from src.infrastructure.sqlite.database import RuntimeDatabase
    from src.repositories.llm_spend_ledger_repository import SpendLedgerRepository

    db, run_id, auth_id = sys.argv[1], sys.argv[2], sys.argv[3]
    database = RuntimeDatabase(db)
    ledger = SpendLedgerRepository(database)
    ledger.ensure_account(10_000_000)
    guard.configure_ledger(ledger, account_id="account")
    call_id = guard.stable_call_id(run_id=run_id, purpose="planner", step="round-1")
    with guard.bound_scope(auth_id, run_id):
        guard.reserve_call(
            prompt_chars=4000, max_tokens=800, purpose="planner",
            model="deepseek-flash", call_id=call_id,
        )
    print("SENT", flush=True)
"""


def test_process_exit_after_a_sent_call_prevents_a_second_send(env):
    database, repository, service, auth, ledger, discovery = env
    run, grant = _paused_authorized_run(service, repository, auth, topic="sent-then-exit")

    child = _run_child(_SEND_CHILD, str(database.path), run.id, grant.id)
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "SENT"

    call_id = guard.stable_call_id(run_id=run.id, purpose="planner", step="round-1")
    assert ledger.state(call_id) == "sent"
    assert discovery.unconfirmed_calls(run.id) == (call_id,)

    # Recovery must stop rather than pay again.
    with pytest.raises(ClaimRefused) as refusal:
        discovery.claim(run.id, holder="worker-B")
    assert refusal.value.reason == "unconfirmed_paid_call"

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT COUNT(*) AS calls FROM llm_spend_ledger WHERE authorization_id = ?",
            (grant.id,),
        ).fetchone()
    assert int(rows["calls"]) == 1, "recovery must not create a second paid call"


def test_worker_parks_a_run_whose_paid_call_is_unconfirmed(env):
    database, repository, service, auth, ledger, discovery = env
    run, grant = _paused_authorized_run(service, repository, auth, topic="park")
    call_id = guard.stable_call_id(run_id=run.id, purpose="planner", step="round-1")
    ledger.reserve(
        call_id=call_id, authorization_id=grant.id, scope_id=run.id, purpose="planner",
        model="deepseek-chat", estimated_micros=CNY(1),
    )
    ledger.mark_sent(call_id)

    worker = AsyncResearchWorker(
        discovery=discovery, runs=repository, authorizations=auth,
        executor=lambda claim: pytest.fail("a parked run must never execute"),
    )
    outcome = worker.run_once(holder="worker-B")

    assert outcome.claimed is False
    current = repository.get(run.id)
    assert current is not None and current.status == "paused", (
        "the run must be parked, not retried in a loop"
    )


# --- 5. the old worker keeps no authority after a takeover ---------------

def test_old_worker_after_takeover_cannot_heartbeat_write_or_claim(env):
    database, repository, service, auth, _, discovery = env
    run, _ = _paused_authorized_run(service, repository, auth, topic="takeover")

    old = discovery.claim(run.id, holder="worker-A", ttl_seconds=60)
    _expire_lease(database, run.id)
    new = discovery.claim(run.id, holder="worker-B", ttl_seconds=60)
    assert new.epoch == old.epoch + 1

    with pytest.raises(LeaseLost):
        repository.heartbeat_lease(run.id, holder=old.holder, epoch=old.epoch)
    with pytest.raises(LeaseLost):
        repository.complete(
            run.id, items=[], source_block="", warnings=[], provider_status="found",
            stop_reason="", lease=(old.holder, old.epoch),
        )
    with pytest.raises(ClaimRefused) as refusal:
        discovery.claim(run.id, holder="worker-A")
    assert refusal.value.reason == "lease_held"

    # The current holder still owns the run.
    repository.heartbeat_lease(run.id, holder=new.holder, epoch=new.epoch)


# --- 6. scope follows the paid call across threads ----------------------

def test_each_paid_call_gets_its_scope_even_when_executed_on_another_thread(env):
    database, repository, service, auth, ledger, discovery = env
    run, grant = _paused_authorized_run(service, repository, auth, topic="scoped")
    guard.configure_ledger(ledger, account_id="account")

    seen: list[object] = []

    def executor(claim):
        seen.append(guard.current_scope())
        guard.reserve_call(
            prompt_chars=4000, max_tokens=800, purpose="planner", model="deepseek-flash",
            call_id=guard.stable_call_id(run_id=claim.run_id, purpose="planner", step="round-1"),
        )

    worker = AsyncResearchWorker(
        discovery=discovery, runs=repository, authorizations=auth, executor=executor,
        holder="worker-A", ttl_seconds=120,
    )
    try:
        outcome: list[object] = []
        thread = threading.Thread(
            target=lambda: outcome.append(worker.run_once(holder="worker-A"))
        )
        thread.start()
        thread.join(timeout=60)
    finally:
        guard.configure_ledger(None)

    assert seen == [(grant.id, run.id)], (
        "the worker must establish the run's scope where the paid call happens"
    )
    call_id = guard.stable_call_id(run_id=run.id, purpose="planner", step="round-1")
    assert ledger.state(call_id) == "sent"
    assert auth.run_usage(run.id)["reserved_micros"] > 0
    assert outcome and outcome[0].executed is True
