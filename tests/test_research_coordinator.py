"""CL-M3 QD-3b: the coordinator that advances a research across a process boundary.

What these tests are actually about is the seam between two workers. Everything the
coordinator does is small and mechanical - discover, claim, run a round, checkpoint,
release - and all of it would be easy to get wrong in the one place that matters:
when two processes believe they own the same research.

So the tests are arranged around contention rather than around the happy path.

- The database decides, not the caller. Two coordinators scanning the same rows
  produce one winner, and the loser learns it from the repository's refusal.
- A taken-over worker's late write is refused, because its fencing token is stale.
  This is the property that makes a crashed worker safe to replace.
- A failed round leaves no durable mark, so the research is rediscovered rather than
  remembered as finished.
- The executor decides when a research ends. The coordinator has no policy of its
  own, because two places answering "is this over" would eventually disagree.
"""

from __future__ import annotations

import threading

import pytest

from src.application.research_coordinator import (
    DEFAULT_LEASE_SECONDS,
    AdvanceOutcome,
    ResearchCoordinator,
    ResearchLease,
)
from src.domain.research_state import (
    STATE_CHECKPOINTED,
    STATE_STOPPED,
    ResearchRound,
)
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.research_state_repository import (
    ResearchLeaseHeld,
    ResearchStateRepository,
    StaleResearchWriter,
)

RESEARCH = "research-1"
THREAD = "thread-1"

# Two moments in the past, far enough from the real clock that a lease written
# there has already expired. This is how a takeover is simulated without waiting:
# the lease is written in the past, so it is expired by the time the coordinator
# compares against the real now - which is what a crashed worker's lease looks
# like. The two moments differ because a takeover must happen *after* the lease
# it replaces expired, and the boundary is exclusive.
EXPIRED_NOW = "2020-01-01T00:00:00+00:00"
EXPIRED_LATER = "2020-01-01T00:00:02+00:00"


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
        operation_id="operation-1",
        original_question=question,
        question=question,
        tier="standard",
    )


def _round(research_id, index, *, question="what is the state of X?", evidence=()):
    return ResearchRound(
        research_id=research_id,
        round_index=index,
        question=question,
        queries=(f"query-{index}",),
        evidence=tuple(evidence),
    )


class RecordingExecutor:
    """An executor that records what it was asked to do and returns one round."""

    def __init__(self, *, stop_after=None, refuse=False, raise_at=None):
        self.calls: list[tuple[int, tuple[str, ...]]] = []
        self.leases: list[ResearchLease] = []
        self.seen_evidence: list[tuple[str, ...]] = []
        self.stop_after = stop_after
        self.refuse = refuse
        self.raise_at = raise_at

    def __call__(self, resume, lease):
        assert isinstance(lease, ResearchLease)
        self.calls.append((resume.next_round_index, resume.executed_queries))
        self.leases.append(lease)
        self.seen_evidence.append(resume.evidence)
        if self.raise_at is not None and len(self.calls) == self.raise_at:
            raise RuntimeError("executor exploded")
        if self.refuse:
            return None
        index = resume.next_round_index
        if self.stop_after is not None and len(self.calls) >= self.stop_after:
            return AdvanceOutcome(
                round_record=_round(resume.state.research_id, index),
                status=STATE_STOPPED,
                stop_reason="evidence_sufficient",
            )
        return AdvanceOutcome(
            round_record=_round(
                resume.state.research_id,
                index,
                evidence=(f"fact-{index}",),
            )
        )


# --- the ordinary path ---------------------------------------------------------------


def test_a_scan_advances_one_research_by_one_round(repository):
    _create(repository)
    executor = RecordingExecutor()
    coordinator = ResearchCoordinator(repository, executor=executor)

    result = coordinator.scan_once()

    assert result.rounds == 1
    assert result.researches == 1
    assert result.finished == 0
    state = repository.load(RESEARCH)
    assert state.round_index == 1
    assert state.status == STATE_CHECKPOINTED
    assert state.evidence == ("fact-0",)
    rounds = repository.rounds(RESEARCH)
    assert len(rounds) == 1
    assert rounds[0].queries == ("query-0",)


def test_a_round_records_its_queries_so_the_next_round_does_not_repeat_them(repository):
    _create(repository)
    executor = RecordingExecutor()
    coordinator = ResearchCoordinator(repository, executor=executor)

    coordinator.scan_once()
    coordinator.scan_once()

    # The second round saw the first round's query, and its own query was new.
    assert executor.calls == [(0, ()), (1, ("query-0",))]
    rounds = repository.rounds(RESEARCH)
    assert [round_.queries for round_ in rounds] == [("query-0",), ("query-1",)]


def test_a_second_round_sees_the_evidence_the_first_round_produced(repository):
    _create(repository)
    executor = RecordingExecutor()
    coordinator = ResearchCoordinator(repository, executor=executor)

    coordinator.scan_once()
    coordinator.scan_once()

    assert executor.seen_evidence == [(), ("fact-0",)]


def test_the_executor_decides_when_a_research_ends(repository):
    _create(repository)
    executor = RecordingExecutor(stop_after=1)
    coordinator = ResearchCoordinator(repository, executor=executor)

    result = coordinator.scan_once()

    assert result.finished == 1
    state = repository.load(RESEARCH)
    assert state.status == STATE_STOPPED
    assert state.stop_reason == "evidence_sufficient"


def test_a_terminal_research_is_not_picked_up_again(repository):
    _create(repository)
    executor = RecordingExecutor(stop_after=1)
    coordinator = ResearchCoordinator(repository, executor=executor)

    coordinator.scan_once()
    result = coordinator.scan_once()

    assert result.researches == 0
    assert len(executor.calls) == 1


def test_the_coordinator_holds_no_state_of_its_own(repository):
    """A second coordinator over the same database continues the same research.

    This is the property that makes a restart free: nothing lives in the first
    coordinator that the second one cannot find in the rows.
    """

    _create(repository)
    first = ResearchCoordinator(repository, executor=RecordingExecutor(), owner="worker-a")
    first.scan_once()

    second = ResearchCoordinator(repository, executor=RecordingExecutor(), owner="worker-b")
    result = second.scan_once()

    assert result.rounds == 1
    state = repository.load(RESEARCH)
    assert state.round_index == 2


# --- contention between two workers ---------------------------------------------------


def test_two_workers_never_advance_the_same_research_at_once(repository):
    """The database picks the winner; the loser is refused, not blocked.

    Both coordinators discover the research. Exactly one claim may succeed, so
    exactly one round may be written by this pair.

    **There are two ways to lose, and they are not the same event.** A worker
    that scans *before* the winner claims sees the research as a candidate and
    is refused by ``claim`` - the repository tells it so, and the refusal is
    counted as ``leases_lost``. A worker that scans *after* the winner has
    claimed never sees the research at all, because a live lease is not
    offered, and it is simply skipped. Both are correct, and which one
    happens depends on which scan reaches the database first.

    So the assertion is about what the pair guarantees, not about which of
    the two refusals occurred: **together they advance the research exactly
    once**, and the loser never wrote a round of its own. Asserting a
    particular counter instead would be asserting the scheduler, and it
    failed on roughly half the runs.
    """

    _create(repository)
    started = threading.Barrier(2)
    a_scanned = threading.Event()
    b_scanned = threading.Event()

    class _HoldingExecutor(RecordingExecutor):
        """An executor that stays inside the round until the other worker is done.

        The wait happens **before** the round is produced, so the lease is
        still held while the other worker scans. Waiting afterwards would be
        too late: the coordinator hands the lease back as soon as the round
        is written down.
        """

        def __init__(self, other_scanned: threading.Event):
            super().__init__()
            self._other_scanned = other_scanned

        def __call__(self, resume, lease):
            assert self._other_scanned.wait(timeout=30), (
                "the other worker never scanned"
            )
            return super().__call__(resume, lease)

    executor_a = _HoldingExecutor(b_scanned)
    executor_b = _HoldingExecutor(a_scanned)
    first = ResearchCoordinator(repository, executor=executor_a, owner="worker-a")
    second = ResearchCoordinator(repository, executor=executor_b, owner="worker-b")

    results = []
    lock = threading.Lock()

    def run(coordinator, scanned):
        started.wait(timeout=5)
        outcome = coordinator.scan_once()
        with lock:
            results.append(outcome)
        scanned.set()

    threads = [
        threading.Thread(target=run, args=(first, a_scanned)),
        threading.Thread(target=run, args=(second, b_scanned)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    total_rounds = sum(result.rounds for result in results)
    assert total_rounds == 1
    assert len(repository.rounds(RESEARCH)) == 1
    # The loser did not write a round of its own. It was stopped by the
    # database - either refused at the claim or never offered the research -
    # and in both cases it is the repository, not the other worker, that
    # decided. Which of the two refusals happened is not the point; the
    # point is that the pair advanced the research exactly once.
    assert len(executor_a.calls) + len(executor_b.calls) == 1


def test_a_claimed_research_is_not_offered_to_another_worker(repository):
    _create(repository)
    owner = ResearchCoordinator(repository, executor=RecordingExecutor(), owner="worker-a")
    other = ResearchCoordinator(repository, executor=RecordingExecutor(), owner="worker-b")

    owner.repository.claim(RESEARCH, owner="worker-a", ttl_seconds=300.0)

    assert other.scan_once().researches == 0
    with pytest.raises(ResearchLeaseHeld):
        other.repository.claim(RESEARCH, owner="worker-b", ttl_seconds=300.0)


def test_a_taken_over_worker_cannot_write_its_late_result(repository):
    """The fence: the old worker's round is refused after a takeover.

    This is what makes replacing a crashed worker safe. The old worker is still
    running somewhere, still believes it owns the research, and still has a round
    worth writing. Its write must be refused - by the token, not by timing.
    """

    _create(repository)
    stale = ResearchCoordinator(repository, executor=RecordingExecutor(), owner="worker-a")
    # The lease is taken in the past so that it is already expired by the real
    # clock. That is the state a crashed worker leaves behind: it held the lease,
    # it stopped writing, and time passed.
    claimed = stale.repository.claim(
        RESEARCH, owner="worker-a", ttl_seconds=1.0, now=EXPIRED_NOW
    )
    stale_lease = ResearchLease(RESEARCH, "worker-a", claimed.fencing_token)

    # Another worker takes over once the lease has expired.
    taken = repository.claim(
        RESEARCH, owner="worker-b", ttl_seconds=1.0, now=EXPIRED_LATER
    )
    assert taken.fencing_token > claimed.fencing_token

    with pytest.raises(StaleResearchWriter):
        repository.checkpoint(
            RESEARCH,
            _round(RESEARCH, 0, evidence=("stale-fact",)),
            owner=stale_lease.owner,
            fencing_token=stale_lease.fencing_token,
            expected_state_version=claimed.state_version,
        )

    # The refused write left no trace at all.
    assert repository.rounds(RESEARCH) == ()
    assert repository.load(RESEARCH).round_index == 0


def test_a_worker_that_lost_its_lease_does_not_run_another_round(repository):
    """A takeover between rounds stops the old worker before it spends more.

    The renewal is where the old worker finds out. Without it the old worker would
    keep doing work whose results can no longer be written.
    """

    _create(repository)
    executor = RecordingExecutor()
    coordinator = ResearchCoordinator(repository, executor=executor, owner="worker-a")
    coordinator.scan_once()

    state = repository.load(RESEARCH)
    # Another worker takes over. Its claim bumps the fencing token, so the old
    # worker's next renewal is refused.
    taken = repository.claim(RESEARCH, owner="worker-b", ttl_seconds=300.0)
    assert taken.fencing_token > state.fencing_token

    result = coordinator.scan_once()

    # The old worker may not write any more, and the new owner holds the research.
    assert result.rounds == 0
    assert repository.load(RESEARCH).lease_owner == "worker-b"
    assert len(executor.calls) == 1  # no second round was attempted


# --- failures leave no trace ----------------------------------------------------------


def test_a_failed_round_leaves_no_durable_mark(repository):
    _create(repository)
    executor = RecordingExecutor(raise_at=1)
    coordinator = ResearchCoordinator(repository, executor=executor)

    result = coordinator.scan_once()

    assert result.failures == 1
    assert result.rounds == 0
    assert repository.rounds(RESEARCH) == ()
    state = repository.load(RESEARCH)
    assert state.round_index == 0
    assert state.status != STATE_STOPPED


def test_a_failed_round_is_retried_by_a_later_scan(repository):
    """The research is rediscovered, not remembered as broken."""

    _create(repository)
    failing = ResearchCoordinator(
        repository, executor=RecordingExecutor(raise_at=1), owner="worker-a"
    )
    assert failing.scan_once().failures == 1

    healthy = ResearchCoordinator(
        repository, executor=RecordingExecutor(), owner="worker-b"
    )
    result = healthy.scan_once()

    assert result.rounds == 1
    assert repository.load(RESEARCH).round_index == 1


def test_an_executor_that_declines_writes_nothing(repository):
    _create(repository)
    coordinator = ResearchCoordinator(
        repository, executor=RecordingExecutor(refuse=True), owner="worker-a"
    )

    result = coordinator.scan_once()

    assert result.rounds == 0
    assert result.skipped == 1
    assert repository.rounds(RESEARCH) == ()
    assert repository.load(RESEARCH).round_index == 0
    # The lease was handed back, so the research is immediately available again.
    assert repository.load(RESEARCH).lease_owner == ""


def test_a_failed_round_leaves_the_research_available_to_another_worker(repository):
    _create(repository)
    failing = ResearchCoordinator(
        repository, executor=RecordingExecutor(raise_at=1), owner="worker-a"
    )
    failing.scan_once()

    other = ResearchCoordinator(
        repository, executor=RecordingExecutor(), owner="worker-b"
    )
    assert other.scan_once().rounds == 1


# --- bounds ---------------------------------------------------------------------------


def test_a_scan_takes_at_most_its_batch(repository):
    for index in range(5):
        _create(repository, research_id=f"research-{index}")
    coordinator = ResearchCoordinator(
        repository, executor=RecordingExecutor(), batch_size=2
    )

    result = coordinator.scan_once()

    assert result.researches == 2
    assert result.rounds == 2


def test_one_research_cannot_take_over_the_whole_scan(repository):
    """A research runs a bounded number of rounds per scan, then yields."""

    _create(repository)
    executor = RecordingExecutor()
    coordinator = ResearchCoordinator(
        repository, executor=executor, rounds_per_scan=2
    )

    result = coordinator.scan_once()

    assert result.rounds == 2
    assert len(executor.calls) == 2
    assert repository.load(RESEARCH).round_index == 2


def test_a_stop_requested_worker_does_not_start_another_scan(repository):
    _create(repository)
    coordinator = ResearchCoordinator(repository, executor=RecordingExecutor())
    coordinator._stop.set()

    result = coordinator.scan_once()

    assert result.researches == 0
    assert coordinator.stats.scans == 1


def test_a_stop_requested_mid_scan_does_not_start_another_round(repository):
    """A stop that arrives between rounds must stop the next round too.

    The scan-level check only refuses to *begin* a scan. A worker that is asked
    to stop while it is already scanning must also stop between rounds, or the
    stop request would take effect one round late - which for a research means
    one more round of real model calls after the user asked it to stop.
    """

    _create(repository)
    executor = RecordingExecutor()
    coordinator = ResearchCoordinator(
        repository, executor=executor, rounds_per_scan=5
    )

    class StoppingExecutor(RecordingExecutor):
        def __call__(self, resume, lease):
            outcome = super().__call__(resume, lease)
            # The stop arrives once the first round is done.
            coordinator._stop.set()
            return outcome

    stopping = StoppingExecutor()
    coordinator.executor = stopping

    result = coordinator.scan_once()

    assert result.rounds == 1
    assert len(stopping.calls) == 1


def test_a_stop_requested_worker_returns_its_lease(repository):
    """A worker that stops must not keep the research to itself.

    Holding the lease after a stop would make the research wait out the whole
    TTL before anybody else could continue it - the opposite of what stopping is
    for.
    """

    _create(repository)
    coordinator = ResearchCoordinator(
        repository, executor=RecordingExecutor(), rounds_per_scan=5
    )

    class StoppingExecutor(RecordingExecutor):
        def __call__(self, resume, lease):
            outcome = super().__call__(resume, lease)
            coordinator._stop.set()
            return outcome

    coordinator.executor = StoppingExecutor()
    coordinator.scan_once()

    assert repository.load(RESEARCH).lease_owner == ""


# --- the worker thread ----------------------------------------------------------------


def test_the_worker_scans_immediately_on_start(repository):
    _create(repository)
    executor = RecordingExecutor()
    coordinator = ResearchCoordinator(
        repository, executor=executor, interval_seconds=3600.0
    )

    coordinator.start()
    try:
        deadline = threading.Event()
        for _ in range(200):
            if executor.calls:
                deadline.set()
                break
            threading.Event().wait(0.02)
        assert deadline.is_set(), "the worker did not scan on start"
    finally:
        coordinator.stop()


def test_waking_the_worker_does_not_run_work_on_the_caller_thread(repository):
    _create(repository)
    executor = RecordingExecutor()
    coordinator = ResearchCoordinator(
        repository, executor=executor, interval_seconds=3600.0
    )
    caller = threading.current_thread().ident
    seen: list[int | None] = []

    class Recorder:
        def __call__(self, resume, lease):
            seen.append(threading.current_thread().ident)
            return executor(resume, lease)

    coordinator.executor = Recorder()
    coordinator.start()
    try:
        for _ in range(200):
            if seen:
                break
            threading.Event().wait(0.02)
        assert seen, "the worker never ran"
        assert seen[0] != caller
    finally:
        coordinator.stop()


def test_starting_twice_creates_one_worker(repository):
    coordinator = ResearchCoordinator(repository, executor=RecordingExecutor())
    coordinator.start()
    try:
        thread = coordinator._thread
        coordinator.start()
        assert coordinator._thread is thread
    finally:
        coordinator.stop()


# --- the durable contract -------------------------------------------------------------


def test_the_state_row_never_loses_the_round_it_already_recorded(repository):
    """A crash between rounds leaves the previous round intact and readable."""

    _create(repository)
    executor = RecordingExecutor()
    coordinator = ResearchCoordinator(repository, executor=executor)
    coordinator.scan_once()

    # A new process reads the same database.
    other = ResearchCoordinator(repository, executor=RecordingExecutor(), owner="worker-b")
    resume = other.repository.resume(RESEARCH)

    assert resume is not None
    assert resume.next_round_index == 1
    assert resume.evidence == ("fact-0",)
    assert resume.executed_queries == ("query-0",)


def test_a_checkpoint_may_not_lower_a_quota_it_already_recorded(repository):
    """The observation is monotonic, so a resume cannot invent budget."""

    _create(repository)
    claimed = repository.claim(RESEARCH, owner="worker-a", ttl_seconds=300.0)
    repository.checkpoint(
        RESEARCH,
        _round(RESEARCH, 0),
        owner="worker-a",
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
        quota_observed={"searches": 5},
    )
    state = repository.load(RESEARCH)
    assert state.quota_observed == {"searches": 5}

    with pytest.raises(ValueError):
        repository.checkpoint(
            RESEARCH,
            _round(RESEARCH, 1),
            owner="worker-a",
            fencing_token=claimed.fencing_token,
            expected_state_version=state.state_version,
            quota_observed={"searches": 9},
        )

    # The refused checkpoint wrote nothing at all.
    assert len(repository.rounds(RESEARCH)) == 1
    assert repository.load(RESEARCH).quota_observed == {"searches": 5}


def test_the_lease_outlives_one_round(repository):
    """A lease shorter than a planning loop would expire mid-round."""

    assert DEFAULT_LEASE_SECONDS >= 120.0


def test_the_coordinator_never_changes_a_tier(repository):
    _create(repository)
    coordinator = ResearchCoordinator(repository, executor=RecordingExecutor())
    coordinator.scan_once()

    assert repository.load(RESEARCH).tier == "standard"


# --- the request identity -------------------------------------------------------------


def test_a_replayed_round_derives_the_same_request_identity(repository):
    """The identity of a round is derived, so a replay is the same request.

    This is what makes "a crashed worker does not pay twice" work without this
    layer knowing what was paid for. The key is a function of the research, the
    round and the stage - nothing a restart can lose - so the ledger sees the
    replay as the request it already refused.

    The replay is of the *same* round: a worker that ran round 0 and died before
    its checkpoint landed. The replacement runs round 0 again, and must derive the
    same key - not a fresh one, which would read as a second, separately billable
    request.
    """

    _create(repository)
    # Worker A runs round 0 and dies before writing the checkpoint.
    executor = RecordingExecutor()
    worker_a = ResearchCoordinator(repository, executor=executor, owner="worker-a")
    worker_a.scan_once()
    original_key = executor.leases[0].request_key("decision")

    # Rewind to before the checkpoint: the round was attempted but never recorded.
    with repository.database.connect() as connection:
        connection.execute(
            "DELETE FROM research_rounds WHERE research_id = ?", (RESEARCH,)
        )
        connection.execute(
            "UPDATE research_states SET round_index = 0, state_version = 1, "
            "evidence = '[]' WHERE research_id = ?",
            (RESEARCH,),
        )

    # Worker B replays round 0.
    replay_executor = RecordingExecutor()
    worker_b = ResearchCoordinator(
        repository, executor=replay_executor, owner="worker-b"
    )
    worker_b.scan_once()

    assert replay_executor.leases[0].request_key("decision") == original_key


def test_each_round_derives_its_own_request_identity(repository):
    """Round 1 and round 2 are different requests, and must not share a key."""

    _create(repository)
    executor = RecordingExecutor()
    coordinator = ResearchCoordinator(repository, executor=executor)
    coordinator.scan_once()
    coordinator.scan_once()

    keys = [lease.request_key("decision") for lease in executor.leases]
    assert len(keys) == 2
    assert keys[0] != keys[1]


def test_the_stage_is_part_of_the_request_identity(repository):
    """Two different calls in one round are different requests."""

    _create(repository)
    executor = RecordingExecutor()
    coordinator = ResearchCoordinator(repository, executor=executor)
    coordinator.scan_once()

    lease = executor.leases[0]
    assert lease.request_key("decision") != lease.request_key("search")
    assert lease.request_key("decision") == lease.request_key("decision")


# --- the milestone --------------------------------------------------------------------


def test_a_killed_worker_is_replaced_and_the_research_continues(repository):
    """The milestone: a worker dies mid-research and another one finishes it.

    The first worker finishes round 0 and checkpoints it. Then it dies - it never
    writes again, which is exactly what a SIGKILL looks like to the database.

    The second worker takes over and runs round 1. It must not repeat round 0's
    search, must not lose round 0's observation, and must not spend a second time
    on round 0's work.

    Note the shape of the handover. Between rounds the coordinator hands the lease
    back on purpose, so a research is never held by an idle worker. The crash is
    therefore interesting precisely because it happens *inside* a round: the lease
    is still held, and the replacement has to wait for it to expire.
    """

    _create(repository)
    first = RecordingExecutor()
    worker_a = ResearchCoordinator(repository, executor=first, owner="worker-a")

    # Round 0 runs and is checkpointed.
    worker_a.scan_once()
    assert repository.load(RESEARCH).round_index == 1

    # Worker A is killed mid-research: its lease is still held, so the research is
    # not offered to anybody until that lease expires.
    held = repository.claim(
        RESEARCH, owner="worker-a", ttl_seconds=1.0, now=EXPIRED_NOW
    )
    assert held.fencing_token > first.leases[0].fencing_token

    # Worker B takes over once the lease expires. The takeover bumps the fencing
    # token, so worker A's late write would be refused even if it came back.
    taken = repository.claim(
        RESEARCH,
        owner="worker-b",
        ttl_seconds=1.0,
        now=EXPIRED_LATER,
    )
    assert taken.fencing_token > held.fencing_token

    second = RecordingExecutor()
    worker_b = ResearchCoordinator(repository, executor=second, owner="worker-b")
    result = worker_b.scan_once()

    # Round 1 ran, and it started from round 0's observation.
    assert result.rounds == 1
    assert second.calls == [(1, ("query-0",))]
    assert second.seen_evidence == [("fact-0",)]

    # Both rounds are on record, in order, with their own evidence.
    rounds = repository.rounds(RESEARCH)
    assert [round_.round_index for round_ in rounds] == [0, 1]
    assert rounds[0].evidence == ("fact-0",)
    assert rounds[1].evidence == ("fact-1",)
    assert repository.load(RESEARCH).round_index == 2


def test_the_replacement_worker_does_not_repeat_the_dead_workers_search(repository):
    """The second worker must not pay for round 0 a second time.

    It cannot know what was paid for - the ledger is the authority on that, and it
    refuses the duplicate on its own unique key. What the coordinator guarantees is
    narrower and just as necessary: the replacement is *offered* round 1 with
    round 0's queries already excluded, so it does not search for the same thing
    again in the first place.
    """

    _create(repository)
    worker_a = ResearchCoordinator(
        repository, executor=RecordingExecutor(), owner="worker-a"
    )
    worker_a.scan_once()

    # Between rounds the coordinator hands the lease back, so the replacement is
    # offered the research immediately - it does not have to wait out a TTL.
    assert repository.load(RESEARCH).lease_owner == ""

    second = RecordingExecutor()
    worker_b = ResearchCoordinator(repository, executor=second, owner="worker-b")
    worker_b.scan_once()

    # Round 1's own query is new; round 0's is not repeated.
    executed = second.calls[0][1]
    assert executed == ("query-0",)
    assert "query-0" not in second.seen_evidence[0]

    # And the durable log shows two distinct rounds, not a repeat of the first.
    assert len(repository.rounds(RESEARCH)) == 2


def test_the_dead_workers_late_write_is_refused(repository):
    """After the takeover, the dead worker's checkpoint would be refused.

    This is the property that makes "kill it and start another" safe rather than
    merely convenient: the replacement's work and the original's work can never
    both land.
    """

    _create(repository)
    claimed = repository.claim(
        RESEARCH, owner="worker-a", ttl_seconds=1.0, now=EXPIRED_NOW
    )
    stale = ResearchLease(RESEARCH, "worker-a", claimed.fencing_token)

    repository.claim(
        RESEARCH,
        owner="worker-b",
        ttl_seconds=1.0,
        now=EXPIRED_LATER,
    )

    with pytest.raises(StaleResearchWriter):
        repository.checkpoint(
            RESEARCH,
            _round(RESEARCH, 0, evidence=("zombie-fact",)),
            owner=stale.owner,
            fencing_token=stale.fencing_token,
            expected_state_version=claimed.state_version,
        )

    assert repository.rounds(RESEARCH) == ()
