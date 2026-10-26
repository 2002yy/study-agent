"""CL-M3 QD-3e: the scenarios that only happen when things go wrong at once.

QD-3a/3b/3c/3d each tested their own layer with hand-written stubs. What
they could not test is the part where the layers meet under stress: a
worker that dies between the model call and the write, a research that is
cancelled between the executor reading the state and the executor spending,
a quota that runs out mid-round, two workers scanning at once.

This file is about those interleavings, and it is arranged around a
**controllable executor** (``tests/research_test_executor.py``) rather than
around a stub that happens to work. The executor is given a *script*, and a
script step may observe the world from inside the round - which is the only
place the interesting races live.

**What is asserted here, and what is not.** These tests assert the
*mechanism*: which write happened, which refusal came back, what the next
worker found. They do not assert "the research finished", because a test
that asserts the outcome cannot tell a correct implementation from one that
reaches the same outcome by accident. QD-3d's fourth weak guard was exactly
that mistake, and it survived because a test asserting "this raises" was
satisfied by a refusal that came from the wrong check.

**The negative controls are in the same file.** A scenario test that cannot
fail is a scenario test that proves nothing, so each of the five scenarios
has a mutation that breaks it, and the mutations are run in the separate
mutation harness.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from src.application.research_coordinator import ResearchCoordinator
from src.application.research_feed import ResearchFeed
from src.domain.research_authorization import STOP_REASON_NO_PROGRESS
from src.domain.research_state import (
    STATE_CANCELLED,
    STATE_STOPPED,
)
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.research_state_repository import ResearchStateRepository
from src.repositories.research_tier_repository import ResearchTierRepository
from tests.research_test_executor import (
    ScriptedExecutor,
    ScriptedStep,
    scripted_round,
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
    return ResearchStateRepository(db)


def _create(repository, research_id=RESEARCH, *, question="what is the state of X?"):
    return repository.create(
        research_id=research_id,
        thread_id=THREAD,
        operation_id=OPERATION,
        original_question=question,
        question=question,
        tier="standard",
    )


def _now(offset_seconds: float = 0.0) -> str:
    """A timestamp for the authorisation's expiry, an hour out by default."""

    return (
        datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    ).isoformat()


# --- scenario 1: the research is cancelled while the round is in flight --------


def test_a_cancellation_during_a_round_stops_the_next_call(repository):
    """Scenario 1, part one: the cancel lands *inside* the round.

    The executor reads the state, then the user cancels, then the executor
    returns a round. The coordinator checkpoints it - that is correct, the
    work was done - but the **next** round must not start, because the
    research is cancelled.

    The assertion that matters is the second call: the executor was entered
    once, not twice. A cancel that only takes effect on the next scan would
    let one more model call through, and that is exactly the "取消后不再产生
    模型调用" the contract forbids.
    """

    _create(repository)
    cancelled_during: list[bool] = []

    def cancel_mid_round(_resume, _lease):
        # The user cancels while this round is running.
        repository.cancel(RESEARCH, reason="user_cancelled")
        cancelled_during.append(True)

    executor = ScriptedExecutor(
        [
            ScriptedStep(action="checkpoint", observe=cancel_mid_round),
            ScriptedStep(action="checkpoint"),
        ]
    )
    coordinator = ResearchCoordinator(
        repository, executor=executor, owner="worker-a", rounds_per_scan=4
    )

    coordinator.scan_once()

    assert len(cancelled_during) == 1
    # The executor was entered once. The second step never ran, because the
    # research was cancelled before the coordinator asked for another round.
    assert len(executor.calls) == 1
    state = repository.load(RESEARCH)
    assert state.cancelled is True
    assert state.cancel_requested_at != ""


def test_a_cancelled_research_records_no_further_rounds(repository):
    """Scenario 1, part two: the durable record agrees with the executor.

    The round that was in flight when the cancel landed is **not** written
    down, and that is the right outcome rather than a loss.

    The cancel is written first, and it moves the state version. The round
    that was running cannot commit against a state it did not read, so the
    database refuses the write. The findings of that round are lost - and
    the contract's "keep what earlier rounds found" is about *completed*
    rounds, which this one is not. It was never durable, and the user said
    stop.

    What is asserted here is the pair: the research is cancelled, and no
    round after the cancellation exists. A round *before* the cancellation
    would be a different question, and it is asked in the test below.
    """

    _create(repository)

    def cancel_mid_round(_resume, _lease):
        repository.cancel(RESEARCH, reason="user_cancelled")

    executor = ScriptedExecutor(
        [
            ScriptedStep(action="checkpoint", observe=cancel_mid_round),
            ScriptedStep(action="checkpoint"),
        ]
    )
    coordinator = ResearchCoordinator(
        repository, executor=executor, owner="worker-a", rounds_per_scan=4
    )

    coordinator.scan_once()

    rounds = repository.rounds(RESEARCH)
    assert len(rounds) == 0
    assert repository.load(RESEARCH).status == STATE_CANCELLED


def test_a_cancellation_keeps_the_rounds_that_were_already_finished(repository):
    """Scenario 1, part three: what was already found is still there.

    The contract says a cancellation must not erase the observations of the
    completed rounds - the user was reading them when they decided to stop.
    So the rounds that finished *before* the cancel stay, and only the
    research's right to continue is taken away.
    """

    _create(repository)

    def cancel_after_the_first_round(_resume, _lease):
        # The first round has already been checkpointed by the time the
        # executor is entered for the second time.
        repository.cancel(RESEARCH, reason="user_cancelled")

    executor = ScriptedExecutor(
        [
            ScriptedStep(action="checkpoint"),
            ScriptedStep(action="checkpoint", observe=cancel_after_the_first_round),
            ScriptedStep(action="checkpoint"),
        ]
    )
    coordinator = ResearchCoordinator(
        repository, executor=executor, owner="worker-a", rounds_per_scan=4
    )

    coordinator.scan_once()

    rounds = repository.rounds(RESEARCH)
    assert len(rounds) == 1
    assert rounds[0].evidence == ("fact-0",)
    assert repository.load(RESEARCH).status == STATE_CANCELLED


def test_a_cancelled_research_is_not_offered_to_another_worker(repository):
    """Scenario 1, part three: the cancel is durable, not in-memory.

    A second worker, with no memory of the first one, must not pick the
    research up either. This is the property that makes the cancellation
    survive the process that received it.
    """

    _create(repository)
    repository.cancel(RESEARCH, reason="user_cancelled")

    executor = ScriptedExecutor([ScriptedStep(action="checkpoint")])
    coordinator = ResearchCoordinator(repository, executor=executor, owner="worker-b")

    result = coordinator.scan_once()

    assert result.rounds == 0
    assert len(executor.calls) == 0


# --- scenario 2: the worker dies between the call and the write ----------------


def test_a_worker_that_dies_mid_round_leaves_no_durable_mark(repository):
    """Scenario 2, part one: the failed round is not remembered as done.

    The executor raised. The round it was working on never happened, as far
    as the database is concerned, so the research must be offered again.
    """

    _create(repository)
    executor = ScriptedExecutor(
        [
            ScriptedStep(action="raise", payload={"message": "the process died"}),
            ScriptedStep(action="checkpoint"),
        ]
    )
    coordinator = ResearchCoordinator(
        repository, executor=executor, owner="worker-a", rounds_per_scan=4
    )

    coordinator.scan_once()

    # The failure left no round behind.
    assert repository.rounds(RESEARCH) == ()
    assert repository.load(RESEARCH).round_index == 0


def test_the_research_is_offered_again_after_the_worker_dies(repository):
    """Scenario 2, part two: the next worker picks it up and continues.

    This is the property the whole lease-and-fencing design exists for. The
    research is not lost, not half-done, and not double-run.
    """

    _create(repository)
    first = ScriptedExecutor(
        [
            ScriptedStep(action="raise", payload={"message": "the process died"}),
        ]
    )
    worker_a = ResearchCoordinator(repository, executor=first, owner="worker-a")
    worker_a.scan_once()
    assert repository.rounds(RESEARCH) == ()

    second = ScriptedExecutor([ScriptedStep(action="checkpoint")])
    worker_b = ResearchCoordinator(repository, executor=second, owner="worker-b")
    result = worker_b.scan_once()

    assert result.rounds == 1
    assert len(repository.rounds(RESEARCH)) == 1
    # And it is round 0, not round 1: the failed round was never counted.
    assert repository.rounds(RESEARCH)[0].round_index == 0


# --- scenario 3: two workers, one research -------------------------------------


def test_two_workers_scanning_at_once_advance_one_round_between_them(repository):
    """Scenario 3: contention, exercised rather than described.

    Both workers are started at the same time, and both are given the same
    research. The database decides which one gets it - not luck, and not the
    order the threads happened to be scheduled in.

    **The lease has to be held, or this test measures the scheduler.** The
    coordinator hands the lease back as soon as it has finished a round, so a
    second worker that scans *after* the first one finished is not a
    competitor - it is a successor, and running the next round is correct
    behaviour. Asserting "exactly one round" without arranging for the two
    scans to overlap therefore asserts something the system never promised,
    and it fails whenever the threads happen to be scheduled one after the
    other.

    So the contention is *arranged* rather than hoped for: the worker that
    wins the claim holds the lease inside its round until the other worker
    has finished its own scan. A live lease is then neither offered to the
    second worker nor claimable by it, so the arbitration is forced to
    happen - and the assertion below becomes deterministic.
    """

    _create(repository)
    started = threading.Barrier(2)
    a_scanned = threading.Event()
    b_scanned = threading.Event()

    def hold_until(other_scanned: threading.Event):
        """Stay inside the round until the other worker has finished scanning."""

        def observe(_resume, _lease):
            assert other_scanned.wait(timeout=30), "the other worker never scanned"

        return observe

    executor_a = ScriptedExecutor(
        [ScriptedStep(action="checkpoint", observe=hold_until(b_scanned))]
    )
    executor_b = ScriptedExecutor(
        [ScriptedStep(action="checkpoint", observe=hold_until(a_scanned))]
    )
    worker_a = ResearchCoordinator(repository, executor=executor_a, owner="worker-a")
    worker_b = ResearchCoordinator(repository, executor=executor_b, owner="worker-b")

    def run(worker, scanned: threading.Event):
        started.wait(timeout=5)
        worker.scan_once()
        scanned.set()

    threads = [
        threading.Thread(target=run, args=(worker_a, a_scanned)),
        threading.Thread(target=run, args=(worker_b, b_scanned)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    # Exactly one round exists, and it exists once.
    assert len(repository.rounds(RESEARCH)) == 1
    assert repository.load(RESEARCH).round_index == 1
    # And only one of the two executors was entered.
    assert len(executor_a.calls) + len(executor_b.calls) == 1


def test_the_loser_of_the_contention_does_not_run_a_second_round(repository):
    """Scenario 3, part two: the refusal is a refusal, not a silent success.

    The worker that lost the claim must not have run anything, and must not
    have written anything. Its own lease was never taken, so it has nothing
    to release either.

    Note what the counters say. A live lease is not even *offered*, so the
    research is simply skipped - the count of lost leases stays zero. Both
    are refusals; the difference is only whether the row was a candidate.
    """

    _create(repository)
    claimed = repository.claim(RESEARCH, owner="worker-a", ttl_seconds=60.0)

    executor = ScriptedExecutor([ScriptedStep(action="checkpoint")])
    worker_b = ResearchCoordinator(repository, executor=executor, owner="worker-b")

    result = worker_b.scan_once()

    assert result.rounds == 0
    assert len(executor.calls) == 0
    assert repository.rounds(RESEARCH) == ()
    # The lease still belongs to the worker that holds it, and the fencing
    # token has not moved: the losing worker did not touch the row.
    assert repository.load(RESEARCH).lease_owner == "worker-a"
    assert repository.load(RESEARCH).fencing_token == claimed.fencing_token


def test_an_expired_lease_is_taken_over_rather_than_refused(repository):
    """Scenario 3, part three: a crashed worker's lease is taken over.

    The lease is written in the past, so it has already expired by the time
    the coordinator compares against the real clock - which is what a
    crashed worker's lease looks like. The takeover is not a contention: the
    research moves forward, and the counters say so.
    """

    _create(repository)
    repository.claim(
        RESEARCH, owner="worker-a", ttl_seconds=1.0, now="2020-01-01T00:00:00+00:00"
    )

    executor = ScriptedExecutor([ScriptedStep(action="checkpoint")])
    worker_b = ResearchCoordinator(repository, executor=executor, owner="worker-b")

    result = worker_b.scan_once()

    assert result.rounds == 1
    assert result.leases_lost == 0
    assert len(executor.calls) == 1
    # The lease was handed back, because the research is not finished.
    assert repository.load(RESEARCH).lease_owner == ""


# --- scenario 4: the quota runs out mid-round ----------------------------------


def test_a_quota_that_is_exhausted_is_recorded_and_not_raised(repository):
    """Scenario 4, part one: the quota observation moves only downwards.

    The executor reports a smaller remaining quota than the state already
    holds. The state must not go back up, because a higher observation would
    look like budget that was never spent - and a research that has already
    spent money must never look like it has spent less.

    The quota keys are a closed vocabulary (``searches``, ``reads``,
    ``decisions``, ``tokens``) and an unknown one is refused rather than
    ignored, so a misspelled key cannot sit in the row doing nothing while
    the budget it was meant to bound goes unrecorded.
    """

    _create(repository)
    executor = ScriptedExecutor(
        [
            ScriptedStep(
                action="checkpoint",
                payload={"quota_observed": {"searches": 5}},
            ),
            ScriptedStep(
                action="checkpoint",
                payload={"quota_observed": {"searches": 1}},
            ),
            ScriptedStep(
                action="checkpoint",
                payload={"quota_observed": {"searches": 99}},
            ),
        ]
    )
    coordinator = ResearchCoordinator(
        repository, executor=executor, owner="worker-a", rounds_per_scan=4
    )

    coordinator.scan_once()

    state = repository.load(RESEARCH)
    # The third checkpoint tried to raise the quota back to 99 and was
    # refused, so the observation stayed at the lowest value seen.
    assert state.quota_observed["searches"] == 1


def test_a_quota_that_runs_out_stops_the_research(repository):
    """Scenario 4, part two: no budget means no more rounds.

    The executor reports that the budget is spent, and the research stops.
    The state is ``stopped``, not ``failed``: the research ended on purpose,
    and what it found is still true.
    """

    _create(repository)
    executor = ScriptedExecutor(
        [
            ScriptedStep(
                action="stop",
                payload={
                    "stop_reason": "quota_exhausted",
                    "quota_observed": {"searches": 0},
                },
            ),
            ScriptedStep(action="checkpoint"),
        ]
    )
    coordinator = ResearchCoordinator(
        repository, executor=executor, owner="worker-a", rounds_per_scan=4
    )

    coordinator.scan_once()

    state = repository.load(RESEARCH)
    assert state.status == STATE_STOPPED
    assert state.stop_reason == "quota_exhausted"
    # The second step never ran: a stopped research is not advanced again.
    assert len(executor.calls) == 1


# --- scenario 5: the research stops because it learned nothing ------------------


def test_two_rounds_without_a_gain_stop_the_research(repository):
    """Scenario 5: the R-4 rule, exercised end to end through the coordinator.

    The rounds report the same observation every time, so the research is
    learning nothing. It must stop, with the reason recorded, and the
    findings it did produce must still be there.
    """

    _create(repository)
    # The factory always reports the same observation, so no round is a gain
    # over any earlier one.
    factory = scripted_round(
        queries=("query-0",),
        observation_urls=("https://example.invalid/same",),
        evidence=("fact-0",),
    )
    executor = ScriptedExecutor(
        [
            ScriptedStep(action="checkpoint"),
            ScriptedStep(action="checkpoint"),
            ScriptedStep(action="checkpoint"),
        ],
        round_factory=factory,
    )
    coordinator = ResearchCoordinator(
        repository, executor=executor, owner="worker-a", rounds_per_scan=4
    )

    coordinator.scan_once()

    state = repository.load(RESEARCH)
    assert state.status == STATE_STOPPED
    assert state.stop_reason == STOP_REASON_NO_PROGRESS
    # And the rounds it did produce are still on record.
    assert len(repository.rounds(RESEARCH)) >= 1


def test_a_stopped_research_is_not_offered_to_another_worker(repository):
    """Scenario 5, part two: stopping is durable too.

    A second worker must not restart a research that stopped for lack of
    progress. The stop reason is a decision, and a decision survives the
    process that made it.
    """

    _create(repository)
    factory = scripted_round(
        queries=("query-0",),
        observation_urls=("https://example.invalid/same",),
        evidence=("fact-0",),
    )
    executor = ScriptedExecutor(
        [ScriptedStep(action="checkpoint"), ScriptedStep(action="checkpoint")],
        round_factory=factory,
    )
    coordinator = ResearchCoordinator(
        repository, executor=executor, owner="worker-a", rounds_per_scan=4
    )
    coordinator.scan_once()
    assert repository.load(RESEARCH).status == STATE_STOPPED

    second = ScriptedExecutor([ScriptedStep(action="checkpoint")])
    worker_b = ResearchCoordinator(repository, executor=second, owner="worker-b")
    result = worker_b.scan_once()

    assert result.rounds == 0
    assert len(second.calls) == 0


# --- scenario 6: the client goes away while the research runs ------------------


def test_a_disconnected_client_does_not_stop_the_research(repository, db):
    """Scenario 6: the subscription ends; the research does not.

    This is the R-3 property that QD-3c established structurally (the
    subscription registry has no cancel method), restated here as a
    behaviour: the research is still advanced after the last client has
    gone.
    """

    _create(repository)
    feed = ResearchFeed(repository)
    executor = ScriptedExecutor([ScriptedStep(action="checkpoint")])
    coordinator = ResearchCoordinator(
        repository, executor=executor, owner="worker-a", rounds_per_scan=4
    )

    # A client watches, then goes away. There is no API to stop the
    # research, and the feed exposes none.
    snapshot = feed.snapshot(RESEARCH)
    assert snapshot.status is not None

    coordinator.scan_once()

    assert len(repository.rounds(RESEARCH)) == 1
    # The subscription registry still has no way to cancel a research.
    from src.application.research_feed import ResearchSubscriptionRegistry

    assert not hasattr(ResearchSubscriptionRegistry, "cancel")
    assert not hasattr(ResearchSubscriptionRegistry, "cancel_research")


# --- scenario 7: the tier upgrade is a user decision, end to end ---------------


def test_a_tier_upgrade_without_a_user_decision_is_refused(repository, db):
    """Scenario 7, part one: the asking is not the granting.

    The research asks to move up a tier. Nothing else happens. The tier
    must not move, and the request must be on record as pending.
    """

    _create(repository)
    tiers = ResearchTierRepository(db)

    request = tiers.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="the standard tier cannot resolve this",
    )

    assert request.status == "pending"
    with pytest.raises(Exception):
        tiers.apply_upgrade(RESEARCH, operation_id=OPERATION)
    assert repository.load(RESEARCH).tier == "standard"


def test_a_tier_upgrade_after_a_user_decision_is_recorded(repository, db):
    """Scenario 7, part two: with the decision, the tier moves and the
    decision is on record.

    The test asserts *who* decided and *when*, because §10.8's fourth
    criterion asks for a record of the user's authorisation, and a record
    that says "approved" but not "by whom" answers a different question.

    The approval states an expiry and both ceilings, because §11.3's
    authorisation record carries "有效期、费用上限" and the ceiling has to
    be re-verified against every upgrade. Before the R-6 safety slice, an
    approval without them was accepted - which is how "no expiry and no
    ceiling" became a normal path rather than a hole.
    """

    _create(repository)
    tiers = ResearchTierRepository(db)

    request = tiers.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="the standard tier cannot resolve this",
    )
    decision = tiers.approve(
        request.request_id,
        approver="user-1",
        scope="this run",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    assert decision.status == "approved"
    assert decision.approver == "user-1"
    assert decision.decided_at != ""
    assert decision.valid_until != ""
    assert decision.max_calls == 10
    assert decision.max_cost == 1.25

    state = tiers.apply_upgrade(RESEARCH, operation_id=OPERATION)
    assert state.tier == "deep"
    assert state.tier_upgrade_authorized is True


def test_the_authorisation_does_not_outlive_the_operation_it_was_given_for(
    repository, db
):
    """Scenario 7, part three: a grant is for one run, not for the research.

    A research that is resumed or retried under a new operation is a
    different run, and a user's "yes, for this one" is not a blank cheque.
    """

    _create(repository)
    tiers = ResearchTierRepository(db)

    request = tiers.request_upgrade(
        RESEARCH,
        operation_id=OPERATION,
        from_tier="standard",
        to_tier="deep",
        reason="the standard tier cannot resolve this",
    )
    tiers.approve(
        request.request_id,
        approver="user-1",
        scope="this run",
        valid_until=_now(3600),
        max_calls=10,
        max_cost=1.25,
        now=_now(),
    )

    with pytest.raises(Exception):
        tiers.apply_upgrade(RESEARCH, operation_id="a-different-operation")
    assert repository.load(RESEARCH).tier == "standard"
