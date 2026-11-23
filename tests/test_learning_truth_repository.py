from __future__ import annotations

import sqlite3

import pytest

from src.domain.learning_truth import (
    ClaimRevision,
    EvidenceBinding,
    LearningClaim,
    LearningGoal,
    LearningHypothesis,
    LearningTopic,
    NextStep,
    SourceEvidence,
    UnderstandingClaimResult,
    UnderstandingEvidence,
)
from src.domain.runtime_entities import ChatThread
from src.infrastructure.sqlite.database import (
    MIGRATIONS,
    RuntimeDatabase,
    SCHEMA_VERSION,
    apply_migrations,
)
from src.repositories.learning_truth_repository import LearningTruthRepository
from src.repositories.runtime_repository import RuntimeRepository


COMMIT_SHA = "a" * 40
TREE_SHA = "b" * 40


def _source(
    *,
    source_id: str = "source-primary",
    path: str = "src/service.py",
    symbol: str = "Service.run",
    start_line: int = 10,
) -> SourceEvidence:
    return SourceEvidence(
        id=source_id,
        repository="2002yy/study-agent",
        commit_sha=COMMIT_SHA,
        tree_sha=TREE_SHA,
        path=path,
        file_sha=f"file-{path}",
        symbol=symbol,
        symbol_kind="method",
        start_line=start_line,
        end_line=start_line,
        evidence_kind="search_result",
    )


def _seed_topic_goal_claim(repository: LearningTruthRepository):
    topic = repository.create_topic(LearningTopic(title="Source evidence"))
    goal = repository.create_goal(
        LearningGoal(topic_id=topic.id, objective="Understand source evidence identity")
    )
    claim = repository.create_claim(
        LearningClaim(topic_id=topic.id, claim_kind="invariant")
    )
    return topic, goal, claim


def _build_v16_database(db_path) -> None:
    with sqlite3.connect(db_path) as connection:
        for version, sql in MIGRATIONS:
            if version >= 17:
                break
            connection.executescript(sql)
            connection.execute(
                "INSERT OR REPLACE INTO runtime_meta(key, value) VALUES('schema_version', ?)",
                (str(version),),
            )
        connection.commit()


def test_runtime_initializes_normalized_learning_truth_tables(tmp_path):
    db_path = tmp_path / "runtime.db"
    RuntimeDatabase(db_path).initialize()

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        version = connection.execute(
            "SELECT value FROM runtime_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        source_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(source_evidence)")
        }

    assert version == str(SCHEMA_VERSION)
    assert {
        "learning_topics",
        "learning_goals",
        "learning_goal_prerequisites",
        "learning_claims",
        "claim_revisions",
        "source_evidence",
        "claim_revision_evidence",
        "understanding_evidence",
        "understanding_evidence_claims",
        "learning_hypotheses",
        "next_steps",
    } <= tables
    assert {
        "query",
        "rank",
        "score",
        "confidence",
        "provider_status",
        "selection_reason",
        "metadata",
    }.isdisjoint(source_columns)


def test_v16_upgrade_preserves_existing_runtime_data(tmp_path):
    db_path = tmp_path / "runtime.db"
    _build_v16_database(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO chat_threads(
                id, status, settings_snapshot, created_at, updated_at, version,
                learning_state
            ) VALUES ('legacy', 'active', '{}', 'now', 'now', 1,
                      '{"confirmed_points":["legacy-only"]}')
            """
        )
        connection.commit()

    RuntimeDatabase(db_path).initialize()

    with sqlite3.connect(db_path) as connection:
        version = connection.execute(
            "SELECT value FROM runtime_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        state = connection.execute(
            "SELECT learning_state FROM chat_threads WHERE id = 'legacy'"
        ).fetchone()[0]
        claim_count = connection.execute("SELECT COUNT(*) FROM learning_claims").fetchone()[0]
        evidence_count = connection.execute("SELECT COUNT(*) FROM source_evidence").fetchone()[0]

    assert version == str(SCHEMA_VERSION)
    assert "legacy-only" in state
    assert claim_count == 0
    assert evidence_count == 0


def test_v17_migration_failure_rolls_back_cleanly(tmp_path):
    db_path = tmp_path / "runtime.db"
    _build_v16_database(db_path)

    def fail_during_v17(version: int, index: int) -> None:
        if version == 17 and index == 4:
            raise RuntimeError("injected v17 failure")

    with sqlite3.connect(db_path) as connection:
        with pytest.raises(RuntimeError, match="injected v17"):
            apply_migrations(connection, after_statement=fail_during_v17)
        version = connection.execute(
            "SELECT value FROM runtime_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        learning_tables = connection.execute(
            """
            SELECT COUNT(*) FROM sqlite_master
            WHERE type = 'table' AND name IN ('learning_topics', 'learning_goals')
            """
        ).fetchone()[0]
        ledger = connection.execute(
            "SELECT status FROM runtime_migrations WHERE version = 17"
        ).fetchone()[0]

    assert version == "16"
    assert learning_tables == 0
    assert ledger == "failed"

    RuntimeDatabase(db_path).initialize()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT value FROM runtime_meta WHERE key = 'schema_version'"
        ).fetchone()[0] == str(SCHEMA_VERSION)
        assert connection.execute(
            "SELECT status FROM runtime_migrations WHERE version = 17"
        ).fetchone()[0] == "completed"
        assert connection.execute(
            "SELECT status FROM runtime_migrations WHERE version = 18"
        ).fetchone()[0] == "completed"


def test_repository_round_trip_survives_restart(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = LearningTruthRepository(database)
    topic, goal, claim = _seed_topic_goal_claim(repository)
    revision = ClaimRevision(
        claim_id=claim.id,
        claim_text="Source evidence is pinned to an exact repository state.",
        source_commit=COMMIT_SHA,
    )
    primary = _source()
    support = _source(
        source_id="source-support",
        path="tests/test_service.py",
        symbol="test_service_run",
        start_line=20,
    )

    committed = repository.commit_revision(
        revision,
        (
            EvidenceBinding(source=primary, role="primary", position=0),
            EvidenceBinding(
                source=support,
                role="supporting_corroborating",
                position=1,
            ),
        ),
    )

    restarted = LearningTruthRepository(database)
    stored = restarted.get_revision(revision.id)

    assert restarted.get_topic(topic.id) == topic
    assert restarted.get_goal(goal.id) == goal
    assert restarted.get_claim(claim.id) == claim
    assert stored == committed
    assert stored is not None
    assert [item.role for item in stored.evidence] == [
        "primary",
        "supporting_corroborating",
    ]


def test_revision_boundary_requires_one_primary_and_at_most_four_supporting(tmp_path):
    repository = LearningTruthRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    _topic, _goal, claim = _seed_topic_goal_claim(repository)

    with pytest.raises(ValueError, match="exactly one primary"):
        repository.commit_revision(
            ClaimRevision(claim_id=claim.id, claim_text="invalid"),
            (
                EvidenceBinding(source=_source(source_id="a"), role="primary", position=0),
                EvidenceBinding(
                    source=_source(source_id="b", path="src/b.py", symbol="b", start_line=2),
                    role="primary",
                    position=1,
                ),
            ),
        )

    too_many = [EvidenceBinding(source=_source(), role="primary", position=0)]
    for index in range(5):
        too_many.append(
            EvidenceBinding(
                source=_source(
                    source_id=f"support-{index}",
                    path=f"tests/test_{index}.py",
                    symbol=f"test_{index}",
                    start_line=index + 1,
                ),
                role="supporting_corroborating",
                position=index + 1,
            )
        )
    with pytest.raises(ValueError, match="at most four"):
        repository.commit_revision(
            ClaimRevision(claim_id=claim.id, claim_text="also invalid"),
            tuple(too_many),
        )


def test_revision_transaction_rolls_back_partial_source_writes(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = LearningTruthRepository(database)
    _topic, _goal, claim = _seed_topic_goal_claim(repository)
    revision = ClaimRevision(claim_id=claim.id, claim_text="must roll back")

    first = _source(source_id="collision", path="src/a.py", symbol="a", start_line=1)
    second = _source(source_id="collision", path="src/b.py", symbol="b", start_line=2)

    with pytest.raises(sqlite3.IntegrityError):
        repository.commit_revision(
            revision,
            (
                EvidenceBinding(source=first, role="primary", position=0),
                EvidenceBinding(
                    source=second,
                    role="supporting_corroborating",
                    position=1,
                ),
            ),
        )

    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM claim_revisions WHERE id = ?", (revision.id,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM source_evidence WHERE id = 'collision'"
        ).fetchone()[0] == 0


def test_revision_and_source_identity_are_immutable(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = LearningTruthRepository(database)
    _topic, _goal, claim = _seed_topic_goal_claim(repository)
    revision = ClaimRevision(claim_id=claim.id, claim_text="immutable truth")
    source = _source()
    repository.commit_revision(
        revision,
        (EvidenceBinding(source=source, role="primary", position=0),),
    )

    with database.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE claim_revisions SET claim_text = 'rewritten' WHERE id = ?",
                (revision.id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE source_evidence SET path = 'other.py' WHERE id = ?",
                (source.id,),
            )


def test_prerequisite_cycle_is_rejected(tmp_path):
    repository = LearningTruthRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    topic = repository.create_topic(LearningTopic(title="Dependencies"))
    first = repository.create_goal(LearningGoal(topic_id=topic.id, objective="First"))
    second = repository.create_goal(LearningGoal(topic_id=topic.id, objective="Second"))
    third = repository.create_goal(LearningGoal(topic_id=topic.id, objective="Third"))

    repository.add_prerequisite(first.id, second.id)
    repository.add_prerequisite(second.id, third.id)

    with pytest.raises(ValueError, match="cycle"):
        repository.add_prerequisite(third.id, first.id)

    assert repository.list_prerequisite_ids(first.id) == [second.id]
    assert repository.list_prerequisite_ids(second.id) == [third.id]
    assert repository.list_prerequisite_ids(third.id) == []


def test_understanding_hypothesis_and_next_step_use_normalized_relations(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = LearningTruthRepository(database)
    topic, goal, claim = _seed_topic_goal_claim(repository)
    revision = ClaimRevision(claim_id=claim.id, claim_text="testable claim")
    repository.commit_revision(
        revision,
        (EvidenceBinding(source=_source(), role="primary", position=0),),
        goal_id=goal.id,
    )

    understanding = UnderstandingEvidence(
        method="apply",
        prompt="What happens if CI is unavailable?",
        user_response="Source identity remains valid.",
    )
    result = UnderstandingClaimResult(
        understanding_evidence_id=understanding.id,
        claim_revision_id=revision.id,
        result="pass",
    )
    written, _, _ = repository.commit_semantic_closure(
        goal_id=goal.id, understanding=understanding, results=(result,)
    )
    assert written == understanding

    hypothesis = repository.create_hypothesis(
        LearningHypothesis(
            topic_id=topic.id,
            goal_id=goal.id,
            text="A different recovery path may behave differently.",
            unresolved_reason="insufficient_evidence",
        )
    )
    next_step = repository.create_next_step(
        NextStep(goal_id=goal.id, text="Inspect the alternate recovery path", is_primary=True)
    )

    assert repository.get_understanding_evidence(understanding.id) == (
        understanding,
        (result,),
    )
    assert repository.get_hypothesis(hypothesis.id) == hypothesis
    assert repository.get_next_step(next_step.id) == next_step

    with pytest.raises(sqlite3.IntegrityError):
        repository.create_next_step(
            NextStep(goal_id=goal.id, text="Second active primary", is_primary=True)
        )


def test_legacy_learning_state_is_never_promoted_into_formal_truth(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
    runtime.create_chat_thread(
        ChatThread(
            learning_state={
                "confirmed_points": ["legacy summary is not formal mastery"],
                "next_action": "legacy next",
            }
        )
    )

    LearningTruthRepository(database)

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM learning_claims").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM claim_revisions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM source_evidence").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM understanding_evidence").fetchone()[0] == 0
