"""§168-C: durable misconception storage layer (domain + schema + repository)."""

from __future__ import annotations

from src.domain.learning_truth import LearningGoal, LearnerMisconception, LearningTopic
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.learning_truth_repository import LearningTruthRepository


def _repo(tmp_path) -> tuple[LearningTruthRepository, str]:
    database = RuntimeDatabase(tmp_path / "truth.db")
    repo = LearningTruthRepository(database)
    topic = repo.create_topic(LearningTopic(title="t"))
    goal = repo.create_goal(LearningGoal(topic_id=topic.id, objective="recover durable resume"))
    return repo, goal.id


def test_create_and_get_roundtrip(tmp_path):
    repo, goal_id = _repo(tmp_path)
    item = repo.create_misconception(
        LearnerMisconception(
            goal_id=goal_id,
            description="believes recovery replays full history",
            source_eval_ref="eval-1",
        )
    )
    fetched = repo.get_misconception(item.id)
    assert fetched is not None
    assert fetched.description == "believes recovery replays full history"
    # Promotion default: a first sighting is suspected, never confirmed.
    assert fetched.status == "suspected"
    assert fetched.occurrence_count == 1


def test_list_for_goal(tmp_path):
    repo, goal_id = _repo(tmp_path)
    repo.create_misconception(
        LearnerMisconception(goal_id=goal_id, description="a")
    )
    repo.create_misconception(
        LearnerMisconception(goal_id=goal_id, description="b")
    )
    assert len(repo.list_misconceptions_for_goal(goal_id)) == 2


def test_find_by_description_is_case_insensitive(tmp_path):
    repo, goal_id = _repo(tmp_path)
    repo.create_misconception(
        LearnerMisconception(goal_id=goal_id, description="Replay Full History")
    )
    found = repo.find_misconception_by_description(goal_id, "replay full history")
    assert found is not None
    assert found.description == "Replay Full History"


def test_empty_description_is_rejected(tmp_path):
    repo, goal_id = _repo(tmp_path)
    try:
        repo.create_misconception(
            LearnerMisconception(goal_id=goal_id, description="   ")
        )
    except ValueError as exc:
        assert "description" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("empty description must be rejected")


def test_status_vocabulary_is_constrained(tmp_path):
    repo, goal_id = _repo(tmp_path)
    # The schema only permits the three lifecycle states.
    repo.create_misconception(
        LearnerMisconception(goal_id=goal_id, description="x", status="confirmed")
    )
    items = repo.list_misconceptions_for_goal(goal_id)
    assert items[0].status == "confirmed"
