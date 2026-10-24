"""CL-M3 QD-3d: the three ways a research may end, and the one way it may not.

The contract froze three semantics on 2026-10-24 (CL_M3_CAPABILITY_CONTRACT.md
§11). This file is the negative control for the first of them: **cooperative
cancellation** (R-3).

**What a negative control is here.** Each test in this file is written from
the contract's *counter-example*, not from the implementation. If the
implementation is missing, wrong, or quietly bypassed, the matching test
fails. A test written from the code instead would pass on the code and prove
nothing - and QD-3c already paid for that lesson twice (a guard that deleted
all the data it protected, and a mutation runner that reported an environment
failure as a detection).

**The three counter-examples for R-3**, straight from §11.1:

1. The cancellation is persisted, and the executor then makes another model
   call anyway.
2. The cancellation erases what earlier rounds had found.
3. A request that was already in flight when the user cancelled is treated as
   if it had never been sent - that is, the research pretends it cost nothing.

The third one is the subtle one. The contract says an in-flight call may be
interrupted on a best-effort basis, but that **a network interruption must not
be read as "the server did not run it"**. A cancellation that forgets an
in-flight call would let the research look cheaper than it was, and the ledger
would be asked to reconcile a number that never existed.
"""

from __future__ import annotations

import pytest

from src.domain.research_state import (
    STATE_CANCELLED,
    STATE_CHECKPOINTED,
    ResearchRound,
)
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.research_state_repository import ResearchStateRepository

RESEARCH = "research-1"
THREAD = "thread-1"


@pytest.fixture
def db(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.sqlite")
    database.initialize()
    return database


@pytest.fixture
def repository(db):
    return ResearchStateRepository(db)


def _create(repository, research_id=RESEARCH, *, thread_id=THREAD, question="what is X?"):
    return repository.create(
        research_id=research_id,
        thread_id=thread_id,
        operation_id=f"operation-{research_id}",
        original_question=question,
        question=question,
        tier="standard",
    )


def _round(research_id, index, *, evidence=(), urls=()):
    return ResearchRound(
        research_id=research_id,
        round_index=index,
        question="what is X?",
        queries=(f"query-{index}",),
        observation_urls=tuple(urls),
        evidence=tuple(evidence),
    )


def _checkpoint(repository, *, owner="worker-1", index=0, status=STATE_CHECKPOINTED):
    claimed = repository.claim(RESEARCH, owner=owner)
    state = repository.checkpoint(
        RESEARCH,
        _round(RESEARCH, index, evidence=(f"fact-{index}",), urls=(f"https://s/{index}",)),
        owner=owner,
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
        status=status,
    )
    if not state.terminal:
        repository.release(RESEARCH, owner=owner, fencing_token=claimed.fencing_token)
    return state


# --- the cancellation is persisted ----------------------------------------------------


def test_a_cancellation_is_persisted_immediately(repository):
    """The user cancels; the fact of it is durable before anything else happens.

    A cancellation that lives only in the process that received it is not a
    cancellation - it is a hint. The research outlives the process by design,
    so the decision has to outlive it too.
    """

    _create(repository)
    _checkpoint(repository)

    state = repository.cancel(RESEARCH, reason="user_cancelled")

    assert state.status == STATE_CANCELLED
    assert state.cancel_requested_at != ""
    # It survives a fresh read, which is what "durable" has to mean.
    reloaded = repository.load(RESEARCH)
    assert reloaded is not None
    assert reloaded.status == STATE_CANCELLED
    assert reloaded.cancel_requested_at != ""


def test_a_cancellation_is_visible_to_a_resuming_worker(repository):
    """A worker that takes the research over must see the cancellation.

    This is the whole point of persisting it. The worker that gets the lease
    is not the process the user clicked in, and it is the one that would
    otherwise start the next model call.
    """

    _create(repository)
    _checkpoint(repository)
    repository.cancel(RESEARCH, reason="user_cancelled")

    resume = repository.resume(RESEARCH)

    assert resume is not None
    assert resume.cancelled is True
    assert resume.state.status == STATE_CANCELLED


def test_a_cancelled_research_may_not_be_claimed(repository):
    """Nothing may pick a cancelled research up and carry it on."""

    _create(repository)
    _checkpoint(repository)
    repository.cancel(RESEARCH, reason="user_cancelled")

    from src.repositories.research_state_repository import ResearchAlreadyTerminal

    with pytest.raises(ResearchAlreadyTerminal):
        repository.claim(RESEARCH, owner="worker-2")


def test_a_cancellation_is_refused_for_a_research_that_does_not_exist(repository):
    from src.repositories.research_state_repository import ResearchNotFound

    with pytest.raises(ResearchNotFound):
        repository.cancel("no-such-research", reason="user_cancelled")


def test_a_cancellation_records_its_reason(repository):
    """Why a research stopped is part of what a client is told.

    A cancellation with no reason is indistinguishable from a crash to anyone
    reading the state later.
    """

    _create(repository)
    _checkpoint(repository)

    state = repository.cancel(RESEARCH, reason="user_cancelled")

    assert state.stop_reason == "user_cancelled"


# --- counter-example 1: the research keeps calling models anyway ------------------------


def test_a_cancelled_research_reports_that_no_further_call_may_start(repository):
    """The guard the executor checks before it spends money.

    The contract's first counter-example: the cancellation is persisted and a
    model call happens anyway. The only way to stop that without killing the
    process is a durable flag that the executor reads *before* it dispatches.
    """

    _create(repository)
    _checkpoint(repository)
    repository.cancel(RESEARCH, reason="user_cancelled")

    resume = repository.resume(RESEARCH)

    assert resume.cancelled is True
    assert resume.may_start_new_call is False


def test_a_live_research_may_start_a_new_call(repository):
    """The negative side of the same guard: a healthy research is not blocked.

    A guard that refuses everything is not a guard; it is an outage. This test
    exists so that the cancellation guard cannot be "implemented" by simply
    refusing to run.
    """

    _create(repository)
    _checkpoint(repository)

    resume = repository.resume(RESEARCH)

    assert resume.cancelled is False
    assert resume.may_start_new_call is True


# --- counter-example 2: the cancellation erases the findings ----------------------------


def test_a_cancellation_keeps_what_earlier_rounds_found(repository):
    """Cancelling ends the research. It does not un-learn the observations.

    The contract: the existing findings and the open questions must survive.
    A cancellation that wiped the rounds would be indistinguishable from a
    research that never ran - and it would destroy exactly the evidence the
    user was reading when they decided to stop.
    """

    _create(repository)
    _checkpoint(repository, index=0)
    _checkpoint(repository, index=1)

    repository.cancel(RESEARCH, reason="user_cancelled")

    resume = repository.resume(RESEARCH)
    assert resume is not None
    assert [record.round_index for record in resume.rounds] == [0, 1]
    assert "fact-0" in resume.evidence
    assert "fact-1" in resume.evidence


# --- counter-example 3: the in-flight call is treated as if it never happened ---------


def test_a_cancellation_does_not_pretend_the_in_flight_call_never_happened(repository):
    """A request that was already dispatched is still a request that was sent.

    The contract is explicit: an interrupted call may have run on the server
    and may have been billed, and the research must not pretend otherwise. So
    the cancellation records *what was outstanding* rather than erasing it.

    This is what keeps the ledger honest. A cancellation that reset the
    in-flight count to zero would make the research look free, and the ledger
    would later be asked to reconcile a cost that was really paid.
    """

    _create(repository)
    _checkpoint(repository)
    claimed = repository.claim(RESEARCH, owner="worker-1")

    # A worker announces a call it is about to make.
    repository.note_call_started(RESEARCH, owner="worker-1", fencing_token=claimed.fencing_token)
    repository.cancel(RESEARCH, reason="user_cancelled")

    resume = repository.resume(RESEARCH)

    assert resume is not None
    # The call was dispatched, so it is recorded as outstanding - not erased.
    assert resume.in_flight_calls == 1
    # And it is still a call that was made, so the research is not "free".
    assert resume.observed_calls == 1
