"""Async Deep-1B evidence: durable paid-call identity (1B-5).

Real SQLite; no model, search or network call.
"""

from __future__ import annotations

import pytest

from src import llm_spend_guard as guard
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.llm_spend_ledger_repository import SpendLedgerRepository
from src.repositories.research_authorization_repository import (
    ResearchAuthorizationRepository,
    cny_to_micros,
)

CNY = cny_to_micros


@pytest.fixture()
def env(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    auth = ResearchAuthorizationRepository(database)
    ledger = SpendLedgerRepository(database)
    ledger.ensure_account(CNY(10))
    grant = auth.create_grant(
        owner_thread_id="thread-1", deadline_at="2099-01-01T00:00:00+00:00",
        max_model_calls=24, max_vision_calls=2, max_searches=20, max_reads=30,
        max_spend_micros=CNY(10), run_id="run-1",
    )
    guard.configure_ledger(ledger, account_id="account")
    yield auth, ledger, grant
    guard.configure_ledger(None)


def _call(step: str, *, run_id="run-1", purpose="planner"):
    return guard.stable_call_id(run_id=run_id, purpose=purpose, step=step)


# --- identity ------------------------------------------------------------

def test_call_identity_is_derived_from_durable_facts_not_a_fresh_uuid():
    first = _call("round-1")
    second = _call("round-1")
    assert first == second == "run-1:planner:round-1"
    assert first != _call("round-2")


# --- recovery refusals ---------------------------------------------------

def test_unknown_outcome_is_never_reissued_under_a_new_process(env):
    """A `sent` call must stop recovery instead of paying a second time."""

    _, ledger, grant = env
    call_id = _call("round-1")
    with guard.bound_scope(grant.id, "run-1"):
        guard.reserve_call(
            prompt_chars=4000, max_tokens=800, purpose="planner",
            model="deepseek-flash", call_id=call_id,
        )
    assert ledger.state(call_id) == "sent"
    reserved_once = bookkeeper(env)

    # A recovery in a fresh process rebuilds the same identity.
    assert _call("round-1") == call_id
    with guard.bound_scope(grant.id, "run-1"):
        with pytest.raises(guard.UncertainCall, match="already sent"):
            guard.reserve_call(
                prompt_chars=4000, max_tokens=800, purpose="planner",
                model="deepseek-flash", call_id=call_id,
            )

    assert bookkeeper(env) == reserved_once, "an unknown call must not be charged twice"
    assert ledger.unconfirmed_sends() == [call_id], "recovery can report it, not resend it"


def test_settled_call_is_never_reissued_and_settles_only_once(env):
    _, ledger, grant = env
    call_id = _call("round-2")
    with guard.bound_scope(grant.id, "run-1"):
        guard.reserve_call(
            prompt_chars=4000, max_tokens=800, purpose="planner",
            model="deepseek-flash", call_id=call_id,
        )
    guard.settle_call(call_id, actual_micros=CNY(0.2))
    assert ledger.state(call_id) == "settled"

    with guard.bound_scope(grant.id, "run-1"):
        with pytest.raises(guard.UncertainCall, match="already settled"):
            guard.reserve_call(
                prompt_chars=4000, max_tokens=800, purpose="planner",
                model="deepseek-flash", call_id=call_id,
            )

    guard.settle_call(call_id, actual_micros=CNY(9))  # repeat settlement
    assert ledger.state(call_id) == "settled"
    assert _settled(ledger, call_id) == CNY(0.2), (
        "a repeated recovery must not overwrite the settled amount"
    )


def test_a_reservation_that_never_left_the_process_may_be_retried(env):
    """The only safe re-entry: provably absent (reserved, never sent)."""

    _, ledger, grant = env
    call_id = _call("round-3", purpose="vision")

    def reserve_once():
        with guard.bound_scope(grant.id, "run-1"):
            guard.reserve_call(
                prompt_chars=500, max_tokens=200, purpose="vision",
                model="deepseek-flash", call_id=call_id,
            )

    reserve_once()
    assert ledger.state(call_id) == "sent"

    # Simulate a crash between the reservation and the send-intent write.
    with ledger.database.connect() as connection:
        connection.execute(
            "UPDATE llm_spend_ledger SET state = 'reserved' WHERE call_id = ?",
            (call_id,),
        )
    assert ledger.state(call_id) == "reserved"

    reserve_once()  # safe: it never left the process
    assert ledger.state(call_id) == "sent"


def _settled(ledger, call_id: str) -> int:
    with ledger.database.connect() as connection:
        row = connection.execute(
            "SELECT settled_micros FROM llm_spend_ledger WHERE call_id = ?", (call_id,)
        ).fetchone()
    return int(row["settled_micros"]) if row else 0


def bookkeeper(env) -> int:
    """The run's cumulative reserved amount, as the authorization sees it."""

    auth, _, _ = env
    return int(auth.run_usage("run-1")["reserved_micros"])
