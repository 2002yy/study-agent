"""Async Deep-1B-R1 evidence: production-closure negative controls.

Covers the review findings: a superseded worker must not be able to pay or park, an
authorized paid call must carry a stable identity, a re-authorization must not
unblock an unconfirmed call, and a claimed lease must be usable by its own holder.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
from src.repositories.web_lookup_repository import LeaseHeld, LeaseLost, WebLookupRepository

CNY = cny_to_micros


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


def _grant(auth, run_id, *, spend_cny=10):
    return auth.create_grant(
        owner_thread_id="thread-1",
        deadline_at=(datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        max_model_calls=24, max_vision_calls=2, max_searches=20, max_reads=30,
        max_spend_micros=CNY(spend_cny), run_id=run_id,
    )


def _expire(database, run_id):
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET lease_expires_at = ? WHERE id = ?", (past, run_id)
        )


def _authorized(service, repository, auth, *, topic="t"):
    run = service.create(topic, owner_thread_id="thread-1")
    prep = repository.acquire_lease(run.id, holder="prep")
    repository.pause_run(run.id, reason="prep", lease=(prep.holder, prep.epoch))
    _expire(repository.database, run.id)
    return run, _grant(auth, run.id)


# --- P0-3: a superseded worker can neither pay nor park -----------------

def test_superseded_worker_cannot_start_a_new_paid_request(env):
    database, repository, service, auth, ledger, discovery = env
    guard.configure_ledger(ledger, account_id="account")
    try:
        run, grant = _authorized(service, repository, auth, topic="superseded-pay")
        stale = discovery.claim(run.id, holder="worker-A", ttl_seconds=60)
        _expire(database, run.id)
        fresh = discovery.claim(run.id, holder="worker-B", ttl_seconds=60)
        assert fresh.epoch == stale.epoch + 1

        # The old worker still has a valid authorization and a healthy balance.
        assert auth.get(grant.id).status == "active"
        with guard.bound_scope(grant.id, run.id, lease=(stale.holder, stale.epoch)):
            with pytest.raises(guard.SpendLimitExceeded, match="no longer holds the lease"):
                guard.reserve_call(
                    prompt_chars=4000, max_tokens=800, purpose="planner",
                    model="deepseek-flash",
                    call_id=guard.stable_call_id(
                        run_id=run.id, purpose="planner", step="round-1"
                    ),
                )
        with database.connect() as connection:
            calls = connection.execute(
                "SELECT COUNT(*) AS n FROM llm_spend_ledger WHERE scope_id = ?", (run.id,)
            ).fetchone()
        assert int(calls["n"]) == 0, "the superseded holder must not create a paid call"

        # The current holder may pay.
        with guard.bound_scope(grant.id, run.id, lease=(fresh.holder, fresh.epoch)):
            guard.reserve_call(
                prompt_chars=4000, max_tokens=800, purpose="planner",
                model="deepseek-flash",
                call_id=guard.stable_call_id(
                    run_id=run.id, purpose="planner", step="round-1"
                ),
            )
        assert ledger.state(
            guard.stable_call_id(run_id=run.id, purpose="planner", step="round-1")
        ) == "sent"
    finally:
        guard.configure_ledger(None)


def test_superseded_worker_cannot_park_the_new_workers_run(env):
    database, repository, service, auth, _, discovery = env
    run, _ = _authorized(service, repository, auth, topic="superseded-park")
    stale = discovery.claim(run.id, holder="worker-A", ttl_seconds=60)
    _expire(database, run.id)
    fresh = discovery.claim(run.id, holder="worker-B", ttl_seconds=60)

    # A late failure path of the old worker must not stop the new worker's run.
    with pytest.raises(LeaseLost):
        repository.pause_run(run.id, reason="late_failure",
                             lease=(stale.holder, stale.epoch))
    current = repository.get(run.id)
    assert current.status == "running" and current.lease_holder == fresh.holder

    worker = AsyncResearchWorker(
        discovery=discovery, runs=repository, authorizations=auth,
        executor=lambda claim: None, holder="worker-A",
    )
    worker._park(run.id, "late_failure", claim=stale)
    still = repository.get(run.id)
    assert still.status == "running" and still.lease_holder == fresh.holder, (
        "a superseded worker's park must be a no-op"
    )


# --- P0-4: stable identity and cross-authorization blocking -------------

def test_authorized_paid_call_without_a_stable_identity_is_refused(env):
    database, repository, service, auth, ledger, discovery = env
    guard.configure_ledger(ledger, account_id="account")
    try:
        run, grant = _authorized(service, repository, auth, topic="no-identity")
        claim = discovery.claim(run.id, holder="worker-A", ttl_seconds=120)
        with guard.bound_scope(grant.id, run.id, lease=(claim.holder, claim.epoch)):
            with pytest.raises(guard.UncertainCall, match="stable call_id"):
                guard.reserve_call(
                    prompt_chars=4000, max_tokens=800, purpose="planner",
                    model="deepseek-flash",
                )
    finally:
        guard.configure_ledger(None)


def test_reauthorization_does_not_unblock_an_unconfirmed_call(env):
    database, repository, service, auth, ledger, discovery = env
    run, first = _authorized(service, repository, auth, topic="reauth")
    call_id = guard.stable_call_id(run_id=run.id, purpose="planner", step="round-1")
    ledger.reserve(
        call_id=call_id, authorization_id=first.id, scope_id=run.id, purpose="planner",
        model="deepseek-chat", estimated_micros=CNY(1),
    )
    ledger.mark_sent(call_id)

    # The user grants again; the new grant has a different id.
    second = _grant(auth, run.id)
    assert second.id != first.id

    # The block must survive, because it is a fact about the run, not the grant.
    assert discovery.unconfirmed_calls(run.id) == (call_id,)
    with pytest.raises(ClaimRefused) as refusal:
        discovery.claim(run.id, holder="worker-B")
    assert refusal.value.reason == "unconfirmed_paid_call"


# --- P0-2: a claimed lease is usable by its holder ----------------------

def test_a_claimed_lease_can_begin_its_own_operation_but_not_a_foreign_one(env):
    database, repository, service, auth, _, discovery = env
    run, _ = _authorized(service, repository, auth, topic="begin-op")
    claim = discovery.claim(run.id, holder="worker-A", ttl_seconds=120)

    # The same holder continues under its own lease instead of being blocked.
    begun = repository.begin_operation(
        run.id, operation_id=claim.holder, stage="collecting",
        lease=(claim.holder, claim.epoch),
    )
    assert begun.status == "running"

    # Anybody else is still refused while that lease is live.
    with pytest.raises(LeaseHeld):
        repository.begin_operation(
            run.id, operation_id="intruder", stage="collecting",
            lease=("worker-Z", claim.epoch),
        )
