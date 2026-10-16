"""Async Deep-1B final evidence: the four frozen product paths.

Real SQLite, fake model/search gateways, and **real separate processes** where the
contract is about process exit and restart.  No paid API is ever called.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src import llm_spend_guard as guard
from src.application.async_research_observer import should_cancel_on_disconnect
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
    ledger.ensure_account(CNY(50))
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


def _expire_lease(database, run_id):
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET lease_expires_at = ? WHERE id = ?", (past, run_id)
        )


def _authorized_run(service, repository, auth, *, topic, items=None, context=None,
                    spend_cny=10):
    run = service.create(topic, owner_thread_id="thread-1")
    prep = repository.acquire_lease(run.id, holder="prep")
    repository.pause_run(run.id, reason="prep", lease=(prep.holder, prep.epoch))
    _expire_lease(repository.database, run.id)
    if items or context:
        with repository.database.connect() as connection:
            connection.execute(
                "UPDATE web_lookup_runs SET items = ?, research_context = ? WHERE id = ?",
                (json.dumps(items or []), json.dumps(context or {}), run.id),
            )
    grant = _grant(auth, run.id, spend_cny=spend_cny)
    return run, grant


# --- path 1: auto start, disconnect does not kill it, immediate still does ---

def test_path_1_authorized_run_starts_itself_and_survives_a_disconnect(env):
    _, repository, service, auth, _, discovery = env
    service.authorization_lookup = lambda run_id: auth.any_for_run(run_id)
    run, grant = _authorized_run(service, repository, auth, topic="path1")

    executed: list[str] = []
    worker = AsyncResearchWorker(
        discovery=discovery, runs=repository, authorizations=auth,
        executor=lambda claim: executed.append(claim.run_id), holder="worker-A",
    )
    outcome = worker.run_once(holder="worker-A")
    assert outcome.claimed and outcome.executed and executed == [run.id], (
        "an authorized run must start without a user request"
    )

    # The observer leaves: the async run is not cancelled, an immediate one is.
    assert service.is_async_authorized(run.id) is True
    assert should_cancel_on_disconnect(run_is_async=True) is False
    immediate = service.create("immediate", owner_thread_id="thread-1")
    assert should_cancel_on_disconnect(
        run_is_async=service.is_async_authorized(immediate.id)
    ) is True


# --- path 2: restart continues the run, never re-reads or re-sends ------

_RESTART_CHILD = """
    import sys
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
    run = WebLookupRepository(database).get(run_id)
    print("ITEMS " + str(len(run.items)), flush=True)
    print("STAGE " + str(run.stage), flush=True)
    try:
        claim = discovery.claim(run_id, holder=holder, ttl_seconds=120)
    except ClaimRefused as exc:
        print("REFUSED " + exc.reason, flush=True)
        sys.exit(0)
    print(f"CLAIMED {claim.epoch}", flush=True)
"""


def test_path_2_restart_continues_from_the_checkpoint_and_never_re_sends(env):
    database, repository, service, auth, ledger, discovery = env
    run, grant = _authorized_run(
        service, repository, auth, topic="path2",
        items=[{"title": "already read"}],
        context={"read_summary": {"ok": 3, "failed": 0}, "stage": "collecting"},
    )

    # Process A: claim and make one paid call whose outcome is never recorded.
    first = discovery.claim(run.id, holder="worker-A", ttl_seconds=60)
    call_id = guard.stable_call_id(run_id=run.id, purpose="planner", step="round-1")
    ledger.reserve(
        call_id=call_id, authorization_id=grant.id, scope_id=run.id, purpose="planner",
        model="deepseek-chat", estimated_micros=CNY(1),
    )
    ledger.mark_sent(call_id)
    # ... and the process dies without settling it.

    _expire_lease(database, run.id)
    child = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_RESTART_CHILD), str(database.path), run.id,
         "worker-B"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )
    assert child.returncode == 0, child.stderr
    lines = child.stdout.split()
    assert lines[0] == "ITEMS" and lines[1] == "1", (
        "committed evidence must survive the restart"
    )
    assert "REFUSED" in child.stdout and "unconfirmed_paid_call" in child.stdout, (
        f"recovery must stop on an unconfirmed call, got: {child.stdout}"
    )

    with database.connect() as connection:
        calls = connection.execute(
            "SELECT COUNT(*) AS n FROM llm_spend_ledger WHERE authorization_id = ?",
            (grant.id,),
        ).fetchone()
    assert int(calls["n"]) == 1, "the restart must not create a second paid call"
    assert first.epoch >= 1


def test_path_2_restart_is_safe_when_nothing_was_ever_sent(env):
    database, repository, service, auth, ledger, discovery = env
    run, grant = _authorized_run(service, repository, auth, topic="path2b")
    discovery.claim(run.id, holder="worker-A", ttl_seconds=60)
    _expire_lease(database, run.id)

    child = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_RESTART_CHILD), str(database.path), run.id,
         "worker-B"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )
    assert "CLAIMED" in child.stdout, f"a clean restart must resume, got {child.stdout}"
    assert int(child.stdout.splitlines()[-1].split()[1]) >= 2


# --- path 3: cumulative budgets govern the run --------------------------

def test_path_3_cumulative_ceiling_and_expired_lease_hold_execution(env):
    database, repository, service, auth, ledger, discovery = env
    run, grant = _authorized_run(service, repository, auth, topic="path3", spend_cny=2)

    # Spend the whole authorization, then a fresh claim must be refused.
    ledger.reserve(
        call_id="spend-all", authorization_id=grant.id, scope_id=run.id, purpose="planner",
        model="deepseek-chat", estimated_micros=CNY(2),
    )
    ledger.mark_sent("spend-all")
    with pytest.raises(ClaimRefused) as refusal:
        discovery.claim(run.id, holder="worker-A")
    assert refusal.value.reason in {"authorization_exhausted", "unconfirmed_paid_call"}

    # A late heartbeat cannot restore rights that a takeover already moved on.
    other, _ = _authorized_run(service, repository, auth, topic="path3b")
    stale = discovery.claim(other.id, holder="worker-A", ttl_seconds=60)
    _expire_lease(database, other.id)
    fresh = discovery.claim(other.id, holder="worker-B", ttl_seconds=60)
    assert fresh.epoch > stale.epoch
    with pytest.raises(LeaseLost):
        repository.heartbeat_lease(other.id, holder=stale.holder, epoch=stale.epoch)


# --- path 4: stop / expiry / exhaustion / lost authority all block spend ---

def test_path_4_every_stop_condition_blocks_the_next_paid_request(env):
    database, repository, service, auth, ledger, discovery = env

    # (a) explicit stop
    stopped, _ = _authorized_run(service, repository, auth, topic="stop")
    repository.cancel_run(stopped.id, reason="user_cancelled")
    with pytest.raises(ClaimRefused):
        discovery.claim(stopped.id, holder="worker-A")

    # (b) authorization expiry
    expired, expired_grant = _authorized_run(service, repository, auth, topic="expired")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with database.connect() as connection:
        connection.execute(
            "UPDATE research_authorizations SET deadline_at = ? WHERE id = ?",
            (past, expired_grant.id),
        )
    with pytest.raises(ClaimRefused) as refusal:
        discovery.claim(expired.id, holder="worker-A")
    assert refusal.value.reason == "authorization_expired"

    # (c) spend exhaustion
    drained, drained_grant = _authorized_run(service, repository, auth, topic="drained")
    with database.connect() as connection:
        connection.execute(
            "UPDATE research_authorizations SET reserved_micros = max_spend_micros "
            "WHERE id = ?",
            (drained_grant.id,),
        )
    with pytest.raises(ClaimRefused) as refusal:
        discovery.claim(drained.id, holder="worker-A")
    assert refusal.value.reason == "authorization_exhausted"

    # (d) lost authority: the old holder cannot write a terminal state either
    taken, _ = _authorized_run(service, repository, auth, topic="taken")
    old = discovery.claim(taken.id, holder="worker-A", ttl_seconds=60)
    _expire_lease(database, taken.id)
    new = discovery.claim(taken.id, holder="worker-B", ttl_seconds=60)
    with pytest.raises(LeaseLost):
        repository.complete(
            taken.id, items=[], source_block="", warnings=[], provider_status="found",
            stop_reason="", lease=(old.holder, old.epoch),
        )
    repository.complete(
        taken.id, items=[], source_block="", warnings=[], provider_status="found",
        stop_reason="", lease=(new.holder, new.epoch),
    )
