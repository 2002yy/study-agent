"""Async Deep-1B evidence: the restricted discovery entry.

Real SQLite; no model, search or network call.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.async_research_discovery import AsyncResearchDiscovery
from src.repositories.deep_trigger_repository import DeepTriggerRepository
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
    discovery = AsyncResearchDiscovery(database, runs=repository, authorizations=auth)
    return database, repository, service, auth, discovery


def _grant(auth, run_id, *, deadline=None, spend_cny=10):
    return auth.create_grant(
        owner_thread_id="thread-1",
        deadline_at=deadline
        or (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        max_model_calls=24, max_vision_calls=2, max_searches=20, max_reads=30,
        max_spend_micros=CNY(spend_cny), run_id=run_id,
    )


def _pause(repository, run_id):
    held = repository.acquire_lease(run_id, holder="worker-A")
    repository.pause_run(run_id, reason="test", lease=(held.holder, held.epoch))


# --- 1B-3: entry boundary ------------------------------------------------

def test_unauthorized_run_is_never_discoverable(env):
    """Without a grant there is no async task, so no paid background work."""

    _, repository, service, _, discovery = env
    run = service.create("unauthorized topic", owner_thread_id="thread-1")
    _pause(repository, run.id)

    assert discovery.discover() == ()


def test_expired_grant_does_not_make_a_run_discoverable(env):
    _, repository, service, auth, discovery = env
    run = service.create("expired topic", owner_thread_id="thread-1")
    _pause(repository, run.id)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    grant = _grant(auth, run.id, deadline=past)
    assert grant.status == "active"

    assert discovery.discover() == ()


def test_authorized_paused_run_is_discoverable(env):
    _, repository, service, auth, discovery = env
    run = service.create("authorized topic", owner_thread_id="thread-1")
    _pause(repository, run.id)
    grant = _grant(auth, run.id)

    candidates = discovery.discover()
    assert [c.run_id for c in candidates] == [run.id]
    assert candidates[0].authorization_id == grant.id


def test_a_live_lease_makes_a_run_unavailable_to_a_second_worker(env):
    _, repository, service, auth, discovery = env
    run = service.create("leased topic", owner_thread_id="thread-1")
    repository.acquire_lease(run.id, holder="worker-A")  # live, not expired
    _grant(auth, run.id)

    assert discovery.discover() == ()


def test_discovery_is_reached_only_through_the_authorization_join(env):
    """A paused run with no grant must stay invisible even beside eligible peers."""

    _, repository, service, auth, discovery = env
    orphan = service.create("orphan topic", owner_thread_id="thread-1")
    _pause(repository, orphan.id)
    peer = service.create("peer topic", owner_thread_id="thread-1")
    _pause(repository, peer.id)
    _grant(auth, peer.id)

    run_ids = [c.run_id for c in discovery.discover()]
    assert run_ids == [peer.id]
    assert orphan.id not in run_ids


# --- 1B-3: the existing Standard->Deep queue must not change -------------

def test_new_entry_leaves_the_standard_deep_queue_untouched(env):
    _, _, service, auth, discovery = env
    triggers = DeepTriggerRepository(service.repository.database)
    before = triggers.discover()

    run = service.create("topic", owner_thread_id="thread-1")
    _grant(auth, run.id)
    discovery.discover()

    assert triggers.discover() == before
