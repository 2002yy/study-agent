"""Async Deep-1A evidence 2/3: lease fencing, paused/cancelled state, eligibility.

Real SQLite; no model, search or network call.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.application.async_research_eligibility import is_eligible
from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.research_authorization_repository import (
    ResearchAuthorizationRepository,
    cny_to_micros,
)
from src.repositories.web_lookup_repository import (
    LeaseHeld,
    LeaseLost,
    LeaseNotAvailable,
    WebLookupRepository,
)

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
    run = service.create("lease topic", owner_thread_id="thread-1")
    return database, repository, service, auth, run


def _grant(auth, run_id, *, spend_cny=10, deadline=None):
    return auth.create_grant(
        owner_thread_id="thread-1",
        deadline_at=deadline or (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        max_model_calls=24, max_vision_calls=2, max_searches=20, max_reads=30,
        max_spend_micros=CNY(spend_cny), run_id=run_id,
    )


def _expire_lease(database, run_id):
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET lease_expires_at = ? WHERE id = ?", (past, run_id)
        )


# --- concurrency ---------------------------------------------------------

def test_two_executors_cannot_lease_the_same_run(env):
    _, repository, _, _, run = env
    first = repository.acquire_lease(run.id, holder="worker-A")
    assert first.epoch == 1
    with pytest.raises(LeaseHeld):
        repository.acquire_lease(run.id, holder="worker-B")


def test_heartbeat_keeps_a_live_worker_past_the_old_stale_rule(env, ):
    database, repository, service, _, run = env
    repository.acquire_lease(run.id, holder="worker-A", ttl_seconds=90)
    # Simulate a long HTTP request: the legacy 120 s rule would call this stale...
    stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = json_set(research_context, '$.operation.active_operation_started_at', ?) WHERE id = ?",
            (stale, run.id),
        )
    # ...but the live lease still owns the run, so no takeover happens.
    with pytest.raises(LeaseHeld):
        repository.acquire_lease(run.id, holder="worker-B")
    renewed = repository.heartbeat_lease(run.id, holder="worker-A", epoch=1)
    assert renewed.epoch == 1


def test_stale_epoch_writes_are_rejected_for_checkpoint_complete_and_fail(env):
    database, repository, _, _, run = env
    first = repository.acquire_lease(run.id, holder="worker-A")
    _expire_lease(database, run.id)
    second = repository.acquire_lease(run.id, holder="worker-B")
    assert second.epoch == first.epoch + 1

    stale = ("worker-A", first.epoch)
    with pytest.raises(LeaseLost):
        repository.checkpoint(
            run.id, operation_id="op-stale", research_context={}, query_attempts=[],
            selected_sources=[], rejected_sources=[], items=[], warnings=[], lease=stale,
        )
    with pytest.raises(LeaseLost):
        repository.complete(
            run.id, items=[], source_block="", warnings=[], provider_status="found",
            stop_reason="completed", lease=stale,
        )
    with pytest.raises(LeaseLost):
        repository.fail(run.id, "boom", lease=stale)

    # The current holder is still allowed to write.
    repository.checkpoint(
        run.id, operation_id="worker-B", research_context={}, query_attempts=[],
        selected_sources=[], rejected_sources=[], items=[], warnings=[],
        lease=("worker-B", second.epoch),
    )


def test_takeover_after_the_lease_check_cannot_land_a_stale_write(env, monkeypatch):
    """L2: the fence must live in the write itself, not only in a prior check.

    ``assert_lease`` is disabled here on purpose, so the only thing that can stop
    the stale writer is the predicate inside the ``UPDATE``.
    """

    database, repository, _, _, run = env
    first = repository.acquire_lease(run.id, holder="worker-A")
    _expire_lease(database, run.id)
    second = repository.acquire_lease(run.id, holder="worker-B")
    assert second.epoch == first.epoch + 1
    before = repository.get(run.id)
    assert before is not None and before.lease_holder == "worker-B"

    monkeypatch.setattr(repository, "assert_lease", lambda *args, **kwargs: None)
    stale = ("worker-A", first.epoch)

    with pytest.raises(ValueError, match="conflicted"):
        repository.complete(
            run.id, items=[], source_block="", warnings=[], provider_status="found",
            stop_reason="", lease=stale,
        )
    with pytest.raises(ValueError, match="conflicted"):
        repository.fail(run.id, "boom", lease=stale)

    after = repository.get(run.id)
    assert after is not None
    assert after.status == before.status and after.version == before.version
    assert after.lease_holder == "worker-B" and after.lease_epoch == second.epoch


def test_authorized_run_pays_inside_its_own_scope_while_a_legacy_run_does_not(env):
    """1B-2: paid work of an authorized run must be bound to that run's grant."""

    from src import llm_spend_guard

    _, _, service, auth, legacy_run = env
    seen: list[object] = []

    class _ObservingGateway(_Gateway):
        def search(self, query, *, max_items=10):
            seen.append(llm_spend_guard.current_scope())
            return []

        def warnings(self):
            return []

    service.gateway = _ObservingGateway()
    # Same wiring production uses (src/application/runtime_repository.py).
    service.authorization_lookup = lambda run_id: auth.any_for_run(run_id)
    service.execute(legacy_run.id)
    assert seen and seen[-1] is None, "a legacy run must keep the process cap"

    authorized = service.create("authorized topic", owner_thread_id="thread-1")
    grant = _grant(auth, authorized.id)
    seen.clear()
    service.execute(authorized.id)
    assert seen and seen[-1] == (grant.id, authorized.id), (
        "an authorized run must bind its own grant scope while it executes"
    )


# --- cancellation / pause / eligibility ---------------------------------
def test_cancelled_run_is_never_leased_or_resumed(env):
    _, repository, _, _, run = env
    repository.cancel_run(run.id, reason="user_cancelled")

    with pytest.raises(LeaseNotAvailable):
        repository.acquire_lease(run.id, holder="worker-A")
    # The ordinary resume path refuses too (N13) unless explicitly opted in.
    with pytest.raises(ValueError, match="cancelled by the user"):
        repository.begin_operation(run.id, operation_id="op-1", stage="searching")

    after = repository._required(run.id)
    assert after.status == "cancelled"
    assert after.cancel_requested_at is not None  # the cancel fact is not cleared


def test_only_the_explicit_user_resume_may_revive_a_cancelled_run(env):
    _, repository, service, _, run = env
    repository.cancel_run(run.id, reason="user_cancelled")

    # Automatic / background entries must never revive it.
    with pytest.raises(LeaseNotAvailable):
        repository.acquire_lease(run.id, holder="worker-A")
    with pytest.raises(ValueError, match="cancelled by the user"):
        service.execute(run.id)
    assert repository._required(run.id).status == "cancelled"

    # The explicit, user-initiated resume remains available.
    revived = service.resume(run.id)
    assert revived.id == run.id
    assert repository._required(run.id).status != "cancelled"


def test_paused_resumes_only_with_an_active_authorization(env):
    _, repository, _, auth, run = env
    held = repository.acquire_lease(run.id, holder="worker-A")
    repository.pause_run(run.id, reason="authorization_exhausted",
                         lease=(held.holder, held.epoch))
    assert repository._required(run.id).status == "paused"

    # No grant -> not eligible.
    assert is_eligible(run=repository._required(run.id), grant=None, lease_available=True)[0] is False
    grant = _grant(auth, run.id)
    assert is_eligible(run=repository._required(run.id), grant=grant, lease_available=True) == (True, "")

    repository.resume_run(run.id)
    assert repository._required(run.id).status == "pending"


def test_expired_authorization_cannot_auto_start(env):
    _, repository, _, auth, run = env
    expired = _grant(auth, run.id, deadline=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    eligible, reason = is_eligible(run=repository._required(run.id), grant=expired, lease_available=True)
    assert (eligible, reason) == (False, "authorization_expired")


def test_reauthorization_does_not_reset_consumption(env):
    _, _, _, auth, run = env
    first = _grant(auth, run.id, spend_cny=10)
    auth.add_executed_seconds(first.id, 120.0)
    second = _grant(auth, run.id, spend_cny=10)

    assert second.authorization_version == first.authorization_version + 1
    assert second.supersedes_authorization_id == first.id
    assert auth.get(first.id).status == "superseded"
    # The old grant keeps its own history; nothing is zeroed by the new grant.
    assert auth.get(first.id).executed_seconds == pytest.approx(120.0)
    # Exactly one active entitlement per run.
    assert auth.active_for_run(run.id).id == second.id


def test_failed_runs_are_only_retryable_for_retryable_reasons(env):
    _, repository, _, auth, run = env
    grant = _grant(auth, run.id)

    from src.domain.runtime_entities import WebLookupRun

    def _failed(reason: str) -> WebLookupRun:
        return WebLookupRun(id=run.id, status="failed", stop_reason=reason,
                            research_context=run.research_context)

    assert is_eligible(run=_failed("providers_failed"), grant=grant, lease_available=True)[0] is True
    for blocked in ("permission_denied", "security_violation", "integrity_error"):
        eligible, reason = is_eligible(run=_failed(blocked), grant=grant, lease_available=True)
        assert eligible is False and reason.startswith("failure_not_retryable:")


# --- compatibility -------------------------------------------------------

def test_legacy_resume_semantics_are_preserved_for_uncancelled_runs(env):
    _, repository, _, _, run = env
    repository.begin_operation(run.id, operation_id="op-1", stage="searching")
    stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    context = dict(repository._required(run.id).research_context)
    operation = dict(context.get("operation") or {})
    operation["active_operation_started_at"] = stale
    context["operation"] = operation
    import json

    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), run.id),
        )
    resumed = repository.begin_operation(run.id, operation_id="op-2", stage="reading",
                                        stale_after_seconds=60)
    assert resumed.active_operation_id == "op-2"


def test_checkpoint_without_a_lease_keeps_previous_behaviour(env):
    _, repository, _, _, run = env
    # An *unleased* run keeps the legacy behaviour: an operation owner may write
    # without any lease fence (Async Deep-1A only fences leased runs).
    repository.begin_operation(run.id, operation_id="op-1", stage="searching")
    updated = repository.checkpoint(
        run.id, operation_id="op-1", research_context={"marker": 1}, query_attempts=[],
        selected_sources=[], rejected_sources=[], items=[], warnings=[],
    )
    assert updated.research_context.get("marker") == 1
    # ...while a leased run requires its fence (also asserted in the closure suite).
    repository.acquire_lease(run.id, holder="worker-A")
    with pytest.raises(LeaseLost, match="lease fence is required"):
        repository.checkpoint(
            run.id, operation_id="worker-A", research_context={}, query_attempts=[],
            selected_sources=[], rejected_sources=[], items=[], warnings=[],
        )
