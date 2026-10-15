"""Async Deep-1A-R closure: production wiring, fail-closed and race conditions.

Real SQLite + the real paid-call entry point (`_build_request_kwargs`); no model,
search or network call is made.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.llm_spend_ledger_repository import (
    SpendLedgerRepository,
    SpendLimitExceeded,
)
from src.repositories.research_authorization_repository import (
    ResearchAuthorizationRepository,
    cny_to_micros,
)

CNY = cny_to_micros


def _grant(auth, *, run_id="run-1", spend_cny=10, deadline=None, status_deadline=None):
    return auth.create_grant(
        owner_thread_id="thread-1",
        deadline_at=deadline or (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        max_model_calls=24, max_vision_calls=2, max_searches=20, max_reads=30,
        max_spend_micros=CNY(spend_cny), run_id=run_id,
    )


@pytest.fixture()
def stack(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    auth = ResearchAuthorizationRepository(database)
    ledger = SpendLedgerRepository(database)
    ledger.ensure_account(CNY(10))
    return database, auth, ledger, tmp_path


# --- F2: fail-closed reservation checks ---------------------------------

def test_reserve_refuses_expired_mis_scoped_or_unconfigured(stack, monkeypatch):
    database, auth, ledger, _ = stack
    expired = _grant(auth, run_id="run-1",
                     deadline=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    with pytest.raises(SpendLimitExceeded, match="expired"):
        ledger.reserve(call_id="c1", authorization_id=expired.id, scope_id="run-1",
                       purpose="chat", model="m", estimated_micros=CNY(0.1))

    fresh = _grant(auth, run_id="run-1")
    with pytest.raises(SpendLimitExceeded, match="bound to run"):
        ledger.reserve(call_id="c2", authorization_id=fresh.id, scope_id="other-run",
                       purpose="chat", model="m", estimated_micros=CNY(0.1))

    # No account ceiling => no authority to spend (never open-ended).
    with database.connect() as connection:
        connection.execute("DELETE FROM llm_spend_accounts")
    with pytest.raises(SpendLimitExceeded, match="account ceiling"):
        ledger.reserve(call_id="c3", authorization_id=fresh.id, scope_id="run-1",
                       purpose="chat", model="m", estimated_micros=CNY(0.1))


def test_reauthorization_carries_the_run_usage_forward(stack):
    _, auth, ledger, _ = stack
    first = _grant(auth, run_id="run-1", spend_cny=10)
    ledger.reserve(call_id="c1", authorization_id=first.id, scope_id="run-1",
                   purpose="chat", model="m", estimated_micros=CNY(3))
    auth.add_executed_seconds(first.id, 60.0)

    second = _grant(auth, run_id="run-1", spend_cny=10)
    assert second.reserved_micros == CNY(3), "the new grant must not restart from zero"
    assert second.executed_seconds == pytest.approx(60.0)
    # F4: carried forward, so the newest grant is the authoritative cumulative
    # (summing every grant would double-count the inherited amount).
    usage = auth.run_usage("run-1")
    assert usage["reserved_micros"] == CNY(3)
    assert usage["executed_seconds"] == pytest.approx(60.0)
    assert usage["grants"] == 2


# --- F1: the durable ledger is the authority for scoped calls ------------

def _kwargs(**overrides):

    base = dict(messages=[{"role": "user", "content": "x" * 50}], temperature=0.0,
                model_profile="flash", provider_profile="deepseek", task_name="deep_planner",
                max_tokens=100, timeout=5.0, response_format=None, stream=False)
    base.update(overrides)
    return base


def test_production_call_path_uses_the_durable_ledger_across_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL_FLASH_NAME", "deepseek-flash")
    monkeypatch.setenv("DEEPSEEK_MODEL_PRO_NAME", "deepseek-v4-pro")
    monkeypatch.setenv("LLM_SPEND_CAP_CNY", "1")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "2.5")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "9.0")

    import src.llm_spend_guard as guard

    database = RuntimeDatabase(tmp_path / "runtime.db")
    auth = ResearchAuthorizationRepository(database)
    ledger = SpendLedgerRepository(database)
    ledger.ensure_account(CNY(10))
    grant = _grant(auth, run_id="run-1", spend_cny=0.05)

    guard.reset_spend()
    guard.configure_ledger(ledger)
    token = guard.bind_scope(grant.id, "run-1")
    try:
        guard.reserve_call(prompt_chars=50, max_tokens=100, purpose="chat",
                           model="deepseek-flash", call_id="closure-1")
        reserved = auth.get(grant.id).reserved_micros
        assert reserved > 0
        assert auth.remaining_micros(grant.id) == grant.max_spend_micros - reserved
    finally:
        guard.reset_scope(token)

    # Simulate a process restart: fresh repositories on the same database.
    restarted_ledger = SpendLedgerRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    restarted_auth = ResearchAuthorizationRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    # The reservation survived the restart, so the allowance is NOT re-granted.
    assert restarted_auth.remaining_micros(grant.id) == grant.max_spend_micros - reserved
    assert [row for row in [restarted_ledger.state("closure-1")]] == ["sent"]


def test_paid_entry_points_route_through_the_guard(monkeypatch):
    """Every production paid entry point must call the (durable-capable) guard."""

    import inspect

    from src import llm_client

    source = inspect.getsource(llm_client._build_request_kwargs)
    assert "reserve_call(" in source, "the LLM client must reserve before sending"
    assert "model=" in source and "call_id=" in source, "the guard needs model + call id"

    from src.application import attachment_vision

    vision_source = inspect.getsource(attachment_vision.describe_image_with_deepseek)
    assert "reserve_call(" in vision_source, "vision must reserve through the same guard"


def test_without_a_bound_scope_the_guard_keeps_the_process_behaviour(stack, monkeypatch):
    database, auth, ledger, _ = stack
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL_FLASH_NAME", "deepseek-flash")
    monkeypatch.setenv("DEEPSEEK_MODEL_PRO_NAME", "deepseek-v4-pro")
    monkeypatch.setenv("LLM_SPEND_CAP_CNY", "10")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "2.5")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "9.0")

    from src.llm_spend_guard import configure_ledger, reset_spend

    reset_spend()
    configure_ledger(ledger)
    try:
        _kwargs()
        # No scope bound -> nothing is charged to a run authorization.
        assert auth.active_for_run("run-1") is None
    finally:
        configure_ledger(None)


# --- L1: fencing is mandatory for a leased run ---------------------------

def test_leasing_a_run_makes_the_fence_mandatory(tmp_path):
    from src.application.web_lookup_service import WebLookupService
    from src.repositories.web_lookup_repository import LeaseLost, WebLookupRepository

    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = WebLookupRepository(database)
    service = WebLookupService(repository, object())
    run = service.create("fenced topic", owner_thread_id="t")
    lease = repository.acquire_lease(run.id, holder="worker-A")

    # A leased run may not be written without its fence.
    with pytest.raises(LeaseLost, match="lease fence is required"):
        repository.checkpoint(
            run.id, operation_id="worker-A", research_context={}, query_attempts=[],
            selected_sources=[], rejected_sources=[], items=[], warnings=[],
        )
    with pytest.raises(LeaseLost, match="lease fence is required"):
        repository.fail(run.id, "boom", operation_id="worker-A")

    # With the fence it works.
    repository.checkpoint(
        run.id, operation_id="worker-A", research_context={"ok": 1}, query_attempts=[],
        selected_sources=[], rejected_sources=[], items=[], warnings=[],
        lease=("worker-A", lease.epoch),
    )


# --- S1: an async cancelled run cannot be revived ------------------------

def test_async_cancelled_run_cannot_be_resumed(tmp_path):
    from src.application.web_lookup_service import WebLookupService
    from src.repositories.research_authorization_repository import (
        ResearchAuthorizationRepository,
    )
    from src.repositories.web_lookup_repository import WebLookupRepository

    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = WebLookupRepository(database)
    auth = ResearchAuthorizationRepository(database)
    service = WebLookupService(repository, object(),
                               authorization_lookup=auth.any_for_run)
    run = service.create("async topic", owner_thread_id="t")
    _grant(auth, run_id=run.id)

    repository.cancel_run(run.id, reason="user_cancelled")
    with pytest.raises(ValueError, match="create a new run"):
        service.resume(run.id)


def test_legacy_run_without_authorization_keeps_explicit_resume(tmp_path):
    from src.application.web_lookup_service import WebLookupService
    from src.repositories.web_lookup_repository import WebLookupRepository

    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = WebLookupRepository(database)
    service = WebLookupService(repository, object())  # no authorization lookup
    run = service.create("legacy topic", owner_thread_id="t")
    repository.cancel_run(run.id, reason="user_cancelled")
    revived = service.resume(run.id)
    assert revived.id == run.id
    assert repository._required(run.id).status != "cancelled"
