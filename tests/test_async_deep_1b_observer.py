"""Async Deep-1B evidence: SSE observer is decoupled from execution (1B-6).

The four boundary rules are proven without a browser: the route's decision function
is exercised directly, and the observer is shown to be read-only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.application.async_research_observer import (
    AsyncResearchObserver,
    should_cancel_on_disconnect,
)
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
from src.repositories.web_lookup_repository import WebLookupRepository

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
    ledger.ensure_account(CNY(10))
    discovery = AsyncResearchDiscovery(database, runs=repository, authorizations=auth)
    observer = AsyncResearchObserver(runs=repository)
    return database, repository, service, auth, ledger, discovery, observer


def _grant(auth, run_id, *, spend_cny=10):
    return auth.create_grant(
        owner_thread_id="thread-1",
        deadline_at=(datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        max_model_calls=24, max_vision_calls=2, max_searches=20, max_reads=30,
        max_spend_micros=CNY(spend_cny), run_id=run_id,
    )


def _paused_authorized_run(service, repository, auth, *, topic="topic"):
    run = service.create(topic, owner_thread_id="thread-1")
    prep = repository.acquire_lease(run.id, holder="prep")
    repository.pause_run(run.id, reason="prep", lease=(prep.holder, prep.epoch))
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET lease_expires_at = ? WHERE id = ?", (past, run.id)
        )
    grant = _grant(auth, run.id)
    return run, grant


# --- rule 1: disconnect does not end a background run -------------------

def test_disconnect_cancels_only_an_immediate_run(env):
    """The route's decision: observers leave, authorized runs keep going."""

    assert should_cancel_on_disconnect(run_is_async=False) is True
    assert should_cancel_on_disconnect(run_is_async=True) is False


def test_service_reports_a_run_as_async_only_when_it_has_a_grant(env):
    _, _, service, auth, _, _, _ = env
    service.authorization_lookup = lambda run_id: auth.any_for_run(run_id)

    immediate = service.create("immediate", owner_thread_id="thread-1")
    assert service.is_async_authorized(immediate.id) is False
    assert should_cancel_on_disconnect(run_is_async=service.is_async_authorized(immediate.id))

    async_run = service.create("async", owner_thread_id="thread-1")
    _grant(auth, async_run.id)
    assert service.is_async_authorized(async_run.id) is True
    assert not should_cancel_on_disconnect(
        run_is_async=service.is_async_authorized(async_run.id)
    )


# --- rule 2: reconnect re-subscribes, never starts a second worker ------

def test_reconnect_observes_without_starting_a_second_worker(env):
    database, repository, service, auth, _, discovery, observer = env
    run, _ = _paused_authorized_run(service, repository, auth, topic="reconnect")
    claim = discovery.claim(run.id, holder="worker-A", ttl_seconds=300)

    before = observer.snapshot(run.id)
    assert before["lease_holder"] == "worker-A"
    assert observer.is_observed_by_worker(run.id) is True

    # A reconnect only reads: the lease, epoch and version must not move.
    for _ in range(3):
        observer.snapshot(run.id)
    after = repository.get(run.id)
    assert after.version == before["version"], "observing must not write"
    assert after.lease_holder == "worker-A" and after.lease_epoch == claim.epoch

    with pytest.raises(ClaimRefused) as refusal:
        discovery.claim(run.id, holder="worker-B")
    assert refusal.value.reason == "lease_held", "a reconnect cannot seize the run"


# --- rule 3: explicit cancel is a persisted fact ------------------------

def test_explicit_cancel_stops_the_worker_and_is_not_optimistic(env):
    database, repository, service, auth, _, discovery, _ = env
    run, _ = _paused_authorized_run(service, repository, auth, topic="cancel")
    # The explicit user stop is a persisted fact, not an in-memory signal.
    repository.cancel_run(run.id, reason="user_cancelled")
    cancelled = repository.get(run.id)
    assert cancelled.status == "cancelled"

    assert discovery.discover() == (), "a cancelled run is never a candidate again"
    with pytest.raises(ClaimRefused) as refusal:
        discovery.claim(run.id, holder="worker-B")
    assert refusal.value.reason in {"cancelled_is_terminal", "status_not_eligible:cancelled"}


# --- rule 4: completion with no observer attached -----------------------

def test_background_run_completes_with_no_observer_attached(env):
    database, repository, service, auth, _, discovery, observer = env
    run, _ = _paused_authorized_run(service, repository, auth, topic="no-observer")

    executed: list[str] = []

    def executor(claim):
        executed.append(claim.run_id)
        repository.complete(
            claim.run_id, items=[{"title": "found"}], source_block="[1] source",
            warnings=[], provider_status="found", stop_reason="",
            lease=(claim.holder, claim.epoch),
        )

    worker = AsyncResearchWorker(
        discovery=discovery, runs=repository, authorizations=auth, executor=executor,
        holder="worker-A", ttl_seconds=120,
    )
    outcome = worker.run_once(holder="worker-A")

    assert outcome.claimed is True and outcome.executed is True
    assert executed == [run.id]
    persisted = repository.get(run.id)
    assert persisted.status == "completed", "results persist with nobody watching"
    assert persisted.items == [{"title": "found"}]
    assert observer.snapshot(run.id)["status"] == "completed"
