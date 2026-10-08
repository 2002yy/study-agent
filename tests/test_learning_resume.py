from __future__ import annotations

from src.application.learning_outcome_commit import LearningOutcomeCommitService
from src.application.learning_resume import LearningResumeService
from src.application.learning_source_evidence import EvidenceConvergenceResult
from src.domain.learning_truth import (
    EvidenceBinding,
    LearningGoal,
    LearningHypothesis,
    LearningTopic,
    NextStep,
    SourceEvidence,
    UnderstandingClaimResult,
    UnderstandingEvidence,
)
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.learning_truth_repository import LearningTruthRepository
from src.repositories.runtime_repository import RuntimeRepository


COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
TREE_SHA = "c" * 40


def _source(*, commit: str = COMMIT_A, line: int = 10) -> SourceEvidence:
    return SourceEvidence(
        repository="2002yy/study-agent",
        commit_sha=commit,
        tree_sha=TREE_SHA,
        path="src/application/learning_resume.py",
        file_sha=f"file-{commit}",
        symbol="LearningResumeService.build",
        symbol_kind="method",
        start_line=line,
        end_line=line,
        evidence_kind="search_result",
    )


def _convergence(*, commit: str = COMMIT_A, line: int = 10) -> EvidenceConvergenceResult:
    return EvidenceConvergenceResult(
        primary=EvidenceBinding(
            source=_source(commit=commit, line=line),
            role="primary",
            position=0,
        ),
        candidate_count=1,
    )


def _setup(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
    thread = runtime.ensure_chat_thread("thread-resume")
    truth = LearningTruthRepository(database)
    topic = truth.create_topic(LearningTopic(title="Durable resume"))
    goal, _context = truth.create_goal_for_thread(
        LearningGoal(topic_id=topic.id, objective="Resume from durable truth"),
        thread_id=thread.id,
        focus_pinned=True,
    )
    return database, runtime, truth, thread, topic, goal


def test_durable_resume_uses_latest_revision_and_bounded_semantic_state(tmp_path):
    _database, _runtime, truth, thread, topic, goal = _setup(tmp_path)
    outcome_service = LearningOutcomeCommitService(truth)

    first = outcome_service.commit(
        topic_id=topic.id,
        goal_id=goal.id,
        claim_text="Resume derives from durable Goal state.",
        claim_kind="invariant",
        convergence=_convergence(),
    )
    assert first.claim is not None and first.revision is not None

    other_revisions = []
    for index in range(3):
        item = outcome_service.commit(
            topic_id=topic.id,
            goal_id=goal.id,
            claim_text=f"Additional durable fact {index}.",
            claim_kind="mechanism",
            convergence=_convergence(line=30 + index),
        )
        assert item.revision is not None
        other_revisions.append(item.revision.revision)

    # Revalidate the first Claim last. Resume recency must follow the latest
    # Revision activity rather than the Claim's original creation position.
    second = outcome_service.commit(
        topic_id=topic.id,
        goal_id=goal.id,
        claim_text="Resume derives from the latest durable Goal revision.",
        claim_kind="invariant",
        convergence=_convergence(commit=COMMIT_B, line=20),
        existing_claim_id=first.claim.id,
        revision_reason="revalidated",
    )
    assert second.revision is not None

    pass_evidence = UnderstandingEvidence(
        method="apply",
        prompt="Why does durable resume not require replaying chat?",
        user_response="Because the Goal and ClaimRevision are persisted separately.",
    )
    truth.create_understanding_evidence(
        pass_evidence,
        (
            UnderstandingClaimResult(
                understanding_evidence_id=pass_evidence.id,
                claim_revision_id=second.revision.revision.id,
                result="pass",
            ),
        ),
    )
    fail_evidence = UnderstandingEvidence(
        method="explain",
        prompt="Explain additional fact 2.",
        user_response="Incorrect explanation that should not appear in resume context.",
    )
    truth.create_understanding_evidence(
        fail_evidence,
        (
            UnderstandingClaimResult(
                understanding_evidence_id=fail_evidence.id,
                claim_revision_id=other_revisions[-1].id,
                result="fail",
            ),
        ),
    )

    hypothesis = truth.create_hypothesis(
        LearningHypothesis(
            topic_id=topic.id,
            goal_id=goal.id,
            text="One edge path still needs evidence.",
            unresolved_reason="insufficient_evidence",
        )
    )
    primary_step = truth.create_next_step(
        NextStep(goal_id=goal.id, text="Inspect the edge path", is_primary=True)
    )
    truth.create_next_step(NextStep(goal_id=goal.id, text="Optional review A"))
    truth.create_next_step(NextStep(goal_id=goal.id, text="Optional review B"))
    truth.create_next_step(NextStep(goal_id=goal.id, text="Optional review C"))

    resume = LearningResumeService(truth).build(thread.id)

    assert resume["source"] == "durable"
    assert resume["status"] == "active"
    assert resume["topic"]["topic_id"] == topic.id
    assert resume["goal"]["goal_id"] == goal.id
    assert resume["claim_count"] == 4
    assert len(resume["claims"]) == 3
    assert all(
        claim["revision_id"] != first.revision.revision.id
        for claim in resume["claims"]
    )
    latest = next(
        claim for claim in resume["claims"] if claim["claim_id"] == first.claim.id
    )
    assert latest["revision_id"] == second.revision.revision.id
    assert latest["understanding_status"] == "confirmed"
    assert latest["validation_result"] == "pass"
    # Learning State-1 §2.1 (T07): confirmed durable understanding is the only
    # mastery evidence, and its provenance is explicit.
    assert latest["authority"]["authority"] == "verified"
    assert latest["authority"]["is_mastery_evidence"] is True
    assert latest["primary_evidence"]["commit_sha"] == COMMIT_B
    assert "user_response" not in latest["latest_validation"]
    failed = next(
        claim
        for claim in resume["claims"]
        if claim["revision_id"] == other_revisions[-1].id
    )
    assert failed["understanding_status"] == "attempted"
    assert failed["validation_result"] == "fail"
    # Learning State-1 §2.1 (T08): a non-confirmed durable status is not mastery.
    assert failed["authority"]["authority"] == "system_inferred"
    assert failed["authority"]["is_mastery_evidence"] is False
    assert resume["unresolved"] == [
        {
            "hypothesis_id": hypothesis.id,
            "text": "One edge path still needs evidence.",
            "reason": "insufficient_evidence",
        }
    ]
    assert resume["next_step"]["next_step_id"] == primary_step.id
    assert len(resume["optional_next_steps"]) == 2


def test_durable_context_with_no_active_goal_never_resurrects_legacy_state(tmp_path):
    _database, _runtime, truth, thread, _topic, goal = _setup(tmp_path)
    truth.update_goal_status(goal.id, "completed")

    resume = LearningResumeService(truth).build(
        thread.id,
        legacy_navigation={
            "objective": "OLD LEGACY OBJECTIVE",
            "confirmed_points": ["OLD LEGACY CONFIRMED"],
            "next_action": "OLD LEGACY NEXT",
        },
    )

    assert resume["source"] == "durable"
    assert resume["status"] == "no_active_goal"
    assert resume["goal"] == {}
    assert resume["claims"] == []
    assert "legacy_confirmed_points" not in resume
    assert "OLD LEGACY" not in str(resume)


def test_legacy_fallback_keeps_old_confirmed_points_outside_formal_claims(tmp_path):
    database = RuntimeDatabase(tmp_path / "legacy.db")
    runtime = RuntimeRepository(database)
    thread = runtime.ensure_chat_thread("legacy-thread")
    truth = LearningTruthRepository(database)

    resume = LearningResumeService(truth).build(
        thread.id,
        legacy_navigation={
            "objective": "Legacy objective",
            "confirmed_points": ["legacy point one", "legacy point two"],
            "unresolved_gap": "legacy gap",
            "next_action": "legacy next",
        },
    )

    assert resume["source"] == "legacy_fallback"
    assert resume["status"] == "legacy"
    assert resume["claims"] == []
    assert resume["claim_count"] == 0
    assert resume["legacy_confirmed_points"] == [
        "legacy point one",
        "legacy point two",
    ]
    # Learning State-1 §2.1/§6 (T03): legacy points are read-only labelled and
    # are never mastery evidence.
    authorities = resume["legacy_confirmed_points_authority"]
    assert {item["authority"] for item in authorities} == {"legacy_unverified"}
    assert all(item["is_mastery_evidence"] is False for item in authorities)
    assert resume["goal"] == {
        "objective": "Legacy objective",
        "status": "legacy_unverified",
    }
    assert resume["next_step"]["status"] == "legacy_unverified"


def test_empty_thread_without_durable_or_legacy_learning_state_is_empty(tmp_path):
    database = RuntimeDatabase(tmp_path / "empty.db")
    runtime = RuntimeRepository(database)
    thread = runtime.ensure_chat_thread("empty-thread")
    truth = LearningTruthRepository(database)

    resume = LearningResumeService(truth).build(thread.id)

    assert resume["source"] == "legacy_fallback"
    assert resume["status"] == "empty"
    assert resume["claims"] == []
    assert resume["goal"] == {}
    assert resume["next_step"] == {}
