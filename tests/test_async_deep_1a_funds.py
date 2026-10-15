"""Async Deep-1A evidence 1/3: money safety.

Real SQLite + deterministic clock; no model, search or network call.
"""

from __future__ import annotations

import pytest

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.llm_spend_ledger_repository import (
    SpendIdentityConflict,
    SpendLedgerRepository,
    SpendLimitExceeded,
)
from src.repositories.research_authorization_repository import (
    ResearchAuthorizationRepository,
    cny_to_micros,
)

CNY = cny_to_micros


@pytest.fixture()
def repos(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    auth = ResearchAuthorizationRepository(database)
    ledger = SpendLedgerRepository(database)
    # F2: a reservation needs an account ceiling; without it, spending is refused.
    ledger.ensure_account(CNY(10))
    return auth, ledger, tmp_path


def _grant(auth, *, run_id="run-1", spend_cny=10, deadline="2099-01-01T00:00:00+00:00"):
    return auth.create_grant(
        owner_thread_id="thread-1", deadline_at=deadline,
        max_model_calls=24, max_vision_calls=2, max_searches=20, max_reads=30,
        max_spend_micros=CNY(spend_cny), run_id=run_id,
    )


def test_same_call_id_with_identical_identity_is_idempotent(repos):
    auth, ledger, _ = repos
    grant = _grant(auth)
    first = ledger.reserve(call_id="c1", authorization_id=grant.id, scope_id="run-1",
                           purpose="chat:answer", model="deepseek-flash",
                           estimated_micros=CNY(0.5))
    second = ledger.reserve(call_id="c1", authorization_id=grant.id, scope_id="run-1",
                            purpose="chat:answer", model="deepseek-flash",
                            estimated_micros=CNY(0.5))
    assert first.created is True and second.created is False
    # Reserved once, not twice.
    assert auth.get(grant.id).reserved_micros == CNY(0.5)


def test_same_call_id_with_a_different_identity_is_rejected(repos):
    auth, ledger, _ = repos
    grant = _grant(auth)
    ledger.reserve(call_id="c1", authorization_id=grant.id, scope_id="run-1",
                   purpose="chat:answer", model="deepseek-flash", estimated_micros=CNY(0.5))
    with pytest.raises(SpendIdentityConflict):
        ledger.reserve(call_id="c1", authorization_id=grant.id, scope_id="run-1",
                       purpose="chat:different", model="deepseek-flash",
                       estimated_micros=CNY(0.5))


def test_run_and_global_ceilings_are_both_enforced(repos):
    auth, ledger, _ = repos
    grant = _grant(auth, spend_cny=1)
    ledger.ensure_account(CNY(5))
    # Run ceiling: 1 CNY grant cannot absorb 2 CNY.
    with pytest.raises(SpendLimitExceeded):
        ledger.reserve(call_id="c1", authorization_id=grant.id, scope_id="run-1",
                       purpose="chat:answer", model="m", estimated_micros=CNY(2))
    # Fits the run ceiling but not the account ceiling.
    ledger.ensure_account(CNY(0.2))
    with pytest.raises(SpendLimitExceeded):
        ledger.reserve(call_id="c2", authorization_id=grant.id, scope_id="run-1",
                       purpose="chat:answer", model="m", estimated_micros=CNY(0.5))
    # A rejected attempt leaves nothing partially deducted.
    assert auth.get(grant.id).reserved_micros == 0
    assert ledger.global_remaining_micros() == CNY(0.2)


def test_remaining_money_survives_a_process_restart(repos):
    auth, ledger, tmp_path = repos
    grant = _grant(auth)
    ledger.reserve(call_id="c1", authorization_id=grant.id, scope_id="run-1",
                   purpose="chat:answer", model="m", estimated_micros=CNY(3))

    # A brand-new repository pair on the same database == process restart.
    database = RuntimeDatabase(tmp_path / "runtime.db")
    restarted_auth = ResearchAuthorizationRepository(database)
    restarted_ledger = SpendLedgerRepository(database)

    assert restarted_auth.remaining_micros(grant.id) == CNY(7)
    # Recovery must not re-grant the consumed allowance.
    with pytest.raises(SpendLimitExceeded):
        restarted_ledger.reserve(call_id="c2", authorization_id=grant.id, scope_id="run-1",
                                 purpose="chat:answer", model="m", estimated_micros=CNY(8))


def test_vision_reservation_can_precede_the_run_and_is_bound_later(repos):
    auth, ledger, _ = repos
    # Authorization created for the session before any run exists.
    pre = auth.create_grant(
        owner_thread_id="thread-1", deadline_at="2099-01-01T00:00:00+00:00",
        max_model_calls=24, max_vision_calls=2, max_searches=20, max_reads=30,
        max_spend_micros=CNY(10), run_id=None,
    )
    ledger.reserve(call_id="vision-1", authorization_id=pre.id, scope_id="thread-1",
                   purpose="vision:image_description", model="deepseek-flash",
                   estimated_micros=CNY(0.2))
    bound = auth.bind_run(pre.id, "run-9")
    assert bound.run_id == "run-9"
    # The vision reservation is counted against the same authorization.
    assert auth.remaining_micros(pre.id) == CNY(9.8)


def test_unconfirmed_send_is_never_auto_resent(repos):
    auth, ledger, _ = repos
    grant = _grant(auth)
    ledger.reserve(call_id="c1", authorization_id=grant.id, scope_id="run-1",
                   purpose="chat:answer", model="m", estimated_micros=CNY(1))
    ledger.mark_sent("c1")
    assert ledger.unconfirmed_sends() == ["c1"]
    # Crash before the result was stored: the reservation stays, no refund...
    assert auth.remaining_micros(grant.id) == CNY(9)
    # ...and settling records the real cost for audit without touching the balance.
    ledger.settle("c1", actual_micros=CNY(0.4))
    assert ledger.state("c1") == "settled"
    assert auth.remaining_micros(grant.id) == CNY(9)


def test_orphaned_reservation_is_kept_without_refund(repos):
    auth, ledger, _ = repos
    grant = _grant(auth)
    ledger.reserve(call_id="c1", authorization_id=grant.id, scope_id="run-1",
                   purpose="chat:answer", model="m", estimated_micros=CNY(2))
    ledger.mark_orphaned("c1")
    assert ledger.state("c1") == "orphaned"
    assert auth.remaining_micros(grant.id) == CNY(8)


def test_micros_conversion_rounds_up(repos):
    assert CNY(0.0000001) == 1  # never rounds a paid call down to zero
    assert CNY(1.5) == 1_500_000
