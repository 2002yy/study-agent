from __future__ import annotations

from src.application.learning_closure_truth import LearningClosureTruthService
from src.application.learning_source_evidence import EvidenceConvergenceResult
from src.domain.learning_closure import LearningClosureRun
from src.domain.learning_truth import EvidenceBinding, SourceEvidence
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.pedagogy.evaluation import PedagogyEvalRun, SemanticEvaluation
from src.repositories.learning_truth_repository import LearningTruthRepository
from src.repositories.runtime_repository import RuntimeRepository


COMMIT_SHA = "a" * 40
TREE_SHA = "b" * 40
REPO_URL = "https://github.com/2002yy/study-agent"
SOURCE_REF = "github_source:turn-source:0"
CLAIM_TEXT = "恢复 durable learning state 不需要重放完整聊天 turns。"


class FakeSourceEvidenceService:
    def __init__(self, result: EvidenceConvergenceResult):
        self.result = result
        self.calls: list[tuple[str, str, str]] = []

    def search_and_converge(self, repo_url: str, query: str, *, ref: str = ""):
        self.calls.append((repo_url, query, ref))
        return self.result


class FakeEvaluationRepository:
    def __init__(self, evaluation: PedagogyEvalRun | None):
        self.evaluation = evaluation

    def get_for_turn(self, turn_id: str) -> PedagogyEvalRun | None:
        if self.evaluation is None or turn_id != "turn-eval":
            return None
        return self.evaluation


def _source() -> SourceEvidence:
    return SourceEvidence(
        repository="2002yy/study-agent",
        commit_sha=COMMIT_SHA,
        tree_sha=TREE_SHA,
        path="src/application/session_service.py",
        file_sha="file-sha",
        symbol="SessionService.summary_payload",
        symbol_kind="method",
        start_line=80,
        end_line=92,
        evidence_kind="search_result",
    )


def _convergence() -> EvidenceConvergenceResult:
    return EvidenceConvergenceResult(
        primary=EvidenceBinding(source=_source(), role="primary", position=0),
        candidate_count=1,
    )


def _evaluation(decision: str = "accept") -> PedagogyEvalRun:
    misconceptions = ("resume_replays_full_history",) if decision == "reject" else ()
    return PedagogyEvalRun(
        id="eval-1",
        learner_input="durable resume 直接读学习事实，所以恢复时不需要重放完整聊天 turns。",
        objective="理解 session recovery 的 durable owner",
        protocol="socratic_rediscovery",
        expected_concepts=("durable resume",),
        evidence=("source-primary",),
        deterministic_result={
            "is_claim": True,
            "misconceptions": list(misconceptions),
        },
        semantic_result=SemanticEvaluation(
            claims=(CLAIM_TEXT,),
            correct_points=("durable truth is the owner",) if decision == "accept" else (),
            misconceptions=misconceptions,
            reasoning_complete=decision == "accept",
            transfer_ready=decision == "accept",
            confidence=0.92,
            evidence_refs=("source-primary",),
        ),
        confidence=0.92,
        final_decision=decision,
        reasons=(decision,),
    )


def _run(*, include_validation_prompt: bool = True, claim_text: str = CLAIM_TEXT) -> LearningClosureRun:
    recent_dialogue = [
        {
            "turn_id": "turn-source",
            "assistant_message": "请解释：为什么恢复学习状态不需要重放完整聊天？",
            "pedagogy_move": "invite_explanation" if include_validation_prompt else "direct_explain",
        },
        {
            "turn_id": "turn-eval",
            "user_message": "durable resume 直接读学习事实，所以恢复时不需要重放完整聊天 turns。",
            "assistant_message": "对，这就是 durable owner 的边界。",
            "pedagogy_move": "minimal_repair",
        },
    ]
    return LearningClosureRun(
        id="closure-1",
        thread_id="thread-1",
        source_thread_version=2,
        last_completed_turn_id="turn-eval",
        source_hash="source-hash",
        closure_eligibility="learning_summary",
        committed_snapshot={
            "structured_input": {
                "summary_kind": "learning_summary",
                "committed_learning_state": {
                    "objective": "理解 session recovery 的 durable owner",
                },
                "final_pedagogy_evaluation": {
                    "id": "eval-1",
                    "turn_id": "turn-eval",
                },
                "github_learning_sources": [
                    {
                        "source_ref": SOURCE_REF,
                        "turn_id": "turn-source",
                        "tool_name": "github_search",
                        "repo_url": REPO_URL,
                        "query": "SessionService summary_payload durable resume",
                        "commit_sha": COMMIT_SHA,
                    }
                ],
                "recent_dialogue": recent_dialogue,
            }
        },
        generated_result={
            "durable_learning_candidate": {
                "source_ref": SOURCE_REF,
                "claim_text": claim_text,
                "claim_kind": "invariant",
                "scope": "project",
                "next_step": "下一次恢复时检查同一 Goal 是否仍可直接读取。",
                "evaluation_id": "eval-1",
                "evaluation_turn_id": "turn-eval",
            }
        },
    )


def _service(tmp_path, convergence: EvidenceConvergenceResult, evaluation=None):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    RuntimeRepository(database).ensure_chat_thread("thread-1")
    truth = LearningTruthRepository(database)
    source = FakeSourceEvidenceService(convergence)
    service = LearningClosureTruthService(
        truth,
        source,  # type: ignore[arg-type]
        FakeEvaluationRepository(evaluation),  # type: ignore[arg-type]
    )
    return database, truth, source, service


def test_explicit_closure_reconverges_source_then_commits_claim_and_understanding_once(tmp_path):
    database, truth, source, service = _service(
        tmp_path,
        _convergence(),
        _evaluation("accept"),
    )
    run = _run()

    first = service.commit(run)
    second = service.commit(run)

    assert first.status == "claim_validated"
    assert first.validation_status == "pass"
    assert first.claim_revision_id
    assert first.understanding_id
    assert second.claim_revision_id == first.claim_revision_id
    assert second.understanding_id == first.understanding_id
    assert source.calls == [
        (REPO_URL, "SessionService summary_payload durable resume", COMMIT_SHA),
        (REPO_URL, "SessionService summary_payload durable resume", COMMIT_SHA),
    ]
    goal = truth.get_goal(first.goal_id)
    assert goal is not None
    assert goal.status == "active"
    assert truth.get_focus_goal("thread-1") == goal
    assert len(truth.list_goal_revisions(first.goal_id)) == 1
    assert truth.list_understanding_for_revision(first.claim_revision_id)
    # The review read path consumes closure-owned validation without any writer.
    from datetime import datetime, timedelta, timezone

    from src.application.learning_review import LearningReviewService

    evidence, _result = truth.list_understanding_for_revision(first.claim_revision_id)[0]
    verified = datetime.fromisoformat(evidence.verified_at.replace("Z", "+00:00"))
    if verified.tzinfo is None:
        verified = verified.replace(tzinfo=timezone.utc)
    with database.connect() as connection:
        before = "\n".join(connection.iterdump())
    review = LearningReviewService(truth)
    assert not review.build("thread-1", now=verified).items[0].due
    assert review.build("thread-1", now=verified + timedelta(days=7)).items[0].due
    preview = review.preview_prompt(
        "thread-1", first.claim_revision_id, now=verified + timedelta(days=7)
    )
    assert preview.claim_revision_id == first.claim_revision_id
    assert preview.status == "preview"
    assert review.build("another-thread", now=verified).items == ()
    with database.connect() as connection:
        assert "\n".join(connection.iterdump()) == before
    steps = truth.list_next_steps_for_goal(first.goal_id)
    assert len([item for item in steps if item.status == "active" and item.is_primary]) == 1
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM learning_claims").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM claim_revisions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM understanding_evidence").fetchone()[0] == 1


def test_missing_primary_creates_hypothesis_only_and_retry_is_idempotent(tmp_path):
    database, truth, _source, service = _service(
        tmp_path,
        EvidenceConvergenceResult(unresolved_reason="provider_unavailable"),
        _evaluation("accept"),
    )
    run = _run()

    first = service.commit(run)
    second = service.commit(run)

    assert first.status == "hypothesis"
    assert first.hypothesis_id
    assert second.hypothesis_id == first.hypothesis_id
    assert len(truth.list_hypotheses_for_goal(first.goal_id)) == 1
    steps = truth.list_next_steps_for_goal(first.goal_id)
    assert len([item for item in steps if item.status == "active" and item.is_primary]) == 1
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM learning_claims").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM claim_revisions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM source_evidence").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM learning_hypotheses").fetchone()[0] == 1


def test_without_real_validation_prompt_claim_stays_unverified(tmp_path):
    database, truth, _source, service = _service(
        tmp_path,
        _convergence(),
        _evaluation("accept"),
    )

    result = service.commit(_run(include_validation_prompt=False))

    assert result.status == "claim_unverified"
    assert result.claim_revision_id
    goal = truth.get_goal(result.goal_id)
    assert goal is not None
    assert goal.status == "active"
    assert truth.list_understanding_for_revision(result.claim_revision_id) == []
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM understanding_evidence").fetchone()[0] == 0


def test_unaccepted_or_model_invented_claim_fails_closed_before_source_convergence(tmp_path):
    database, _truth, source, service = _service(
        tmp_path,
        _convergence(),
        _evaluation("reject"),
    )

    rejected = service.commit(_run())

    assert rejected.status == "validation_not_accepted"
    assert source.calls == []
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM learning_topics").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM learning_claims").fetchone()[0] == 0

    database2, _truth2, source2, service2 = _service(
        tmp_path / "invented",
        _convergence(),
        _evaluation("accept"),
    )
    invented = service2.commit(_run(claim_text="模型自己补出来的结论"))

    assert invented.status == "candidate_claim_mismatch"
    assert source2.calls == []
    with database2.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM learning_topics").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM learning_claims").fetchone()[0] == 0
