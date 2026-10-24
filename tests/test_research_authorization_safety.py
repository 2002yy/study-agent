"""CL-M3 R-6 authorisation safety: the three holes, closed.

The contract froze the authorisation semantics on 2026-10-24
(CL_M3_CAPABILITY_CONTRACT.md §11.3):

> **升档前必须重新核验**（不是"请求过就行"）：
> - 授权记录存在，且状态为 `approved`；
> - 授权**未过期**；
> - 授权关联的**操作身份**与当前研究一致；
> - 授权的**费用/调用上限**足以覆盖这次升档。
>
> **一律不得升档的情形**：超时、取消、被拒绝、记录缺失。

**Why this file exists separately.** QD-3d wrote the authorisation table and
its happy path. That work was reviewed, and the review found three places
where the implementation was looser than the contract it claimed to
implement. This file is the negative control for those three places - it is
written from the contract's counter-examples, not from the code, and every
test here fails against the pre-fix implementation.

**The three holes, in the contract's own words:**

1. **An approval may carry no expiry and no ceiling.** The contract's record
   table says an authorisation decision contains "有效期、费用上限" - an
   expiry and a cost ceiling. An approval with neither is not a bounded
   permission; it is a blank cheque. And the ceiling check itself had a
   short-circuit: `if self.max_calls and calls > self.max_calls` skips the
   comparison entirely when ``max_calls`` is 0, so a ceiling of zero meant
   "no limit" rather than "no allowance".

2. **The upgrade path did not check the research's own operation identity.**
   It compared the authorisation's ``operation_id`` against the *caller's*
   argument, but never against the ``research_states`` row. The state's
   ``operation_id`` was read from the database and then never used.

3. **The final write had no state condition.** ``UPDATE research_states SET
   tier = ... WHERE research_id = ?`` - no status, no cancellation flag, no
   version. The read-side checks above it were separated from the write by
   a window in which a cancellation could land, so a cancel and an upgrade
   racing each other could both succeed.

Each test below is the contract's counter-example for one of those, plus
the positive cases that keep the guard from being "implemented" by
refusing everything.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.research_state_repository import ResearchStateRepository
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


def _request(repository, **overrides):
    """A pending upgrade request, ready to be approved."""

    arguments = {
        "operation_id": OPERATION,
        "from_tier": "standard",
        "to_tier": "deep",
        "reason": "need more calls",
        "requested_calls": 10,
        "requested_cost": 1.25,
        "now": _now(),
    }
    arguments.update(overrides)
    return repository.request_upgrade(RESEARCH, **arguments)


# --- hole 1: an approval with no expiry and no ceiling is not an approval -----------------


def test_an_approval_without_an_expiry_is_refused(repository, db):
    """The contract's authorisation record carries "有效期" - an expiry.

    Without one, the grant never runs out. The dataclass's own docstring
    says it: "one without an expiry is a permission that never ends, which
    is not what 'this time, this much' means". The check was missing, so
    the sentence described an intention rather than a rule.
    """

    _create_research(db)
    request = _request(repository)

    with pytest.raises(TierAuthorizationDenied) as refused:
        repository.approve(
            request.request_id,
            approver="user-1",
            scope="this research only",
            valid_until="",  # no deadline
            max_calls=10,
            max_cost=1.25,
            now=_now(),
        )

    assert refused.value.reason == "authorization_missing_expiry"


def test_an_approval_without_a_call_ceiling_is_refused(repository, db):
    """The record carries a cost ceiling, and a call ceiling.

    A ceiling of zero is not "no ceiling" - it is a ceiling of zero. But
    ``covers()`` short-circuited on it: ``if self.max_calls and ...`` skips
    the comparison entirely when the ceiling is 0, so a grant with
    ``max_calls=0`` covered *any* number of calls. The approval must not
    even be recordable in that state.
    """

    _create_research(db)
    request = _request(repository)

    with pytest.raises(TierAuthorizationDenied) as refused:
        repository.approve(
            request.request_id,
            approver="user-1",
            scope="this research only",
            valid_until=_now(3600),
            max_calls=0,  # no ceiling at all
            max_cost=1.25,
            now=_now(),
        )

    assert refused.value.reason == "authorization_missing_ceiling"


def test_an_approval_without_a_cost_ceiling_is_refused(repository, db):
    """The same for the cost ceiling: no ceiling means no record.

    The contract's record table lists "费用上限" alongside "有效期". A grant
    that bounds the calls but not the money is bounded on the cheaper axis
    only, and the money is the axis that costs.
    """

    _create_research(db)
    request = _request(repository)

    with pytest.raises(TierAuthorizationDenied) as refused:
        repository.approve(
            request.request_id,
            approver="user-1",
            scope="this research only",
            valid_until=_now(3600),
            max_calls=10,
            max_cost=0.0,  # no cost ceiling
            now=_now(),
        )

    assert refused.value.reason == "authorization_missing_ceiling"


def test_a_refused_approval_leaves_the_request_pending(repository, db):
    """A rejected approval must not decide the request.

    Otherwise "the approval was refused" and "the request was denied" look
    the same to a client, and the difference matters: one is a malformed
    action, the other is the user's answer.
    """

    _create_research(db)
    request = _request(repository)

    with pytest.raises(TierAuthorizationDenied):
        repository.approve(request.request_id, approver="user-1", now=_now())

    assert repository.authorization(request.request_id) is None
    assert repository.requests_for(RESEARCH)[0].status == "pending"


def test_a_fully_specified_approval_is_still_accepted(repository, db):
    """The positive side, so the guard cannot be "implemented" by refusing
    every approval - which would be an outage, not a guard.
    """

    _create_research(db)
    request = _request(repository)

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
    assert decision.valid_until != ""
    assert decision.max_calls == 10
    assert decision.max_cost == 1.25


# --- hole 2: the research's own operation identity is never checked ------------------------


def test_an_approval_for_another_operation_identity_on_the_same_research_is_refused(
    repository, db
):
    """The authorisation's operation must match the *research's* operation.

    The old check compared the authorisation against the caller's argument.
    The research row carries its own ``operation_id``, and it was read from
    the database and then never looked at.

    So the hole was: approve an upgrade for operation-B, then call
    ``apply_upgrade`` with operation-B, on a research that belongs to
    operation-A. Every check passed, and a research running under a
    different operation identity got a tier upgrade it never earned.
    """

    _create_research(db, RESEARCH, operation_id=OPERATION)
    request = _request(repository, operation_id="operation-B")
    repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    with pytest.raises(TierAuthorizationDenied) as refused:
        repository.apply_upgrade(RESEARCH, operation_id="operation-B", now=_now())

    assert refused.value.reason == "operation_mismatch"


def test_the_upgrade_leaves_the_tier_untouched_when_the_identity_does_not_match(
    repository, db
):
    """The refusal has to be a refusal, not a warning.

    A guard that raised after the tier had already been written would be
    worse than no guard: the caller sees an error and believes nothing
    happened, while the research has quietly become more expensive.
    """

    _create_research(db, RESEARCH, operation_id=OPERATION)
    request = _request(repository, operation_id="operation-B")
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
        repository.apply_upgrade(RESEARCH, operation_id="operation-B", now=_now())

    state = ResearchStateRepository(db).load(RESEARCH)
    assert state is not None
    assert state.tier == "standard"
    assert state.tier_upgrade_authorized is False


# --- hole 3: the final write had no state condition ----------------------------------------


def test_a_cancellation_landing_inside_the_race_window_blocks_the_upgrade(db):
    """The write must carry the conditions - not just the read before it.

    This is the actual race. The old implementation read the state, checked
    it, and then wrote with ``WHERE research_id = ?`` - no condition. A
    cancellation that landed between the read and the write was invisible
    to the check (it had not happened yet) and unconstrained by the write
    (the write did not care), so **both** succeeded: the research was
    cancelled *and* upgraded.

    The contract (§11.1) is explicit: "取消之后**不得**：提交新请求、升档、
    发布过期结果". The upgrade must not happen.

    **How the race is opened deterministically.** SQLite's authorizer
    callback fires while a statement is being compiled - that is, after
    the read-side checks have passed and before the write executes. The
    test installs an authorizer that, at exactly that moment, commits a
    cancellation from a *second, independent connection*.

    That is a real concurrent writer, not a mock: it goes through the same
    ``research_states`` row, the same table, and the same commit path the
    production cancellation uses. And it lands in the one place the old
    implementation was unprotected.

    Without the fix, this test fails with the tier upgraded *and* the
    research cancelled - the exact shape of the defect.
    """

    import sqlite3

    states = _create_research(db)
    repository = ResearchTierRepository(db)
    request = _request(repository)
    repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    raced = []

    def cancel_during_the_write(action, arg1, arg2, dbname, trigger):
        # SQLITE_UPDATE on research_states, column "tier": the write we care
        # about. The cancellation itself runs on another connection, so it
        # is not seen by this authorizer.
        if action == sqlite3.SQLITE_UPDATE and arg1 == "research_states" and arg2 == "tier":
            if not raced:
                raced.append(True)
                other = sqlite3.connect(db.path)
                try:
                    other.execute(
                        "UPDATE research_states SET cancel_requested_at = ?, "
                        "status = 'cancelled', stop_reason = 'user_cancelled' "
                        "WHERE research_id = ?",
                        (_now(), RESEARCH),
                    )
                    other.commit()
                finally:
                    other.close()
        return sqlite3.SQLITE_OK

    original_connect = db.connect

    def connect_with_authorizer():
        connection = original_connect()
        connection.set_authorizer(cancel_during_the_write)
        return connection

    db.connect = connect_with_authorizer  # type: ignore[method-assign]

    try:
        with pytest.raises(TierAuthorizationDenied):
            repository.apply_upgrade(RESEARCH, operation_id=OPERATION, now=_now())
    finally:
        db.connect = original_connect  # type: ignore[method-assign]

    assert raced, "the race window was never entered - the test proved nothing"

    state = states.load(RESEARCH)
    assert state is not None
    # The cancellation stands, and the tier did not move.
    assert state.status == "cancelled"
    assert state.tier == "standard"
    assert state.tier_upgrade_authorized is False


def test_a_cancellation_landing_before_the_call_blocks_the_upgrade(repository, db):
    """The easy half of the same race: the cancellation is already committed.

    This one is not the interesting case - it is here so the refusal reason
    is pinned. A caller has to be able to tell "this research was cancelled"
    from "the state moved under me", because the two mean different things.
    """

    states = _create_research(db)
    request = _request(repository)
    repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    # The cancellation is committed before the upgrade is attempted, so the
    # read-side check sees it. This is the *easy* half of the race, and it
    # is the half that proves the write-side condition is what closes it.
    states.cancel(RESEARCH, reason="user_cancelled")

    with pytest.raises(TierAuthorizationDenied) as refused:
        repository.apply_upgrade(RESEARCH, operation_id=OPERATION, now=_now())

    assert refused.value.reason == "research_cancelled"
    state = states.load(RESEARCH)
    assert state.tier == "standard"


def test_a_research_that_stopped_on_its_own_cannot_be_upgraded(repository, db):
    """The same for a policy stop: a terminal research stays terminal.

    A research that stopped because it ran out of progress, or because it
    had enough evidence, is finished. Giving it a higher spending tier
    afterwards is not a permission - it is spending on a research nobody is
    going to read.
    """

    states = _create_research(db)
    request = _request(repository)
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
        connection.execute(
            "UPDATE research_states SET status = 'stopped', stop_reason = 'no_progress' "
            "WHERE research_id = ?",
            (RESEARCH,),
        )

    with pytest.raises(TierAuthorizationDenied) as refused:
        repository.apply_upgrade(RESEARCH, operation_id=OPERATION, now=_now())

    assert refused.value.reason == "research_terminal"
    state = states.load(RESEARCH)
    assert state.tier == "standard"


def test_the_upgrade_writes_the_tier_when_everything_is_in_order(repository, db):
    """The positive side of the same rule.

    A write with conditions is a write that can refuse. If it refused
    everything, the guard would be indistinguishable from a broken feature.
    """

    _create_research(db)
    request = _request(repository)
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


# --- the ceiling is actually enforced -------------------------------------------------------


def test_an_upgrade_beyond_the_approved_ceiling_is_refused(repository, db):
    """The contract: "授权的**费用/调用上限**足以覆盖这次升档".

    This check existed, but no test ever reached it: every call site
    passed the default ``calls=0`` / ``cost=0.0``, so the refusal branch
    had never been executed. A guard nobody has run is not a guard.
    """

    _create_research(db)
    request = _request(repository)
    repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    with pytest.raises(TierAuthorizationDenied) as refused:
        repository.apply_upgrade(
            RESEARCH, operation_id=OPERATION, calls=11, cost=0.0, now=_now()
        )

    assert refused.value.reason == "authorization_too_small"
    state = ResearchStateRepository(db).load(RESEARCH)
    assert state.tier == "standard"


def test_an_upgrade_within_the_approved_ceiling_is_allowed(repository, db):
    """The other side of the same ceiling: exactly at the limit is allowed.

    "Sufficient to cover" means *at least*, not *more than*.
    """

    _create_research(db)
    request = _request(repository)
    repository.approve(
        request.request_id,
        approver="user-1",
        scope="this research only",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    state = repository.apply_upgrade(
        RESEARCH, operation_id=OPERATION, calls=10, cost=1.25, now=_now()
    )

    assert state.tier == "deep"


# --- cancellation is a terminal decision, and a terminal decision is final -------------------


def test_a_cancellation_does_not_overwrite_a_stop_that_already_happened(db):
    """A research that stopped on its own keeps its own reason.

    The contract (Q-7) asks for four **distinguishable** stop reasons:
    evidence sufficient / budget exhausted / no viable query / user
    cancelled. They are only distinguishable if the one that actually
    happened is the one that stays.

    ``cancel()`` wrote ``WHERE research_id = ?`` - no status condition - so
    a cancellation arriving after a policy stop overwrote the reason with
    ``user_cancelled``. The research had stopped for lack of progress, and
    the record then said the user cancelled it. Nothing was wrong with the
    cancellation; it was simply **late**, and a late decision must not
    rewrite an earlier one.
    """

    states = _create_research(db)

    with db.connect() as connection:
        connection.execute(
            "UPDATE research_states SET status = 'stopped', "
            "stop_reason = 'no_information_gain' WHERE research_id = ?",
            (RESEARCH,),
        )

    state = states.cancel(RESEARCH, reason="user_cancelled")

    # The earlier decision stands.
    assert state.status == "stopped"
    assert state.stop_reason == "no_information_gain"


def test_a_cancellation_does_not_overwrite_a_failure(db):
    """The same for a failure: a failure is a fact, not a decision to be
    revised.

    A research that failed did not fail because the user cancelled it. If
    the cancellation were allowed to overwrite the status, the reason a
    research died would be whatever the last writer happened to be.
    """

    states = _create_research(db)

    with db.connect() as connection:
        connection.execute(
            "UPDATE research_states SET status = 'failed', "
            "stop_reason = 'executor_crashed' WHERE research_id = ?",
            (RESEARCH,),
        )

    state = states.cancel(RESEARCH, reason="user_cancelled")

    assert state.status == "failed"
    assert state.stop_reason == "executor_crashed"


def test_a_cancellation_of_a_running_research_still_records_the_decision(db):
    """The positive side: a cancellation that is *not* late still happens.

    Without this, the guard could be "implemented" by refusing every
    cancellation - which would leave the user's decision unenforced.
    """

    states = _create_research(db)

    state = states.cancel(RESEARCH, reason="user_cancelled")

    assert state.status == "cancelled"
    assert state.stop_reason == "user_cancelled"
    assert state.cancel_requested_at != ""


def test_a_cancellation_of_an_already_cancelled_research_is_idempotent(db):
    """Cancelling twice is not an error and does not move the decision.

    The user may click cancel twice, or a retry may re-send it. The
    recorded decision - when it was made - must not drift because of that.
    """

    states = _create_research(db)

    first = states.cancel(RESEARCH, reason="user_cancelled")
    second = states.cancel(RESEARCH, reason="user_cancelled")

    assert second.status == "cancelled"
    assert second.stop_reason == "user_cancelled"
    # The decision's timestamp is the first one, not a later one.
    assert second.cancel_requested_at == first.cancel_requested_at


# --- hole 4: a ceiling that cannot be compared is not a ceiling ---------------------------


def test_an_approval_with_an_infinite_cost_ceiling_is_refused(repository, db):
    """``float('inf')`` is a real float, so the old checks accepted it.

    ``max_cost <= 0`` is False for infinity, and ``value < 0`` is False for
    infinity, so the ceiling check that was supposed to bound the grant let
    it through. The consequence was not a large ceiling - it was an
    *unbounded* one: every later comparison against infinity is False, so
    ``cost > self.max_cost`` never fired and the grant covered every spend,
    including spends larger than any budget the user could have imagined.

    The contract says the ceiling must be "足以覆盖这次升档" - sufficient to
    cover this upgrade. A ceiling that covers everything covers nothing in
    particular, so it is not a ceiling at all.
    """

    _create_research(db)
    request = _request(repository)

    with pytest.raises(TierAuthorizationDenied) as refused:
        repository.approve(
            request.request_id,
            approver="user-1",
            scope="this research only",
            valid_until=_now(3600),
            max_calls=10,
            max_cost=float("inf"),
            now=_now(),
        )

    assert refused.value.reason == "authorization_non_finite_ceiling"


def test_an_approval_with_a_nan_cost_ceiling_is_refused(repository, db):
    """NaN is quieter than infinity, and that is why it needs its own case.

    Every comparison against NaN is False - not just the upper one. So
    ``max_cost <= 0`` is False, ``value < 0`` is False, and later
    ``cost > self.max_cost`` is False as well. An infinity ceiling at least
    fails one comparison somewhere; NaN fails every comparison, including
    the ones a reviewer would reach for first.
    """

    _create_research(db)
    request = _request(repository)

    with pytest.raises(TierAuthorizationDenied) as refused:
        repository.approve(
            request.request_id,
            approver="user-1",
            scope="this research only",
            valid_until=_now(3600),
            max_calls=10,
            max_cost=float("nan"),
            now=_now(),
        )

    assert refused.value.reason == "authorization_non_finite_ceiling"


def test_an_approval_with_an_infinite_call_ceiling_is_refused(repository, db):
    """The call ceiling has the same shape and gets the same refusal.

    ``max_calls`` is typed as an int, so infinity cannot arrive as an int -
    but it can arrive as a float, and a float that happens to be integral
    would otherwise be accepted. The check states the finiteness question
    rather than relying on the annotation.
    """

    _create_research(db)
    request = _request(repository)

    with pytest.raises(TierAuthorizationDenied) as refused:
        repository.approve(
            request.request_id,
            approver="user-1",
            scope="this research only",
            valid_until=_now(3600),
            max_calls=float("inf"),
            max_cost=1.25,
            now=_now(),
        )

    assert refused.value.reason == "authorization_non_finite_ceiling"


def test_a_refused_non_finite_approval_leaves_the_request_pending(repository, db):
    """The refusal happens before anything is written.

    A malformed approval must not leave a decision behind, and the request
    stays ``pending`` - which is not the same as a denial, because the user
    never said no.
    """

    _create_research(db)
    request = _request(repository)

    with pytest.raises(TierAuthorizationDenied):
        repository.approve(
            request.request_id,
            approver="user-1",
            scope="this research only",
            valid_until=_now(3600),
            max_calls=10,
            max_cost=float("inf"),
            now=_now(),
        )

    stored = repository.authorization(request.request_id)
    assert stored is None
    assert repository.requests_for(RESEARCH)[0].status == "pending"


def test_a_record_with_an_infinite_ceiling_cannot_even_be_built():
    """The domain object refuses a ceiling it cannot compare.

    ``covers()`` is where the upgrade path finally asks "does this grant
    cover this spend", but the record does not get that far: constructing it
    with an infinite ceiling raises, because a ceiling that cannot be
    compared is not a ceiling. The dataclass check is the *first* line -
    a record with a non-finite ceiling cannot exist to be evaluated.

    The assertion is on the construction, not on ``covers()``, because that
    is the order the defence actually takes: refuse the value at the
    boundary rather than reason about it later.
    """

    from src.domain.research_authorization import TierAuthorization

    with pytest.raises(ValueError, match="invalid_max_cost"):
        TierAuthorization(
            request_id="request-1",
            research_id=RESEARCH,
            operation_id=OPERATION,
            status="approved",
            approver="user-1",
            valid_until=_now(3600),
            max_calls=10,
            max_cost=float("inf"),
        )


def test_a_record_with_a_nan_ceiling_cannot_even_be_built():
    """NaN fails every comparison, so it is refused at construction too."""

    from src.domain.research_authorization import TierAuthorization

    with pytest.raises(ValueError, match="invalid_max_cost"):
        TierAuthorization(
            request_id="request-1",
            research_id=RESEARCH,
            operation_id=OPERATION,
            status="approved",
            approver="user-1",
            valid_until=_now(3600),
            max_calls=10,
            max_cost=float("nan"),
        )


def test_covers_refuses_a_non_finite_spend_even_under_a_finite_ceiling():
    """The spend itself must be finite too, not only the ceiling.

    A grant with a sane ceiling still has to answer "does this cover this
    spend" about a spend that is not a number. ``cost=inf`` and
    ``cost=nan`` both fail every comparison, so a guard that only checked
    the ceiling would let them through - and an infinite cost is exactly
    the case where the ceiling must refuse.
    """

    from src.domain.research_authorization import TierAuthorization

    record = TierAuthorization(
        request_id="request-1",
        research_id=RESEARCH,
        operation_id=OPERATION,
        status="approved",
        approver="user-1",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
    )

    assert record.covers(1, 0.5) is True
    assert record.covers(1, float("inf")) is False
    assert record.covers(1, float("nan")) is False
    assert record.covers(float("inf"), 0.5) is False
    assert record.covers(float("nan"), 0.5) is False


def test_a_normal_ceiling_still_covers_a_spend_inside_it(repository, db):
    """The guard must not be "implemented" by refusing everything.

    A finite ceiling still covers what it says it covers, and the amount
    that is refused is still refused. If this test fails, the guard has
    become a blanket denial.
    """

    from src.domain.research_authorization import TierAuthorization

    record = TierAuthorization(
        request_id="request-1",
        research_id=RESEARCH,
        operation_id=OPERATION,
        status="approved",
        approver="user-1",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
    )

    assert record.covers(1, 0.5) is True
    assert record.covers(10, 1.25) is True
    assert record.covers(11, 1.25) is False
    assert record.covers(10, 1.26) is False
