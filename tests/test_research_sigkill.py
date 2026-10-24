"""CL-M3 QD-3e: kill a real process and check that the research survives.

**Why a real process.** QD-3b tested the takeover with a lease written in
the past: the lease was expired by the clock, and a second worker took over.
That is the right *shape* of a crash, but it is not a crash. It never
exercises the parts of a real death that a simulated one cannot:

- the process really is gone, so nothing in it can write anything later;
- its **file handles** are closed by the operating system, not by Python;
- the sqlite connection it held is released by the OS, which is what lets
  another process write to the file at all;
- and it leaves behind whatever a killed process leaves behind - a journal
  file, a partially written page, a lock that was never released cleanly.

A test that claims "the worker was killed" while keeping it alive in the
same process is a test of a *story*, not of the behaviour. The milestone in
QD-3b's own words was "a worker dies mid-research and another one finishes
it", and this file is where that sentence is actually true.

**What is asserted, and what would be a lie.** The test asserts that:

1. the child process really died (its exit status says so, and it is the
   status of a killed process, not a clean exit);
2. the round it finished before dying is still on record;
3. another worker - a *different* one, in this process - takes the research
   over and continues it;
4. and the dead child's late write is refused.

Point 4 is the one that matters most, and it is asserted through the
fencing token rather than through a comment: the dead child cannot write
because its token is stale, and the test proves the token moved.

**What this test does not claim.** It does not claim the research would
survive a machine losing power, nor that the SQLite file is never corrupt.
It claims the thing that the design actually promises: the database is the
authority, a dead worker's work is not lost, and its late writes are
refused.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.application.research_coordinator import ResearchCoordinator
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.research_state_repository import (
    ResearchLeaseHeld,
    ResearchStateRepository,
    StaleResearchWriter,
)
from tests.research_test_executor import ScriptedExecutor, ScriptedStep

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

RESEARCH = "research-sigkill"
THREAD = "thread-sigkill"
OPERATION = "operation-sigkill"

# The child writes a line to stdout as soon as it is ready to be killed. The
# parent waits for that line rather than sleeping, because a sleep is a
# guess and a guess is how a test kills a process that has not started yet.
READY_MARKER = "READY-FOR-KILL"


def _child_source(db_path: str) -> str:
    """The program the child process runs.

    It is written as a source string rather than as a file so that the test
    has no fixture to clean up and no file that could be stale. The child:

    - opens the same database the parent will use;
    - claims the research and runs one round, so there is a completed round
      on record before the kill;
    - then *keeps the lease* and announces that it is ready to die.

    Holding the lease is the interesting part. The coordinator hands the
    lease back between rounds, so a crash between rounds is boring: the
    next worker gets the research immediately. A crash *inside* a round is
    the one where the lease is still held and the replacement has to wait
    for it to expire - and that wait is exactly what a real kill produces
    and a simulated one has to fake.
    """

    return f'''
import os
import sys
import time

sys.path.insert(0, {str(REPO_ROOT)!r})

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.research_state_repository import ResearchStateRepository
from src.application.research_coordinator import ResearchCoordinator
from tests.research_test_executor import ScriptedExecutor, ScriptedStep

db_path = {db_path!r}
database = RuntimeDatabase(db_path)
database.initialize()
repository = ResearchStateRepository(database)

# One round, and then hold the lease instead of handing it back.
executor = ScriptedExecutor(
    [ScriptedStep(action="checkpoint"), ScriptedStep(action="checkpoint")],
)
coordinator = ResearchCoordinator(
    repository,
    executor=executor,
    owner="child-worker",
    rounds_per_scan=1,
    lease_seconds=3600.0,
)
coordinator.scan_once()

# Claim again and keep it: this is what a process that died *inside* a round
# looks like to the database. The lease is short, so the test does not have
# to wait an hour for it to expire.
held = repository.claim(
    {RESEARCH!r},
    owner="child-worker",
    ttl_seconds=2.0,
)
sys.stdout.write("{READY_MARKER} %d %d\\n" % (os.getpid(), held.fencing_token))
sys.stdout.flush()

# Stay alive until the parent kills us.
while True:
    time.sleep(0.05)
'''


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "runtime.sqlite")


@pytest.fixture
def repository(db_path):
    database = RuntimeDatabase(db_path)
    database.initialize()
    repo = ResearchStateRepository(database)
    repo.create(
        research_id=RESEARCH,
        thread_id=THREAD,
        operation_id=OPERATION,
        original_question="what survives a kill?",
        question="what survives a kill?",
        tier="standard",
    )
    return repo


def _start_child(db_path: str) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.Popen(
        [PYTHON, "-c", _child_source(db_path)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def _kill(child: subprocess.Popen, pid: int) -> None:
    """Kill the child the way a crash kills a process.

    **There is no ``SIGKILL`` on Windows.** ``signal.SIGKILL`` does not exist
    there, and the process is killed with ``TerminateProcess`` instead -
    which is the same thing the operating system does to a process that
    faults, and the same thing this test means.

    The distinction matters because the difference between the two platforms
    is exactly the difference this test is about: on both, the process is
    killed **without running any cleanup code**. There is no ``atexit``
    hook, no ``finally`` block, no chance to release the lease. The
    database sees a process that stopped existing mid-round, which is the
    situation the fencing token exists for.
    """

    if hasattr(signal, "SIGKILL"):
        os.kill(pid, signal.SIGKILL)
    else:  # pragma: no cover - the Windows path
        child.kill()


def _wait_for_ready(child: subprocess.Popen, timeout: float = 60.0) -> tuple[int, int]:
    """Wait for the child to announce that it is ready to be killed.

    Returns the child's pid and the fencing token it held. A timeout here
    means the child never got that far, and the test says so rather than
    killing a process that was not ready.
    """

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = child.stdout.readline()
        if not line:
            if child.poll() is not None:
                stderr = child.stderr.read()
                raise AssertionError(
                    f"the child exited before it was ready: {child.returncode}\n{stderr}"
                )
            continue
        if line.startswith(READY_MARKER):
            _, pid, token = line.split()
            return int(pid), int(token)
    raise AssertionError("the child did not become ready in time")


def _wait_for_lease_expiry(repository, timeout: float = 30.0) -> None:
    """Wait until the dead child's lease has genuinely run out.

    This waits on the **real clock** rather than pretending the lease was
    written in the past. The reason is the point: a crashed worker's lease
    is in the future, and a replacement that takes over too early would be
    taking over from a worker that is still running. Waiting for the real
    expiry is what a real deployment does, and it is the only way the test
    exercises the takeover path that production will actually take.
    """

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = repository.load(RESEARCH)
        if state is None:
            raise AssertionError("the research vanished while waiting for the lease")
        if state.lease_expires_at <= _now():
            return
        time.sleep(0.1)
    raise AssertionError("the dead child's lease did not expire in time")


def _now() -> str:
    from src.domain.runtime_entities import utc_now

    return utc_now()


def test_a_killed_process_leaves_its_round_and_loses_the_rest(repository, db_path):
    """The milestone, with a real kill.

    The child finishes round 0, takes the lease, and is killed. The round
    must survive, and the research must be continuable by somebody else.
    """

    child = _start_child(db_path)
    try:
        pid, token = _wait_for_ready(child)

        # The child really is a separate process, and it really holds the
        # lease - so the research is not offered to anybody right now.
        state = repository.load(RESEARCH)
        assert state.lease_owner == "child-worker"
        assert state.fencing_token == token
        assert len(repository.rounds(RESEARCH)) == 1

        # Kill it the way a crash kills a process: no cleanup, no goodbye.
        _kill(child, pid)
        child.wait(timeout=30)
        assert child.returncode is not None
        # A killed process does not exit cleanly. On Windows the status is
        # the terminate code; on POSIX it is the signal.
        assert child.returncode != 0
    finally:
        if child.poll() is None:  # pragma: no cover - only on a failure path
            child.kill()
            child.wait(timeout=10)

    # The round it finished is still on record. The kill did not take the
    # work with it.
    rounds = repository.rounds(RESEARCH)
    assert len(rounds) == 1
    assert rounds[0].round_index == 0

    # And the research is still open, waiting for somebody to pick it up.
    state = repository.load(RESEARCH)
    assert state.round_index == 1
    assert state.status != "failed"


def test_another_worker_takes_over_a_killed_process_research(repository, db_path):
    """A second worker continues the research a killed process was running.

    The second worker is in *this* process, so the two are genuinely
    separate: one died, one continues. It must start from the round the
    dead one finished, and it must not repeat that round's work.
    """

    child = _start_child(db_path)
    try:
        pid, token = _wait_for_ready(child)
        _kill(child, pid)
        child.wait(timeout=30)
    finally:
        if child.poll() is None:  # pragma: no cover - only on a failure path
            child.kill()
            child.wait(timeout=10)

    # The dead child's lease is still recorded, and it has not expired - a
    # killed process does not release its lease. So the research is not
    # offered to the replacement yet, which is the honest behaviour: the
    # database cannot know the holder is dead until the lease runs out.
    #
    # This is where QD-3b's simulation was easier than reality. It wrote the
    # lease in the past, so the takeover was immediate. A real lease is in
    # the **future**, and a real crash leaves it there: the replacement has
    # to wait it out. That wait is the behaviour worth testing, so the test
    # waits it out rather than faking it.
    held = repository.load(RESEARCH)
    assert held.lease_owner == "child-worker"
    assert held.lease_expires_at != ""

    # The replacement cannot take it yet.
    with pytest.raises(ResearchLeaseHeld):
        repository.claim(RESEARCH, owner="replacement-worker", ttl_seconds=300.0)

    # And once the lease runs out, the replacement - which is a coordinator,
    # not a manual claim - takes it over and continues. The takeover is the
    # coordinator's own work: it discovers, claims and advances, and the
    # claim is what moves the fencing token.
    _wait_for_lease_expiry(repository)
    replacement = ResearchCoordinator(
        repository,
        executor=ScriptedExecutor([ScriptedStep(action="checkpoint")]),
        owner="replacement-worker",
    )
    result = replacement.scan_once()

    assert result.rounds == 1
    # The takeover bumped the token, so the dead child's write is now stale.
    assert repository.load(RESEARCH).fencing_token > token
    # The replacement ran round 1 - the round after the dead worker's.
    rounds = repository.rounds(RESEARCH)
    assert [r.round_index for r in rounds] == [0, 1]
    # And it did not repeat the dead worker's search.
    assert rounds[0].queries == ("query-0",)
    assert rounds[1].queries == ("query-1",)


def test_the_killed_process_cannot_write_after_being_replaced(repository, db_path):
    """The dead worker's late write is refused.

    This is the property that makes "kill it and start another" safe rather
    than merely convenient: the replacement's work and the original's work
    can never both land. The refusal comes from the fencing token, and the
    test proves the token moved by using the dead worker's own token.
    """

    child = _start_child(db_path)
    try:
        pid, token = _wait_for_ready(child)
        _kill(child, pid)
        child.wait(timeout=30)
    finally:
        if child.poll() is None:  # pragma: no cover - only on a failure path
            child.kill()
            child.wait(timeout=10)

    # Somebody else takes over, and the takeover bumps the token.
    _wait_for_lease_expiry(repository)
    taken = repository.claim(
        RESEARCH,
        owner="replacement-worker",
        ttl_seconds=300.0,
    )
    assert taken.fencing_token > token

    # The dead worker's write - with the token it held - is refused.
    from src.domain.research_state import ResearchRound

    with pytest.raises(StaleResearchWriter):
        repository.checkpoint(
            RESEARCH,
            ResearchRound(
                research_id=RESEARCH,
                round_index=1,
                question="what survives a kill?",
                queries=("query-1",),
                evidence=("zombie-fact",),
            ),
            owner="child-worker",
            fencing_token=token,
            expected_state_version=repository.load(RESEARCH).state_version,
        )

    # The refused write left nothing behind.
    assert len(repository.rounds(RESEARCH)) == 1
