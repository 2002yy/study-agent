"""CL-M3 QD-3d: what counts as progress, and what does not.

The contract froze the second semantic on 2026-10-24
(CL_M3_CAPABILITY_CONTRACT.md §11.2): a research stops when a whole iteration
produced **no effective information gain**.

**Why the counting is not the obvious one.** It is tempting to treat "the
round did some work" as progress. That is wrong in a way that matters:
re-reading the same page produces another read event, another fact slot, and
another round - and none of it is new. A research that counts actions will run
until its timeout, which is exactly what §10.4's R-4 forbids ("禁止为耗满时间
而循环").

So the unit of progress is the **deduplicated difference** between what this
round observed and what every earlier round had already observed. Counting
actions would make a stuck research look busy.

**The counter-examples**, straight from §11.2:

1. A round that reads the same sources again counts as progress. It does not.
2. A round whose only new fact is a reworded version of an old one counts as
   progress. It does not.
3. An empty result counts as progress. It does not.
4. The *model* says it made progress. The model does not get a vote - the
   count comes from what was persisted.
5. A round with no gain ends the research as a **failure**, throwing away the
   findings. It must end it as a *stop*, keeping them.

Each of these is a test below.
"""

from __future__ import annotations

import pytest

from src.domain.research_state import (
    STATE_CHECKPOINTED,
    STATE_FAILED,
    STATE_STOPPED,
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
        _round(RESEARCH, index, evidence=evidence_of(index), urls=urls_of(index)),
        owner=owner,
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
        status=status,
    )
    if not state.terminal:
        repository.release(RESEARCH, owner=owner, fencing_token=claimed.fencing_token)
    return state


def evidence_of(index):
    return (f"fact-{index}",)


def urls_of(index):
    return (f"https://source/{index}",)


# --- the difference is computed against everything earlier, not just the last round ----


def test_progress_is_measured_against_every_earlier_round(repository):
    """A round that repeats round 0's finding is no progress - even if round 1
    saw something else in between.

    Comparing only against the immediately preceding round would let a research
    oscillate between two sets of findings forever: each round differs from the
    one before it, so each round looks like progress, and nothing is learned.
    """

    _create(repository)
    _checkpoint(repository, index=0)

    # Round 1 sees something new.
    claimed = repository.claim(RESEARCH, owner="worker-1")
    repository.checkpoint(
        RESEARCH,
        _round(RESEARCH, 1, evidence=("fact-1",), urls=("https://source/1",)),
        owner="worker-1",
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
    )
    repository.release(RESEARCH, owner="worker-1", fencing_token=claimed.fencing_token)

    # Round 2 goes back to round 0's finding. That is not new to the research.
    claimed = repository.claim(RESEARCH, owner="worker-1")
    repository.checkpoint(
        RESEARCH,
        _round(RESEARCH, 2, evidence=("fact-0",), urls=("https://source/0",)),
        owner="worker-1",
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
    )
    repository.release(RESEARCH, owner="worker-1", fencing_token=claimed.fencing_token)

    progress = repository.progress_since(RESEARCH)

    assert progress.new_evidence == ()
    assert progress.new_observation_urls == ()
    assert progress.has_gain is False


def test_a_round_with_a_genuinely_new_finding_is_progress(repository):
    """The positive side, so the guard cannot be "implemented" by always
    reporting no progress - which would stop every research after one round.
    """

    _create(repository)
    _checkpoint(repository, index=0)

    claimed = repository.claim(RESEARCH, owner="worker-1")
    repository.checkpoint(
        RESEARCH,
        _round(RESEARCH, 1, evidence=("fact-1",), urls=("https://source/1",)),
        owner="worker-1",
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
    )
    repository.release(RESEARCH, owner="worker-1", fencing_token=claimed.fencing_token)

    progress = repository.progress_since(RESEARCH)

    assert progress.new_evidence == ("fact-1",)
    assert progress.has_gain is True


# --- counter-example 1: repeating the same sources is not progress ----------------------


def test_reading_the_same_page_again_is_not_progress(repository):
    """The contract's first counter-example, and the one that matters most.

    Two rounds, the same URL, the same fact. The second round did work - it
    ran a search and read a page - and it learned nothing. A research that
    counts the second round as progress will keep going until something else
    stops it.
    """

    _create(repository)
    _checkpoint(repository, index=0)

    claimed = repository.claim(RESEARCH, owner="worker-1")
    repository.checkpoint(
        RESEARCH,
        _round(RESEARCH, 1, evidence=("fact-0",), urls=("https://source/0",)),
        owner="worker-1",
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
    )
    repository.release(RESEARCH, owner="worker-1", fencing_token=claimed.fencing_token)

    progress = repository.progress_since(RESEARCH)

    assert progress.has_gain is False
    assert progress.new_observation_urls == ()


# --- counter-example 2: a reworded fact is not a new fact -------------------------------


def test_a_reworded_fact_is_not_new_evidence(repository):
    """Different words, same finding.

    The facts in this system are opaque strings, so "the same finding said
    differently" is not something the counter can detect by comparing text.
    What it *can* detect is the *observation*: the source it came from. A
    reworded fact attached to a source that was already read is not new
    knowledge - the page was already read and had already said what it said.
    """

    _create(repository)
    _checkpoint(repository, index=0)

    claimed = repository.claim(RESEARCH, owner="worker-1")
    repository.checkpoint(
        RESEARCH,
        _round(
            RESEARCH,
            1,
            evidence=("Fact 0, but capitalised and with a period.",),
            urls=("https://source/0",),
        ),
        owner="worker-1",
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
    )
    repository.release(RESEARCH, owner="worker-1", fencing_token=claimed.fencing_token)

    progress = repository.progress_since(RESEARCH)

    # The source is not new, so there is no new knowledge behind the new wording.
    assert progress.new_observation_urls == ()
    assert progress.has_gain is False


# --- counter-example 3: an empty result is not progress ----------------------------------


def test_a_new_source_with_no_new_finding_is_not_progress(repository):
    """A new URL is not the same thing as new knowledge.

    The contract says it twice: "新观察不等于有效增量", and the first of the
    three ways to count an increment is "新增**此前未掌握**、且与当前任务
    **相关**的观察或证据" - new *and* relevant. It also says explicitly that
    "没有新内容的执行状态" does not count.

    So a round that reads a page it has not read before, and comes back with
    no new fact, has not gained anything. If that counted as progress, a
    research could read an endless supply of fresh pages that say nothing,
    and each one would reset the no-progress counter - which is exactly the
    "跑满时长" the contract forbids.

    The source here *is* new. That is the point of the test: the newness of
    the source must not be enough on its own.
    """

    _create(repository)
    _checkpoint(repository, index=0)

    claimed = repository.claim(RESEARCH, owner="worker-1")
    repository.checkpoint(
        RESEARCH,
        _round(
            RESEARCH,
            1,
            evidence=(),  # nothing new was learned
            urls=("https://source/1",),  # but a page not read before
        ),
        owner="worker-1",
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
    )
    repository.release(RESEARCH, owner="worker-1", fencing_token=claimed.fencing_token)

    progress = repository.progress_since(RESEARCH)

    assert progress.new_evidence == ()
    assert progress.has_gain is False


def test_an_empty_round_is_not_progress(repository):
    """A round that found nothing is not a round that found nothing new *and
    something else*. It found nothing at all.
    """

    _create(repository)
    _checkpoint(repository, index=0)

    claimed = repository.claim(RESEARCH, owner="worker-1")
    repository.checkpoint(
        RESEARCH,
        _round(RESEARCH, 1, evidence=(), urls=()),
        owner="worker-1",
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
    )
    repository.release(RESEARCH, owner="worker-1", fencing_token=claimed.fencing_token)

    progress = repository.progress_since(RESEARCH)

    assert progress.has_gain is False
    assert progress.new_evidence == ()


# --- counter-example 4: the model does not get a vote ------------------------------------


def test_progress_comes_from_the_persisted_record_not_from_a_claim(repository):
    """A model may report "I found something new". The count ignores it.

    The contract is explicit: the increment is determined by the executor from
    the actual record, and the model may not declare success. This test pins
    that by asking for the progress of a round whose *facts* are unchanged -
    the only way to make progress in this system is for the persisted
    observations to change.
    """

    _create(repository)
    _checkpoint(repository, index=0)

    claimed = repository.claim(RESEARCH, owner="worker-1")
    repository.checkpoint(
        RESEARCH,
        _round(RESEARCH, 1, evidence=("fact-0",), urls=("https://source/0",)),
        owner="worker-1",
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
    )
    repository.release(RESEARCH, owner="worker-1", fencing_token=claimed.fencing_token)

    progress = repository.progress_since(RESEARCH)

    assert progress.has_gain is False


# --- counter-example 5: no gain means a stop, not a failure ------------------------------


# --- counter-example 6: a fresh page with nothing new in it is not a reason to keep going ----


def test_reading_fresh_but_empty_pages_stops_the_research(repository):
    """The consequence of the rule, end to end: endless fresh-but-empty pages
    must not extend the research.

    This is the failure the rule exists to prevent. Before the fix, a round
    that opened a page nobody had read before counted as an increment *on the
    strength of the URL alone* - so a research could read an endless supply of
    fresh pages that said nothing, and every one of them would reset the
    no-progress counter. The research would run until the wall-clock budget
    ran out, which is exactly what §10.4's R-4 forbids ("禁止为耗满时间而
    循环").

    So: three rounds, each opening a **page never read before**, each
    learning **nothing**. The first round has something to show and is
    exempt by the rule's own wording. The second and third are the two
    consecutive rounds without gain, and the research must stop - keeping
    what it found, and not fetching a fourth page.

    The URLs here are all genuinely new. That is the point: the newness of
    the source must not be what keeps the research alive.
    """

    _create(repository)
    _checkpoint(repository, index=0)

    for index in (1, 2):
        claimed = repository.claim(RESEARCH, owner="worker-1")
        repository.checkpoint(
            RESEARCH,
            _round(
                RESEARCH,
                index,
                evidence=(),  # nothing new was learned
                urls=(f"https://source/{index}",),  # but a page not read before
            ),
            owner="worker-1",
            fencing_token=claimed.fencing_token,
            expected_state_version=claimed.state_version,
        )
        repository.release(RESEARCH, owner="worker-1", fencing_token=claimed.fencing_token)

    state = repository.stop_if_no_progress(RESEARCH)

    assert state is not None
    assert state.status == STATE_STOPPED
    assert state.status != STATE_FAILED
    # It stopped on purpose, and what it found is still true.
    assert "fact-0" in repository.resume(RESEARCH).evidence


def test_a_fresh_page_with_a_finding_still_keeps_the_research_running(repository):
    """The other side of the same rule, so it cannot be "implemented" by
    refusing to count any new source.

    A page that is new **and** carries a new fact is an increment. The rule
    removed the URL-only case; it did not remove progress.
    """

    _create(repository)
    _checkpoint(repository, index=0)

    claimed = repository.claim(RESEARCH, owner="worker-1")
    repository.checkpoint(
        RESEARCH,
        _round(RESEARCH, 1, evidence=("fact-1",), urls=("https://source/1",)),
        owner="worker-1",
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
    )
    repository.release(RESEARCH, owner="worker-1", fencing_token=claimed.fencing_token)

    assert repository.stop_if_no_progress(RESEARCH) is None
    state = repository.load(RESEARCH)
    assert state.status == STATE_CHECKPOINTED


def test_two_rounds_without_gain_stop_the_research_but_keep_the_findings(repository):
    """The contract's §10.8 criterion 3, and its "keep what you have" clause.

    Two consecutive rounds with no effective gain end the automatic iteration.
    They do not turn the research into a failure, and they do not throw away
    the observations that earlier rounds did produce.
    """

    _create(repository)
    _checkpoint(repository, index=0)

    claimed = repository.claim(RESEARCH, owner="worker-1")
    repository.checkpoint(
        RESEARCH,
        _round(RESEARCH, 1, evidence=("fact-0",), urls=("https://source/0",)),
        owner="worker-1",
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
    )
    repository.release(RESEARCH, owner="worker-1", fencing_token=claimed.fencing_token)

    state = repository.stop_if_no_progress(RESEARCH)

    assert state is not None
    assert state.status == STATE_STOPPED
    assert state.status != STATE_FAILED
    assert "fact-0" in repository.resume(RESEARCH).evidence
    assert state.stop_reason != ""


def test_no_progress_stop_cannot_override_an_active_worker(repository):
    """The policy cannot erase an in-flight lease from a worker it does not own."""
    _create(repository)
    _checkpoint(repository, index=0)
    second = repository.claim(RESEARCH, owner="prior-worker")
    repository.checkpoint(
        RESEARCH,
        _round(RESEARCH, 1, evidence=("fact-0",), urls=("https://source/0",)),
        owner="prior-worker",
        fencing_token=second.fencing_token,
        expected_state_version=second.state_version,
    )
    repository.release(RESEARCH, owner="prior-worker", fencing_token=second.fencing_token)

    claimed = repository.claim(RESEARCH, owner="live-worker")
    assert repository.stop_if_no_progress(RESEARCH) is None
    state = repository.load(RESEARCH)
    assert state.status != STATE_STOPPED
    assert state.lease_owner == "live-worker"
    assert state.fencing_token == claimed.fencing_token

    repository.release(RESEARCH, owner="live-worker", fencing_token=claimed.fencing_token)
    stopped = repository.stop_if_no_progress(RESEARCH)
    assert stopped is not None
    assert stopped.status == STATE_STOPPED


def test_no_progress_stop_can_finish_with_its_own_fenced_lease(repository):
    """The QD-3e coordinator checks progress before releasing its own lease."""
    _create(repository)
    _checkpoint(repository, index=0)
    second = repository.claim(RESEARCH, owner="progress-worker")
    repository.checkpoint(
        RESEARCH,
        _round(RESEARCH, 1, evidence=("fact-0",), urls=("https://source/0",)),
        owner="progress-worker",
        fencing_token=second.fencing_token,
        expected_state_version=second.state_version,
    )
    stopped = repository.stop_if_no_progress(
        RESEARCH, owner="progress-worker", fencing_token=second.fencing_token
    )
    assert stopped is not None
    assert stopped.status == STATE_STOPPED
    assert stopped.lease_owner == ""


def test_a_round_with_gain_does_not_stop_the_research(repository):
    """The negative side: a research that is still learning must keep going.

    Otherwise the "no progress" rule is indistinguishable from a rule that
    stops after one round.
    """

    _create(repository)
    _checkpoint(repository, index=0)

    claimed = repository.claim(RESEARCH, owner="worker-1")
    repository.checkpoint(
        RESEARCH,
        _round(RESEARCH, 1, evidence=("fact-1",), urls=("https://source/1",)),
        owner="worker-1",
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
    )
    repository.release(RESEARCH, owner="worker-1", fencing_token=claimed.fencing_token)

    assert repository.stop_if_no_progress(RESEARCH) is None
    state = repository.load(RESEARCH)
    assert state.status == STATE_CHECKPOINTED
