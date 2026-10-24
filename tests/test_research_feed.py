"""CL-M3 QD-3c: a client may look at a research without being able to end it.

The contract's R-3 is one sentence with two halves: a research survives the client
disappearing, and only the user's own cancellation may end it. The first half was
already true after QD-3b - the coordinator advances research from database facts,
and no HTTP connection is part of that. These tests are about the half that was
still missing, and about the failure modes that would make the first half untrue.

The failure modes, in the order they would bite:

- **A reader that can end the research.** If watching and cancelling were the same
  call, then closing a browser tab would end the research, and R-3 would be false
  in the most ordinary way possible. The subscription type therefore carries no
  cancel, and one test asserts the absence rather than the presence.
- **A hole between the round and its event.** If the round were committed and the
  event written afterwards, a crash between the two would leave a research whose
  client can never learn the round happened. The event is written in the same
  transaction, and a test proves a refused checkpoint leaves no event behind.
- **A cursor that skips.** If the sequence could repeat, a resuming client would
  skip an event it had already been told about. The sequence is allocated by the
  database, and a test writes concurrently to show no two events share a sequence.
- **A thread that sees another thread.** If the thread view were not scoped, then
  switching chat would show - and could interfere with - another chat's research.
- **A client that cannot tell "no round" from "the first round".** Round 0 is a
  real round; a sentinel of 0 would conflate it with "not about a round".
"""

from __future__ import annotations

import threading

import pytest

from src.application.research_feed import (
    ResearchFeed,
    ResearchSubscriptionRegistry,
    rounds_to_payload,
)
from src.domain.research_event import (
    EVENT_RESEARCH_FINISHED,
    EVENT_RESEARCH_STARTED,
    EVENT_ROUND_COMPLETED,
    ResearchEvent,
    ResearchSubscription,
)
from src.domain.research_state import (
    STATE_CHECKPOINTED,
    STATE_STOPPED,
    ResearchRound,
)
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.research_state_repository import (
    ResearchNotFound,
    ResearchStateRepository,
    StaleResearchWriter,
)

RESEARCH = "research-1"
THREAD = "thread-1"
OTHER_THREAD = "thread-2"


@pytest.fixture
def db(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.sqlite")
    database.initialize()
    return database


@pytest.fixture
def repository(db):
    return ResearchStateRepository(db)


@pytest.fixture
def feed(repository):
    return ResearchFeed(repository)


def _create(repository, research_id=RESEARCH, *, thread_id=THREAD, question="what is X?"):
    return repository.create(
        research_id=research_id,
        thread_id=thread_id,
        operation_id=f"operation-{research_id}",
        original_question=question,
        question=question,
        tier="standard",
    )


def _round(research_id, index, *, question="what is X?", evidence=()):
    return ResearchRound(
        research_id=research_id,
        round_index=index,
        question=question,
        queries=(f"query-{index}",),
        evidence=tuple(evidence),
    )


def _checkpoint(repository, *, owner="worker-1", token=None, index=0, status=STATE_CHECKPOINTED):
    """Claim the lease, checkpoint under it, then hand the lease back.

    The claim is not optional: a checkpoint's compare-and-swap matches on owner and
    fencing token, so a checkpoint without a lease is refused. The token therefore
    comes from the claim rather than being written down here.

    The release at the end is what lets a second round be checkpointed: a lease
    that is still held would make the next claim fail, and a test that wanted two
    rounds would be testing the lease instead of the events.
    """

    claimed = repository.claim(RESEARCH, owner=owner)
    state = repository.checkpoint(
        RESEARCH,
        _round(RESEARCH, index, evidence=(f"fact-{index}",)),
        owner=owner,
        fencing_token=token if token is not None else claimed.fencing_token,
        expected_state_version=claimed.state_version,
        status=status,
    )
    if not state.terminal:
        repository.release(RESEARCH, owner=owner, fencing_token=claimed.fencing_token)
    return state


# --- the event log ------------------------------------------------------------------


def test_a_checkpoint_publishes_an_event(repository):
    _create(repository)
    _checkpoint(repository)

    events = repository.events(RESEARCH)

    assert [event.kind for event in events] == [EVENT_ROUND_COMPLETED]
    assert events[0].event_seq == 1
    assert events[0].payload["round_index"] == 0


def test_the_event_sequence_is_allocated_by_the_database(repository):
    _create(repository)
    _checkpoint(repository)
    _checkpoint(repository, index=1)

    events = repository.events(RESEARCH)

    assert [event.event_seq for event in events] == [1, 2]


def test_the_sequence_is_shared_across_researches(repository):
    """A client watches a thread and holds one cursor.

    If each research numbered its own events, research B's event 1 would look
    older than research A's event 5 to that cursor, and the client would skip
    B's events entirely.
    """

    _create(repository, RESEARCH, thread_id=THREAD)
    _create(repository, "research-2", thread_id=THREAD)
    _checkpoint(repository)

    other = repository.claim("research-2", owner="worker-2")
    repository.checkpoint(
        "research-2",
        _round("research-2", 0, evidence=("fact-other",)),
        owner="worker-2",
        fencing_token=other.fencing_token,
        expected_state_version=other.state_version,
    )

    first = repository.events(RESEARCH)[0].event_seq
    second = repository.events("research-2")[0].event_seq
    assert second > first

    # One cursor therefore works across both.
    after_first = repository.events("research-2", after_event_seq=first)
    assert [event.event_seq for event in after_first] == [second]


def test_a_terminating_checkpoint_publishes_a_finished_event(repository):
    _create(repository)
    _checkpoint(repository, index=0, status=STATE_STOPPED)

    kinds = [event.kind for event in repository.events(RESEARCH)]

    assert kinds == [EVENT_ROUND_COMPLETED, EVENT_RESEARCH_FINISHED]


def test_a_refused_checkpoint_publishes_no_event(repository):
    """A round that was not written must not have an event.

    The event is written in the same transaction as the round, so a compare-and-swap
    that misses takes the event with it. An event without its round would tell a
    client that a round happened that no worker can ever read back.
    """

    _create(repository)
    claimed = repository.claim(RESEARCH, owner="worker-1")
    with pytest.raises(StaleResearchWriter):
        repository.checkpoint(
            RESEARCH,
            _round(RESEARCH, 0, evidence=("fact-0",)),
            owner="worker-1",
            fencing_token=claimed.fencing_token + 99,
            expected_state_version=claimed.state_version,
        )

    assert repository.events(RESEARCH) == ()
    assert repository.count_events(RESEARCH) == 0


def test_the_event_is_written_in_the_same_transaction_as_the_round(repository, monkeypatch):
    """The event and the round commit together, or not at all.

    If the event were written after the checkpoint committed, a crash between the
    two would leave a research whose round is durable and whose event never
    existed - and a reconnecting client would never learn the round happened.
    That is precisely the loss the first acceptance criterion of 10.8 is about,
    and it cannot be observed by reading the code after the fact: it has to be
    pinned by a test that makes the event write fail and checks that the round
    did not survive either.
    """

    _create(repository)
    claimed = repository.claim(RESEARCH, owner="worker-1")

    original = ResearchStateRepository._append_event

    def exploding(*args, **kwargs):
        raise RuntimeError("event write failed")

    monkeypatch.setattr(ResearchStateRepository, "_append_event", staticmethod(exploding))

    with pytest.raises(RuntimeError):
        repository.checkpoint(
            RESEARCH,
            _round(RESEARCH, 0, evidence=("fact-0",)),
            owner="worker-1",
            fencing_token=claimed.fencing_token,
            expected_state_version=claimed.state_version,
        )

    # The round did not survive the failed event write. If it had, the research
    # would be one round ahead of anything a client was ever told.
    assert repository.rounds(RESEARCH) == ()
    state = repository.load(RESEARCH)
    assert state is not None
    assert state.round_index == 0

    monkeypatch.setattr(
        ResearchStateRepository, "_append_event", staticmethod(original)
    )


def test_concurrent_writers_never_mint_the_same_sequence(repository):
    """Two writers that each added one to their own idea of the next number would
    mint the same sequence twice, and a resuming client would skip an event.

    The first implementation read ``MAX(event_seq) + 1`` and then inserted. Two
    writers read the same maximum and the second insert died on the unique
    constraint - the failure this test exists to catch.
    """

    _create(repository)
    results = []
    errors = []

    def writer(tag):
        try:
            results.append(
                repository.append_event(
                    RESEARCH, kind=EVENT_RESEARCH_STARTED, payload={"tag": tag}
                )
            )
        except Exception as exc:  # pragma: no cover - recorded for the assertion
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    sequences = sorted(event.event_seq for event in results)
    assert len(set(sequences)) == 8
    # Consecutive: the counter hands them out one after another.
    assert sequences == list(range(sequences[0], sequences[0] + 8))


def test_the_event_cursor_is_exclusive(repository):
    _create(repository)
    _checkpoint(repository)
    _checkpoint(repository, index=1)

    after_first = repository.events(RESEARCH, after_event_seq=1)

    assert [event.event_seq for event in after_first] == [2]


def test_an_event_may_be_appended_outside_a_checkpoint(repository):
    _create(repository)
    event = repository.append_event(
        RESEARCH, kind=EVENT_RESEARCH_STARTED, payload={"tier": "standard"}
    )

    assert event.event_seq == 1
    assert repository.count_events(RESEARCH) == 1


def test_an_event_for_an_unknown_research_is_refused(repository):
    with pytest.raises(ResearchNotFound):
        repository.append_event("no-such-research", kind=EVENT_RESEARCH_STARTED)


# --- the subscription cannot end the research ---------------------------------------


def test_a_subscription_carries_no_way_to_cancel_the_research():
    """The absence is the guarantee.

    If watching and cancelling were the same call, then closing a browser tab
    would end the research, and R-3 would be false in the most ordinary way
    possible. This asserts the *absence* of the method rather than the presence of
    a guard elsewhere, because a guard can be bypassed and an absent method cannot.
    """

    subscription = ResearchSubscription(research_id=RESEARCH, thread_id=THREAD)

    for name in ("cancel", "stop", "terminate", "end", "close_research"):
        assert not hasattr(subscription, name), f"subscription must not be able to {name}"


def test_the_registry_cannot_end_a_research_either():
    registry = ResearchSubscriptionRegistry()

    for name in ("cancel", "stop", "terminate", "end_research"):
        assert not hasattr(registry, name), f"registry must not be able to {name}"


def test_unsubscribing_leaves_the_research_untouched(repository, feed):
    _create(repository)
    _checkpoint(repository)
    registry = ResearchSubscriptionRegistry()
    handle = registry.subscribe(research_id=RESEARCH, thread_id=THREAD)

    registry.unsubscribe(handle)

    state = repository.load(RESEARCH)
    assert state is not None
    assert state.status == STATE_CHECKPOINTED
    assert state.round_index == 1


def test_dropping_a_thread_removes_only_its_watchers(repository):
    registry = ResearchSubscriptionRegistry()
    first = registry.subscribe(research_id=RESEARCH, thread_id=THREAD)
    second = registry.subscribe(research_id="research-2", thread_id=OTHER_THREAD)

    dropped = registry.drop_thread(THREAD)

    assert dropped == 1
    assert registry.watchers(RESEARCH) == 0
    assert registry.watchers("research-2") == 1
    assert first.subscriber_id not in {h.subscriber_id for h in registry.handles()}
    assert second.subscriber_id in {h.subscriber_id for h in registry.handles()}


def test_dropping_a_thread_leaves_the_research_running(repository):
    """Switching chat stops the watching. The research keeps going."""

    _create(repository)
    _checkpoint(repository)
    registry = ResearchSubscriptionRegistry()
    handle = registry.subscribe(research_id=RESEARCH, thread_id=THREAD)

    registry.drop_thread(THREAD)

    state = repository.load(RESEARCH)
    assert state is not None
    assert state.status == STATE_CHECKPOINTED
    assert state.terminal is False
    assert handle.research_id == RESEARCH


# --- reconnecting sees what it missed ------------------------------------------------


def test_a_reconnecting_client_sees_the_rounds_it_missed(repository, feed):
    _create(repository)
    _checkpoint(repository)
    _checkpoint(repository, index=1)

    snapshot = feed.snapshot(RESEARCH)

    assert snapshot.round_index == 2
    assert [record.round_index for record in snapshot.rounds] == [0, 1]
    assert [event.kind for event in snapshot.events] == [
        EVENT_ROUND_COMPLETED,
        EVENT_ROUND_COMPLETED,
    ]


def test_a_reconnecting_client_resumes_from_its_cursor(repository, feed):
    _create(repository)
    _checkpoint(repository)
    _checkpoint(repository, index=1)

    seen_one = feed.events_since(RESEARCH, after_event_seq=1)

    assert [event.event_seq for event in seen_one] == [2]


def test_snapshot_cannot_mix_rounds_committed_after_its_state_read(
    repository, feed, monkeypatch
):
    """A concurrent checkpoint between SELECTs must not split one snapshot.

    WAL lets a second writer commit while the reader holds its SQLite snapshot.
    Without a single BEGIN, this returns round_index=1 alongside two rounds.
    """
    _create(repository)
    _checkpoint(repository)
    with repository.database.connect() as connection:
        connection.execute("PRAGMA journal_mode=WAL")

    writer = ResearchStateRepository(RuntimeDatabase(repository.database.path))
    connect = repository.database.connect
    wrote = False

    def hooked_connect():
        connection = connect()

        def on_sql(statement):
            nonlocal wrote
            if "SELECT * FROM research_rounds" in statement and not wrote:
                wrote = True
                _checkpoint(writer, owner="other-worker", index=1)

        connection.set_trace_callback(on_sql)
        return connection

    monkeypatch.setattr(repository.database, "connect", hooked_connect)
    snapshot = feed.snapshot(RESEARCH)
    assert wrote
    assert snapshot.round_index == 1
    assert [record.round_index for record in snapshot.rounds] == [0]
    assert snapshot.missed_events == 1
    assert [event.event_seq for event in snapshot.events] == [1]
    assert writer.load(RESEARCH).round_index == 2


def test_the_snapshot_counts_what_the_client_missed(repository, feed):
    _create(repository)
    _checkpoint(repository)
    _checkpoint(repository, index=1)

    snapshot = feed.snapshot(RESEARCH, after_event_seq=1)

    assert snapshot.missed_events == 1
    assert len(snapshot.events) == 1


def test_the_missed_count_is_a_count_and_not_a_subtraction(repository, feed):
    """The sequence is global, so "total minus cursor" is the wrong arithmetic.

    The cursor is global - it says how far into the whole log the client has
    read - while the total is per research. Subtracting one from the other
    counts the *other* researches' events that happen to sit in between, and
    can even go negative.

    The two formulas only differ when a thread holds more than one research,
    which is exactly the case a single-research test cannot see. That is why
    this test builds two.
    """

    _create(repository, RESEARCH, thread_id=THREAD)
    _create(repository, "research-2", thread_id=THREAD)
    # Two events for the first research, then one for the second.
    _checkpoint(repository)
    _checkpoint(repository, index=1)
    other = repository.claim("research-2", owner="worker-2")
    repository.checkpoint(
        "research-2",
        _round("research-2", 0, evidence=("fact-other",)),
        owner="worker-2",
        fencing_token=other.fencing_token,
        expected_state_version=other.state_version,
    )

    # The client has read everything up to and including sequence 2.
    cursor = 2

    snapshot = feed.snapshot("research-2", after_event_seq=cursor)

    # research-2 has exactly one event after the cursor.
    assert snapshot.missed_events == 1
    assert [event.kind for event in snapshot.events] == [EVENT_ROUND_COMPLETED]
    # The subtraction would have said 1 - 2, i.e. nothing at all.
    assert snapshot.missed_events != max(
        0, repository.count_events("research-2") - cursor
    )


def test_a_client_that_never_disconnected_sees_no_missed_events(repository, feed):
    _create(repository)
    _checkpoint(repository)

    snapshot = feed.snapshot(RESEARCH, after_event_seq=1)

    assert snapshot.missed_events == 0
    assert snapshot.events == ()
    # ...and the state is still correct, because the state does not come from events.
    assert snapshot.round_index == 1


def test_the_state_is_read_from_the_state_table_not_from_the_events(repository, feed):
    """The event log is not a second truth.

    If the state were derived from the events, deleting the log would change what
    the research *is* - and a client that reconnected after a prune would be told
    a different story than one that never disconnected.
    """

    _create(repository)
    _checkpoint(repository)

    with repository.database.connect() as connection:
        connection.execute("DELETE FROM research_events")

    snapshot = feed.snapshot(RESEARCH)

    assert snapshot.status == STATE_CHECKPOINTED
    assert snapshot.round_index == 1
    assert len(snapshot.rounds) == 1


def test_a_research_that_predates_the_event_log_keeps_its_authoritative_state(
    repository, feed
):
    """Migration 28 creates an empty event table. It does not backfill one.

    A research that ran rounds before the log existed has rounds in
    ``research_rounds`` and a ``round_index`` in ``research_states``, and *no*
    events. When it runs its next round after the upgrade, the log holds one
    event and the state says three rounds. A snapshot that counted the log
    instead of reading the state would tell the client the research is one
    round old - and the client would stop drawing rounds that already exist.

    This is not a hypothetical shape. It is the state of every research that was
    running when the migration shipped, and the state of any developer database
    that was already at version 27 when version 28 arrived.

    The earlier test deletes *every* event, which is the weak case: a guard that
    counts the log can short-circuit on an empty one and still pass. This one
    leaves the log non-empty and short, which is where the two truths differ.
    """

    _create(repository)
    _checkpoint(repository, index=0)
    _checkpoint(repository, index=1)

    # The upgrade. Migration 28 adds the table and fills it with nothing.
    with repository.database.connect() as connection:
        connection.execute("DELETE FROM research_events")

    # The first round that runs after the upgrade writes the first event.
    _checkpoint(repository, index=2)

    snapshot = feed.snapshot(RESEARCH)

    assert snapshot.round_index == 3
    assert len(snapshot.rounds) == 3
    assert snapshot.status == STATE_CHECKPOINTED
    # The log is one event long and the state is three rounds. Both are true.
    assert len(snapshot.events) == 1


def test_a_pruned_event_log_does_not_change_what_the_research_is(repository, feed):
    """A retention policy that drops old events must not rewrite the history.

    The event log answers "what did this client miss" and nothing more. A
    pruning job that keeps the newest events and drops the old ones - a normal
    thing to do to an append-only log - leaves the log shorter than the
    research's history. The rounds that finished are still finished, and the
    state table still says how many of them there are.
    """

    _create(repository)
    _checkpoint(repository, index=0)
    _checkpoint(repository, index=1)
    _checkpoint(repository, index=2)

    # Keep the newest event, drop the older ones.
    with repository.database.connect() as connection:
        connection.execute(
            "DELETE FROM research_events WHERE event_seq <= ("
            "SELECT MAX(event_seq) - 1 FROM research_events)"
        )

    snapshot = feed.snapshot(RESEARCH)

    assert snapshot.round_index == 3
    assert len(snapshot.rounds) == 3
    assert len(snapshot.events) == 1


def test_a_pruned_finished_event_does_not_resurrect_a_stopped_research(repository, feed):
    """A finished event that was pruned away must not un-finish the research.

    The status lives in ``research_states``. If it were read from the log, then
    a log that had lost its last event would report a stopped research as
    running - and a client would offer to continue a research that is over.
    """

    _create(repository)
    _checkpoint(repository, index=0, status=STATE_STOPPED)

    # The log keeps its round event and loses the one that says it finished.
    with repository.database.connect() as connection:
        connection.execute(
            "DELETE FROM research_events WHERE kind = 'research_finished'"
        )

    snapshot = feed.snapshot(RESEARCH)

    assert snapshot.status == STATE_STOPPED
    assert snapshot.round_index == 1


def test_every_round_the_coordinator_runs_publishes_an_event(repository, feed):
    """The event comes from the checkpoint, not from a second write.

    If the coordinator wrote the event separately from the checkpoint, a crash
    between the two would leave a research whose client can never learn that the
    round happened. Deriving the event from the checkpoint means there is no gap
    to have.
    """

    from src.application.research_coordinator import AdvanceOutcome, ResearchCoordinator

    def executor(resume, lease):
        return AdvanceOutcome(
            round_record=_round(
                resume.state.research_id,
                resume.next_round_index,
                evidence=(f"fact-{resume.next_round_index}",),
            )
        )

    _create(repository)
    coordinator = ResearchCoordinator(repository, executor=executor)

    coordinator.scan_once()
    coordinator.scan_once()

    kinds = [event.kind for event in repository.events(RESEARCH)]
    assert kinds == [EVENT_ROUND_COMPLETED, EVENT_ROUND_COMPLETED]
    snapshot = feed.snapshot(RESEARCH)
    assert snapshot.round_index == 2
    assert len(snapshot.rounds) == 2


def test_a_reconnecting_client_gets_the_same_state_as_a_connected_one(repository, feed):
    _create(repository)
    _checkpoint(repository)

    connected = feed.snapshot(RESEARCH, after_event_seq=99)
    reconnected = feed.snapshot(RESEARCH, after_event_seq=0)

    assert connected.status == reconnected.status
    assert connected.round_index == reconnected.round_index
    assert len(connected.rounds) == len(reconnected.rounds)


# --- one thread never sees another --------------------------------------------------


def test_a_thread_view_contains_only_that_thread(repository, feed):
    _create(repository, RESEARCH, thread_id=THREAD)
    _create(repository, "research-2", thread_id=OTHER_THREAD)
    _checkpoint(repository)

    snapshots = feed.thread_snapshot(THREAD)

    assert [snapshot.research_id for snapshot in snapshots] == [RESEARCH]
    assert all(snapshot.thread_id == THREAD for snapshot in snapshots)


def test_a_thread_view_includes_a_finished_research(repository, feed):
    _create(repository)
    _checkpoint(repository, status=STATE_STOPPED)

    snapshots = feed.thread_snapshot(THREAD)

    assert len(snapshots) == 1
    assert snapshots[0].status == STATE_STOPPED


# --- the round index sentinel --------------------------------------------------------


def test_the_first_round_is_not_mistaken_for_no_round():
    """Round 0 is a real round. A sentinel of 0 would conflate it."""

    first = ResearchEvent(
        research_id=RESEARCH,
        event_seq=1,
        kind=EVENT_ROUND_COMPLETED,
        payload={"round_index": 0},
    )
    without = ResearchEvent(
        research_id=RESEARCH, event_seq=2, kind=EVENT_RESEARCH_STARTED
    )

    assert first.round_index == 0
    assert without.round_index == -1


# --- the snapshot shape --------------------------------------------------------------


def test_a_snapshot_serialises_without_losing_the_evidence(repository, feed):
    _create(repository)
    _checkpoint(repository)

    payload = feed.snapshot(RESEARCH).as_dict()

    assert payload["rounds"][0]["evidence"] == ["fact-0"]
    assert payload["events"][0]["kind"] == EVENT_ROUND_COMPLETED


def test_rounds_to_payload_keeps_the_queries(repository):
    _create(repository)
    _checkpoint(repository)

    payload = rounds_to_payload(repository.rounds(RESEARCH))

    assert payload[0]["queries"] == ["query-0"]


def test_a_snapshot_for_an_unknown_research_is_refused(feed):
    with pytest.raises(ResearchNotFound):
        feed.snapshot("no-such-research")


def test_a_subscription_rejects_a_negative_cursor():
    with pytest.raises(ValueError):
        ResearchSubscription(research_id=RESEARCH, thread_id=THREAD, after_event_seq=-1)


def test_an_event_rejects_an_unknown_kind():
    with pytest.raises(ValueError):
        ResearchEvent(research_id=RESEARCH, event_seq=1, kind="not-a-kind")


def test_an_event_rejects_a_zero_sequence():
    with pytest.raises(ValueError):
        ResearchEvent(research_id=RESEARCH, event_seq=0, kind=EVENT_ROUND_COMPLETED)
