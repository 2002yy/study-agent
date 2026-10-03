"""§168-C: closure promotion semantics for durable misconceptions."""

from __future__ import annotations

from src.application.learning_closure_truth import LearningClosureTruthService
from src.domain.learning_truth import LearningGoal, LearningTopic
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.pedagogy.evaluation import PedagogyEvalRun, SemanticEvaluation
from src.repositories.learning_truth_repository import LearningTruthRepository


class _NoSourceEvidence:
    def search_and_converge(self, repo_url, query, *, ref=""):  # pragma: no cover
        raise AssertionError("not used by the promotion path")


class _NoEvaluations:
    def list_for_thread(self, thread_id):
        return []


def _evaluation(*, misconceptions=(), eval_id="eval-1") -> PedagogyEvalRun:
    return PedagogyEvalRun(
        id=eval_id,
        learner_input="recovery replays the full history",
        objective="recover durable resume",
        protocol="socratic_rediscovery",
        expected_concepts=("durable resume",),
        evidence=(),
        deterministic_result={"is_claim": True, "misconceptions": []},
        semantic_result=SemanticEvaluation(
            claims=("recovery replays the full history",),
            correct_points=(),
            misconceptions=tuple(misconceptions),
            reasoning_complete=False,
            transfer_ready=False,
            confidence=0.4,
            evidence_refs=(),
        ),
        confidence=0.4,
        final_decision="reject",
        reasons=("reject",),
    )


def _service(tmp_path):
    database = RuntimeDatabase(tmp_path / "truth.db")
    repo = LearningTruthRepository(database)
    topic = repo.create_topic(LearningTopic(title="t"))
    goal = repo.create_goal(
        LearningGoal(topic_id=topic.id, objective="recover durable resume")
    )
    service = LearningClosureTruthService(
        repo,
        _NoSourceEvidence(),  # type: ignore[arg-type]
        _NoEvaluations(),  # type: ignore[arg-type]
    )
    return repo, service, goal.id


def test_first_sighting_is_suspected_never_confirmed(tmp_path):
    repo, service, goal_id = _service(tmp_path)
    service._promote_misconceptions(  # noqa: SLF001
        goal_id, _evaluation(misconceptions=("replays full history",))
    )
    items = repo.list_misconceptions_for_goal(goal_id)
    assert len(items) == 1
    assert items[0].status == "suspected"
    assert items[0].occurrence_count == 1


def test_repeat_observation_bumps_count_without_confirming(tmp_path):
    repo, service, goal_id = _service(tmp_path)
    for _ in range(3):
        service._promote_misconceptions(  # noqa: SLF001
            goal_id, _evaluation(misconceptions=("replays full history",))
        )
    items = repo.list_misconceptions_for_goal(goal_id)
    assert len(items) == 1, "repeat observations must not duplicate the record"
    assert items[0].occurrence_count == 3
    assert items[0].status == "suspected", "counting must never auto-confirm"


def test_deterministic_misconceptions_are_also_promoted(tmp_path):
    repo, service, goal_id = _service(tmp_path)
    run = _evaluation()
    run = PedagogyEvalRun(
        **{
            **{k: getattr(run, k) for k in run.__dataclass_fields__},
            "deterministic_result": {"is_claim": True, "misconceptions": ["bucket drift"]},
        }
    )
    service._promote_misconceptions(goal_id, run)  # noqa: SLF001
    assert [i.description for i in repo.list_misconceptions_for_goal(goal_id)] == [
        "bucket drift"
    ]


def test_no_misconceptions_writes_nothing(tmp_path):
    repo, service, goal_id = _service(tmp_path)
    service._promote_misconceptions(goal_id, _evaluation())  # noqa: SLF001
    assert repo.list_misconceptions_for_goal(goal_id) == []
