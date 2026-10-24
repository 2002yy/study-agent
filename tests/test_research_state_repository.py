"""CL-M3 QD-3a: a finished round is a durable fact, and only one worker may write.

The milestone these tests aim at is the one that decides whether long research is possible at
all: finish round 1, write the checkpoint, lose the worker, let a new one take over, and
continue at round 2 without repeating the search, without buying the same call twice and
without losing what round 1 found.

What is and is not simulated. Each "worker" here is a fresh repository over a fresh
connection to the same file, holding no state besides ``self.database`` - which is exactly
what a restarted process would have. What this does *not* prove is that the operating system
actually kills a worker mid-round and that the lease then expires on its own; that needs a
real process (QD-3e). The persistence half is proven here, and labelled as such.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from src.domain.research_state import (
    MAX_FACTS_PER_ROUND,
    ResearchRound,
    ResearchState,
    research_request_key,
)
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.research_state_repository import (
    ResearchAlreadyTerminal,
    ResearchLeaseHeld,
    ResearchNotFound,
    ResearchStateRepository,
    StaleResearchWriter,
)

THREAD = "chat-durable-1"
OPERATION = "op-durable-1"
RESEARCH = "research-durable-1"

BASE = datetime(2026, 10, 24, 2, 0, 0, tzinfo=timezone.utc)


def at(seconds: float) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat()


def build(path):
    RuntimeDatabase(path).initialize()


def repo(path) -> ResearchStateRepository:
    """A worker: a new repository over a new connection, holding no state."""
    return ResearchStateRepository(RuntimeDatabase(path))


def started(path, **changes):
    values = {
        "research_id": RESEARCH,
        "thread_id": THREAD,
        "operation_id": OPERATION,
        "original_question": "Agent-native 美术管线怎么接 Godot",
        "question": "Agent-native 美术管线怎么接 Godot",
        "tier": "standard",
        "quota_observed": {"searches": 40, "reads": 80, "decisions": 30, "tokens": 900000},
        "now": at(0),
    }
    values.update(changes)
    repo(path).create(**values)
    return values["research_id"]


def round_zero(**changes) -> ResearchRound:
    values = {
        "research_id": RESEARCH,
        "round_index": 0,
        "question": "Agent-native 美术管线怎么接 Godot",
        "queries": ("Godot 4 Krita 导入 管线",),
        "observation_urls": ("https://docs.godotengine.org/pipeline",),
        "evidence": ("Godot 4 通过 glTF 2.0 导入 Krita 导出资源",),
        "stop_reason": "continue",
        "created_at": at(10),
    }
    values.update(changes)
    return ResearchRound(**values)


# --- the milestone ---------------------------------------------------------------------


def test_a_finished_round_survives_its_worker_and_the_next_round_continues(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)

    # Worker A runs round 0 and checkpoints it.
    a = repo(path)
    state = a.claim(RESEARCH, owner="worker-a", ttl_seconds=30, now=at(5))
    assert state.fencing_token == 1
    after = a.checkpoint(
        RESEARCH,
        round_zero(),
        owner="worker-a",
        fencing_token=state.fencing_token,
        expected_state_version=state.state_version,
        question="Godot 4 导入管线里哪些步骤要自动化",
        quota_observed={"searches": 39, "reads": 79, "decisions": 29, "tokens": 880000},
        now=at(10),
    )
    assert after.round_index == 1

    # Worker A dies here: no release, no cleanup. Its lease simply expires.
    del a

    # Worker B is a new process: new repositories, new connections, no memory of A.
    b = repo(path)
    resumed = b.resume(RESEARCH)
    assert resumed is not None
    # It starts after the round that finished, not at the original question.
    assert resumed.next_round_index == 1
    assert resumed.rounds[0].queries == ("Godot 4 Krita 导入 管线",)
    assert resumed.evidence == ("Godot 4 通过 glTF 2.0 导入 Krita 导出资源",)
    # And it knows which queries are already paid for.
    assert resumed.executed_queries == ("Godot 4 Krita 导入 管线",)

    # The stale lease does not block the takeover.
    taken = b.claim(RESEARCH, owner="worker-b", ttl_seconds=30, now=at(60))
    assert taken.fencing_token == 2
    # The budget it inherited is the one the last checkpoint recorded, not the original.
    assert taken.quota_observed["searches"] == 39


def test_the_second_round_is_written_after_the_first_without_repeating_it(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    a = repo(path)
    state = a.claim(RESEARCH, owner="worker-a", ttl_seconds=30, now=at(5))
    a.checkpoint(
        RESEARCH,
        round_zero(),
        owner="worker-a",
        fencing_token=state.fencing_token,
        expected_state_version=state.state_version,
        now=at(10),
    )

    b = repo(path)
    taken = b.claim(RESEARCH, owner="worker-b", ttl_seconds=30, now=at(60))
    second = ResearchRound(
        research_id=RESEARCH,
        round_index=taken.next_round_index,
        question="哪些步骤要自动化",
        queries=("Godot import pipeline automation",),
        observation_urls=("https://example.org/automation",),
        evidence=("导入步骤可以脚本化",),
        created_at=at(70),
    )
    final = b.checkpoint(
        RESEARCH,
        second,
        owner="worker-b",
        fencing_token=taken.fencing_token,
        expected_state_version=taken.state_version,
        now=at(80),
    )

    assert final.round_index == 2
    assert [row.round_index for row in b.rounds(RESEARCH)] == [0, 1]
    # Nothing round 0 found was lost by the handover.
    assert b.resume(RESEARCH).evidence == (
        "Godot 4 通过 glTF 2.0 导入 Krita 导出资源",
        "导入步骤可以脚本化",
    )


# --- who may write ---------------------------------------------------------------------


def test_a_live_lease_cannot_be_claimed_by_a_second_worker(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    repo(path).claim(RESEARCH, owner="worker-a", ttl_seconds=30, now=at(0))

    with pytest.raises(ResearchLeaseHeld):
        repo(path).claim(RESEARCH, owner="worker-b", ttl_seconds=30, now=at(10))


def test_a_superseded_worker_cannot_checkpoint_after_a_takeover(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    a = repo(path)
    old = a.claim(RESEARCH, owner="worker-a", ttl_seconds=10, now=at(0))

    b = repo(path)
    new = b.claim(RESEARCH, owner="worker-b", ttl_seconds=30, now=at(60))
    assert new.fencing_token == old.fencing_token + 1

    # A wakes up late and tries to write its round anyway.
    with pytest.raises(StaleResearchWriter):
        a.checkpoint(
            RESEARCH,
            round_zero(),
            owner="worker-a",
            fencing_token=old.fencing_token,
            expected_state_version=old.state_version,
            now=at(70),
        )
    assert b.rounds(RESEARCH) == ()


def test_the_same_owner_name_reacquiring_is_a_different_writer(tmp_path):
    # The case an owner string alone would miss: same name, later generation.
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    first = repo(path).claim(RESEARCH, owner="worker", ttl_seconds=10, now=at(0))
    second = repo(path).claim(RESEARCH, owner="worker", ttl_seconds=30, now=at(60))

    assert second.fencing_token == first.fencing_token + 1
    with pytest.raises(StaleResearchWriter):
        repo(path).checkpoint(
            RESEARCH,
            round_zero(),
            owner="worker",
            fencing_token=first.fencing_token,
            expected_state_version=first.state_version,
            now=at(70),
        )


def test_a_checkpoint_with_a_stale_state_version_is_refused(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    state = repo(path).claim(RESEARCH, owner="worker-a", ttl_seconds=30, now=at(0))
    repo(path).checkpoint(
        RESEARCH,
        round_zero(),
        owner="worker-a",
        fencing_token=state.fencing_token,
        expected_state_version=state.state_version,
        now=at(10),
    )

    with pytest.raises(StaleResearchWriter):
        repo(path).checkpoint(
            RESEARCH,
            round_zero(round_index=1, created_at=at(20)),
            owner="worker-a",
            fencing_token=state.fencing_token,
            expected_state_version=state.state_version,  # the version before round 0
            now=at(20),
        )
    # And the round row it tried to write went with it: no half-applied checkpoint.
    assert [row.round_index for row in repo(path).rounds(RESEARCH)] == [0]


def test_a_round_belonging_to_another_research_is_refused(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    state = repo(path).claim(RESEARCH, owner="worker-a", ttl_seconds=30, now=at(0))

    with pytest.raises(ValueError, match="research_round_owner_mismatch"):
        repo(path).checkpoint(
            RESEARCH,
            round_zero(research_id="research-somebody-else"),
            owner="worker-a",
            fencing_token=state.fencing_token,
            expected_state_version=state.state_version,
            now=at(10),
        )


def test_a_renewal_from_a_superseded_worker_is_refused(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    old = repo(path).claim(RESEARCH, owner="worker-a", ttl_seconds=10, now=at(0))
    repo(path).claim(RESEARCH, owner="worker-b", ttl_seconds=30, now=at(60))

    with pytest.raises(StaleResearchWriter):
        repo(path).renew(
            RESEARCH,
            owner="worker-a",
            fencing_token=old.fencing_token,
            ttl_seconds=30,
            now=at(70),
        )


def test_a_release_from_a_superseded_worker_does_not_steal_the_lease(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    old = repo(path).claim(RESEARCH, owner="worker-a", ttl_seconds=10, now=at(0))
    current = repo(path).claim(RESEARCH, owner="worker-b", ttl_seconds=30, now=at(60))

    repo(path).release(RESEARCH, owner="worker-a", fencing_token=old.fencing_token)

    still_owned = repo(path).load(RESEARCH)
    assert still_owned is not None
    assert still_owned.lease_owner == "worker-b"
    assert still_owned.fencing_token == current.fencing_token


def test_release_frees_the_lease_so_the_next_worker_need_not_wait(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    state = repo(path).claim(RESEARCH, owner="worker-a", ttl_seconds=300, now=at(0))
    repo(path).release(
        RESEARCH, owner="worker-a", fencing_token=state.fencing_token
    )

    taken = repo(path).claim(RESEARCH, owner="worker-b", ttl_seconds=30, now=at(1))
    assert taken.lease_owner == "worker-b"
    assert taken.fencing_token == state.fencing_token + 1


def test_a_terminal_research_cannot_be_claimed(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    state = repo(path).claim(RESEARCH, owner="worker-a", ttl_seconds=30, now=at(0))
    repo(path).checkpoint(
        RESEARCH,
        round_zero(stop_reason="evidence_sufficient"),
        owner="worker-a",
        fencing_token=state.fencing_token,
        expected_state_version=state.state_version,
        status="stopped",
        now=at(10),
    )

    with pytest.raises(ResearchAlreadyTerminal):
        repo(path).claim(RESEARCH, owner="worker-b", ttl_seconds=30, now=at(60))


def test_a_terminal_checkpoint_hands_the_lease_back(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    state = repo(path).claim(RESEARCH, owner="worker-a", ttl_seconds=300, now=at(0))
    done = repo(path).checkpoint(
        RESEARCH,
        round_zero(stop_reason="no_progress"),
        owner="worker-a",
        fencing_token=state.fencing_token,
        expected_state_version=state.state_version,
        status="stopped",
        now=at(10),
    )

    assert done.terminal
    assert done.lease_owner == ""


# --- atomicity and monotonicity ---------------------------------------------------------


def test_a_duplicate_round_rolls_back_its_own_round_row(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    state = repo(path).claim(RESEARCH, owner="worker-a", ttl_seconds=30, now=at(0))
    repo(path).checkpoint(
        RESEARCH,
        round_zero(),
        owner="worker-a",
        fencing_token=state.fencing_token,
        expected_state_version=state.state_version,
        now=at(10),
    )

    # Round 0 again: out of order, so refused - and it must not leave a second row behind.
    with pytest.raises(StaleResearchWriter):
        repo(path).checkpoint(
            RESEARCH,
            round_zero(created_at=at(20)),
            owner="worker-a",
            fencing_token=state.fencing_token,
            expected_state_version=2,
            now=at(20),
        )

    assert [row.round_index for row in repo(path).rounds(RESEARCH)] == [0]


def test_a_checkpoint_may_lower_the_observed_quota(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    state = repo(path).claim(RESEARCH, owner="worker-a", ttl_seconds=30, now=at(0))
    after = repo(path).checkpoint(
        RESEARCH,
        round_zero(),
        owner="worker-a",
        fencing_token=state.fencing_token,
        expected_state_version=state.state_version,
        quota_observed={"searches": 12, "tokens": 500},
        now=at(10),
    )
    assert after.quota_observed == {"searches": 12, "tokens": 500}


def test_a_checkpoint_may_not_raise_the_observed_quota(tmp_path):
    # A resumed worker that could raise its own ceiling would have found a refund.
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    state = repo(path).claim(RESEARCH, owner="worker-a", ttl_seconds=30, now=at(0))
    repo(path).checkpoint(
        RESEARCH,
        round_zero(),
        owner="worker-a",
        fencing_token=state.fencing_token,
        expected_state_version=state.state_version,
        quota_observed={"searches": 10},
        now=at(10),
    )

    with pytest.raises(ValueError, match="quota_may_not_increase:searches"):
        repo(path).checkpoint(
            RESEARCH,
            round_zero(round_index=1, created_at=at(20)),
            owner="worker-a",
            fencing_token=state.fencing_token,
            expected_state_version=2,
            quota_observed={"searches": 11},
            now=at(20),
        )
    assert [row.round_index for row in repo(path).rounds(RESEARCH)] == [0]


def test_an_unknown_quota_key_is_refused(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    with pytest.raises(ValueError, match="unknown_quota_key:cost"):
        started(path, quota_observed={"cost": 10})


# --- scanning for work -----------------------------------------------------------------


def test_resumable_offers_between_round_work_but_not_a_live_lease(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    repo(path).claim(RESEARCH, owner="worker-a", ttl_seconds=30, now=at(0))

    assert repo(path).resumable(limit=10, now=at(10)) == ()
    offered = repo(path).resumable(limit=10, now=at(60))
    assert [row.research_id for row in offered] == [RESEARCH]


def test_resumable_never_offers_a_terminal_research(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    state = repo(path).claim(RESEARCH, owner="worker-a", ttl_seconds=30, now=at(0))
    repo(path).checkpoint(
        RESEARCH,
        round_zero(stop_reason="evidence_sufficient"),
        owner="worker-a",
        fencing_token=state.fencing_token,
        expected_state_version=state.state_version,
        status="stopped",
        now=at(10),
    )

    assert repo(path).resumable(limit=10, now=at(60)) == ()


# --- identity and bounds ---------------------------------------------------------------


def test_request_keys_are_stable_across_workers_and_differ_by_round():
    first = research_request_key(RESEARCH, 0, "plan")
    # Recomputing it in a fresh "process" (here: just again) must give the same key, or a
    # restart would buy the same call a second time.
    assert research_request_key(RESEARCH, 0, "plan") == first
    assert research_request_key(RESEARCH, 1, "plan") != first
    assert research_request_key(RESEARCH, 0, "search") != first
    assert first.startswith("research:")


@pytest.mark.parametrize(
    "round_index,stage",
    [(-1, "plan"), (0, "Plan"), (0, ""), (0, "plan-dash")],
)
def test_an_invalid_request_identity_is_refused(round_index, stage):
    with pytest.raises(ValueError):
        research_request_key(RESEARCH, round_index, stage)


def test_a_round_with_too_much_evidence_is_refused_rather_than_truncated():
    with pytest.raises(ValueError, match="evidence_exceeds_round_cap"):
        ResearchRound(
            research_id=RESEARCH,
            round_index=0,
            question="q",
            evidence=tuple(f"事实 {index}" for index in range(MAX_FACTS_PER_ROUND + 1)),
        )


def test_the_state_refuses_an_unknown_tier():
    with pytest.raises(ValueError, match="invalid_tier"):
        ResearchState(
            research_id=RESEARCH,
            thread_id=THREAD,
            operation_id=OPERATION,
            original_question="q",
            question="q",
            tier="turbo",
        )


def test_a_missing_research_is_absent_rather_than_invented(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    assert repo(path).load("research-missing") is None
    assert repo(path).resume("research-missing") is None
    with pytest.raises(ResearchNotFound):
        repo(path).claim("research-missing", owner="worker-a", now=at(0))


def test_creating_the_same_research_twice_is_refused(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    started(path)
    with pytest.raises(ValueError, match="research_already_exists"):
        started(path)


def test_the_schema_version_covers_the_allocation_gap():
    # 25 and 26 belong to the AR and spend lines; this branch must not reuse them.
    from src.infrastructure.sqlite.database import MIGRATIONS, SCHEMA_VERSION

    versions = [version for version, _ in MIGRATIONS]
    assert versions == sorted(versions)
    assert version_in(versions, 27)
    assert SCHEMA_VERSION == max(versions)
    assert not version_in(versions, 25) and not version_in(versions, 26)


def version_in(versions, target):
    return target in versions


def test_the_two_tables_are_created_by_the_migration(tmp_path):
    path = tmp_path / "durable.sqlite"
    build(path)
    with sqlite3.connect(path) as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"research_states", "research_rounds"} <= names
