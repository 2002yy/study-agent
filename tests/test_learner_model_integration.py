from __future__ import annotations

from src.application.learner_model import LearnerModelService
from src.application.learning_outcome_commit import LearningOutcomeCommitService
from src.application.learning_source_evidence import EvidenceConvergenceResult
from src.domain.learning_truth import (
    EvidenceBinding,
    LearningGoal,
    LearningHypothesis,
    LearningTopic,
    SourceEvidence,
    UnderstandingClaimResult,
    UnderstandingEvidence,
)
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.domain.runtime_entities import ChatTurn
from src.pedagogy.evaluation import PedagogyEvalRun
from src.repositories.learning_truth_repository import LearningTruthRepository
from src.repositories.pedagogy_eval_repository import PedagogyEvalRepository
from src.repositories.runtime_repository import RuntimeRepository


def _database_state(database: RuntimeDatabase) -> dict[str, tuple[tuple[object, ...], ...]]:
    with database.connect() as connection:
        table_names = [
            row[0]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        ]
        return {
            table_name: tuple(
                tuple(row)
                for row in connection.execute(
                    f'SELECT * FROM "{table_name}" ORDER BY rowid'
                ).fetchall()
            )
            for table_name in table_names
        }


def test_snapshot_derives_from_real_repositories_without_database_writes(tmp_path) -> None:
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
    thread = runtime.ensure_chat_thread("thread-learner-model")
    truth = LearningTruthRepository(database)
    evaluations = PedagogyEvalRepository(database)
    topic = truth.create_topic(LearningTopic(title="Read-only learner model"))
    goal, _context = truth.create_goal_for_thread(
        LearningGoal(topic_id=topic.id, objective="Explain a stable boundary"),
        thread_id=thread.id,
        focus_pinned=True,
    )

    source = SourceEvidence(
        repository="2002yy/study-agent",
        commit_sha="a" * 40,
        tree_sha="b" * 40,
        path="src/application/learner_model.py",
        file_sha="source-file",
        symbol="LearnerModelService.build",
        symbol_kind="method",
        start_line=1,
        end_line=1,
    )
    committed = LearningOutcomeCommitService(truth).commit(
        topic_id=topic.id,
        goal_id=goal.id,
        claim_text="A snapshot derives state without owning it.",
        claim_kind="invariant",
        convergence=EvidenceConvergenceResult(
            primary=EvidenceBinding(source=source, role="primary", position=0),
            candidate_count=1,
        ),
    )
    assert committed.revision is not None
    understanding = UnderstandingEvidence(
        method="explain",
        prompt="Why is the snapshot read-only?",
        user_response="Because repositories remain the truth owners.",
    )
    truth.commit_semantic_closure(
        goal_id=goal.id,
        understanding=understanding,
        results=(
            UnderstandingClaimResult(
                understanding_evidence_id=understanding.id,
                claim_revision_id=committed.revision.revision.id,
                result="pass",
            ),
        ),
    )
    truth.create_hypothesis(
        LearningHypothesis(
            topic_id=topic.id,
            goal_id=goal.id,
            text="One boundary remains unresolved.",
        )
    )
    turn = runtime.add_chat_turn(
        ChatTurn(
            id="turn-learner-model",
            thread_id=thread.id,
            user_message="Explain the boundary.",
            assistant_message="The snapshot reads existing truth.",
            status="completed",
        )
    )
    with database.connect() as connection:
        PedagogyEvalRepository.insert(
            connection,
            run=PedagogyEvalRun(
                id="eval-learner-model",
                learner_input="Private raw learner response.",
                objective=goal.objective,
                protocol="feynman",
                expected_concepts=("boundary",),
                evidence=("source-1",),
                deterministic_result={"is_claim": True},
                semantic_result=None,
                confidence=1.0,
                final_decision="accept",
            ),
            thread_id=thread.id,
            turn_id=turn.id,
            created_at="2026-08-12T00:00:00Z",
        )

    before = _database_state(database)
    snapshot = LearnerModelService(
        truth,
        evaluations,
        read_confirmed_profile=lambda: "## 学习偏好\n- 先看机制再看结论",
    ).build(thread.id)
    after = _database_state(database)

    assert after == before
    assert snapshot.goal_id == goal.id
    assert snapshot.claim_states[0].understanding_status == "confirmed"
    assert snapshot.unresolved_count == 1
    assert snapshot.evaluation.accepted_count == 1
    assert snapshot.confirmed_profile[0].value == "先看机制再看结论"
    assert "Private raw learner response" not in str(snapshot.to_dict())
    assert "repositories remain the truth owners" not in str(snapshot.to_dict())
