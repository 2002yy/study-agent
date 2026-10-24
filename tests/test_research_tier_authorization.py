"""CL-M3 QD-3d: upgrading a research's cost tier needs the user's permission.

The contract froze the third semantic on 2026-10-24
(CL_M3_CAPABILITY_CONTRACT.md §11.3): a tier upgrade is a **user permission
decision**, recorded in **its own table**, in two states.

**Why it cannot live in the existing quota column.** ``research_states`` already
carries ``quota_observed`` - what was left when the checkpoint was written.
That is an *observation of a budget*, and it is deliberately allowed to change
on every checkpoint. An authorisation is neither an observation nor
perishable: it is a decision, it has an author, it has an expiry, and it must
survive long enough to be audited. Putting the two in one column would mean
the next checkpoint overwrote the record of who approved what - and the
contract's criterion 4 ("升档必须留下用户授权记录") would be satisfied by a
field that a routine write erases.

**The counter-examples**, straight from §11.3:

1. A *request* to upgrade is treated as an approval. It is not - the request
   is the model asking, and the answer is the user's.
2. An authorisation is expired, or belongs to a different operation, and the
   upgrade goes ahead anyway.
3. The authorisation record is missing entirely, and the upgrade still
   happens.
4. The audit trail lives only in the event log, so the authority for the
   upgrade is a projection rather than a record.

Each of these is a test below.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.research_tier_repository import (
    ResearchTierRepository,
    TierAuthorizationDenied,
)

RESEARCH = "research-1"
THREAD = "thread-1"
OPERATION = "operation-1"


@pytest.fixture
def db(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.sqlite")
    database.initialize()
    return database


@pytest.fixture
def repository(db):
    return ResearchTierRepository(db)


def _now(offset_seconds: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()


def _create_research(db, research_id=RESEARCH, *, operation_id=OPERATION, tier="standard"):
    from src.repositories.research_state_repository import ResearchStateRepository

    states = ResearchStateRepository(db)
    states.create(
        research_id=research_id,
        thread_id=THREAD,
        operation_id=operation_id,
        original_question="what is X?",
        question="what is X?",
        tier=tier,
    )
    return states


# --- the request is a request ------------------------------------------------------------


def test_a_request_is_recorded_and_is_not_an_approval(repository, db):
    """The model asks; nothing has been granted yet.

    The distinction has to survive in the data, not just in a variable. If the
    request row already said "approved", there would be no place to put the
    user's answer.
    """

    _create_research(db)

    request = repository.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="the standard tier cannot resolve this",
        requested_calls=10,
        requested_cost=1.25,
        now=_now(),
    )

    assert request.status == "pending"
    assert request.approved is False


def test_an_upgrade_is_refused_while_the_request_is_still_pending(repository, db):
    """Counter-example 1: the request is treated as the approval.

    This is the failure the whole table exists to prevent: the research asks
    to spend more, and because the asking is recorded, something later reads
    that record and spends more.
    """

    _create_research(db)
    repository.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="need more calls",
        requested_calls=10,
        requested_cost=1.25,
        now=_now(),
    )

    with pytest.raises(TierAuthorizationDenied):
        repository.apply_upgrade(RESEARCH, operation_id=OPERATION, now=_now())


# --- the approval is a user action --------------------------------------------------------


def test_an_approved_request_allows_the_upgrade(repository, db):
    """The positive path, so the guard cannot be "implemented" by refusing
    every upgrade.
    """

    _create_research(db)
    request = repository.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="need more calls",
        requested_calls=10,
        requested_cost=1.25,
        now=_now(),
    )

    repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    state = repository.apply_upgrade(RESEARCH, operation_id=OPERATION, now=_now())

    assert state.tier == "deep"
    assert state.tier_upgrade_authorized is True


def test_a_denied_request_does_not_allow_the_upgrade(repository, db):
    """The user's "no" is recorded and honoured."""

    _create_research(db)
    request = repository.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="need more calls",
        requested_calls=10,
        requested_cost=1.25,
        now=_now(),
    )

    repository.deny(request.request_id, approver="user-1", reason="too expensive", now=_now())

    with pytest.raises(TierAuthorizationDenied):
        repository.apply_upgrade(RESEARCH, operation_id=OPERATION, now=_now())


# --- counter-example 2: expiry and identity -------------------------------------------------


def test_an_expired_authorisation_does_not_allow_the_upgrade(repository, db):
    """Counter-example 2, first half: the authorisation expired.

    A grant that was given for "the next ten minutes" must stop working after
    ten minutes, even though the record is still there and still says
    approved.
    """

    _create_research(db)
    request = repository.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="need more calls",
        requested_calls=10,
        requested_cost=1.25,
        now=_now(),
    )
    repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(60),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    with pytest.raises(TierAuthorizationDenied):
        repository.apply_upgrade(RESEARCH, operation_id=OPERATION, now=_now(3600))


def test_an_authorisation_for_another_operation_does_not_allow_the_upgrade(
    repository, db
):
    """Counter-example 2, second half: the authorisation is for something else.

    The user approved an upgrade for one research. A different research must
    not inherit it, or a single approval becomes a blank cheque.
    """

    _create_research(db, RESEARCH, operation_id=OPERATION)
    _create_research(db, "research-2", operation_id="operation-2")

    request = repository.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="need more calls",
        requested_calls=10,
        requested_cost=1.25,
        now=_now(),
    )
    repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    with pytest.raises(TierAuthorizationDenied):
        repository.apply_upgrade(
            "research-2", operation_id="operation-2", now=_now()
        )


def test_an_authorisation_for_another_operation_identity_does_not_apply(
    repository, db
):
    """The same research, but a *different* operation identity, is a different run.

    A research may be resumed, retried or re-run under a new operation. An
    authorisation given to the old operation does not carry over silently.
    """

    _create_research(db, RESEARCH, operation_id=OPERATION)
    request = repository.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="need more calls",
        requested_calls=10,
        requested_cost=1.25,
        now=_now(),
    )
    repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    with pytest.raises(TierAuthorizationDenied):
        repository.apply_upgrade(RESEARCH, operation_id="a-different-operation", now=_now())


# --- counter-example 3: no record at all ---------------------------------------------------


def test_a_missing_authorisation_does_not_allow_the_upgrade(repository, db):
    """Counter-example 3: nothing was ever requested or approved.

    This is the "default deny" case. The absence of a record has to mean
    "no", never "probably fine".
    """

    _create_research(db)

    with pytest.raises(TierAuthorizationDenied):
        repository.apply_upgrade(RESEARCH, operation_id=OPERATION, now=_now())


def test_a_cancelled_research_cannot_be_upgraded(repository, db):
    """A cancelled research must not be able to spend more either.

    The contract says a cancellation forbids new requests *and* tier
    upgrades. A guard that only looked at the authorisation table would miss
    this.
    """

    from src.repositories.research_state_repository import ResearchStateRepository

    states = ResearchStateRepository(db)
    _create_research(db)
    request = repository.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="need more calls",
        requested_calls=10,
        requested_cost=1.25,
        now=_now(),
    )
    repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )
    states.cancel(RESEARCH, reason="user_cancelled")

    with pytest.raises(TierAuthorizationDenied):
        repository.apply_upgrade(RESEARCH, operation_id=OPERATION, now=_now())


# --- counter-example 4: the audit trail is not the authority ---------------------------------


def test_the_approval_is_kept_even_if_the_event_log_is_cleared(repository, db):
    """Counter-example 4: the authority for an upgrade is not a projection.

    QD-3c established that the event log is not a second truth. The same
    discipline applies here: clearing the log must not change whether a
    research is allowed to upgrade. If the log were the authority, a routine
    log retention job would silently revoke a user's approval - or, worse,
    a log that still holds an old "approved" event would re-grant one.
    """

    _create_research(db)
    request = repository.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="need more calls",
        requested_calls=10,
        requested_cost=1.25,
        now=_now(),
    )
    repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    with db.connect() as connection:
        connection.execute("DELETE FROM research_events")

    state = repository.apply_upgrade(RESEARCH, operation_id=OPERATION, now=_now())

    assert state.tier == "deep"


def test_the_approval_records_who_decided(repository, db):
    """An authorisation without an author cannot be audited.

    §10.8's criterion 4 asks for a record of the user's authorisation. A
    record that says "approved" but not "by whom" answers a different
    question.
    """

    _create_research(db)
    request = repository.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="need more calls",
        requested_calls=10,
        requested_cost=1.25,
        now=_now(),
    )

    decision = repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    assert decision.status == "approved"
    assert decision.approver == "user-1"
    assert decision.decided_at != ""


# --- the clock expires a grant ------------------------------------------------------------

def test_a_grant_that_reached_its_deadline_is_written_down_as_expired(repository, db):
    """The clock alone may end a grant, and it says so in the record.

    A grant whose deadline has passed is no longer a permission, and the
    record has to say that - otherwise an auditor reading the table sees an
    "approved" row and cannot tell it was spent against.
    """

    _create_research(db)
    request = repository.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="need more calls",
        requested_calls=10,
        requested_cost=1.25,
        now=_now(),
    )
    repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(60),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    expired = repository.expire(request.request_id, now=_now(3600))

    assert expired.status == "expired"


def test_a_live_grant_cannot_be_marked_expired(repository, db):
    """Expiring a grant that has not reached its deadline is a revocation.

    A revocation is a *decision*, and decisions belong to the user. Letting
    the clock path do it would let anything that can call ``expire`` pull a
    grant the user still holds - which is exactly the authority the table was
    built to keep separate.
    """

    _create_research(db)
    request = repository.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="need more calls",
        requested_calls=10,
        requested_cost=1.25,
        now=_now(),
    )
    repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    with pytest.raises(TierAuthorizationDenied):
        repository.expire(request.request_id, now=_now())


def test_the_request_row_agrees_with_the_expired_authorisation(repository, db):
    """Two tables, one decision - they may not disagree.

    The request row and the authorisation row describe the same decision. If
    one says "expired" and the other says "approved", a reader has to guess
    which one is telling the truth, and that is the second-truth problem this
    table exists to avoid.
    """

    _create_research(db)
    request = repository.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="need more calls",
        requested_calls=10,
        requested_cost=1.25,
        now=_now(),
    )
    repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(60),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    repository.expire(request.request_id, now=_now(3600))

    assert repository.authorization(request.request_id).status == "expired"
    assert repository.requests_for(RESEARCH)[0].status == "expired"


def test_a_grant_that_was_never_approved_has_nothing_to_expire(repository, db):
    """Expiry ends a permission. There is no permission to end."""

    _create_research(db)
    request = repository.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="need more calls",
        requested_calls=10,
        requested_cost=1.25,
        now=_now(),
    )

    with pytest.raises(TierAuthorizationDenied):
        repository.expire(request.request_id, now=_now(3600))


def test_an_expired_grant_does_not_allow_a_later_upgrade(repository, db):
    """Writing the expiry down is not decoration - it changes the outcome.

    The expiry is checked twice: once against the clock, and once against the
    record. Both have to hold, and the second one is what stops a grant whose
    deadline passed from being reusable.
    """

    _create_research(db)
    request = repository.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="need more calls",
        requested_calls=10,
        requested_cost=1.25,
        now=_now(),
    )
    repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(60),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )
    repository.expire(request.request_id, now=_now(3600))

    with pytest.raises(TierAuthorizationDenied):
        repository.apply_upgrade(RESEARCH, operation_id=OPERATION, now=_now(7200))
