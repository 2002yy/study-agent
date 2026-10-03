from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.application.learner_model import LearnerModelService, parse_confirmed_profile
from src.domain.learning_truth import (
    NextStep,
    ClaimRevision,
    ClaimRevisionBundle,
    LearningClaim,
    LearningGoal,
    LearningHypothesis,
    UnderstandingClaimResult,
    UnderstandingEvidence,
)
from src.pedagogy.evaluation import PedagogyEvalRun


def _run(
    run_id: str,
    *,
    objective: str,
    decision: str,
    protocol: str = "feynman",
) -> PedagogyEvalRun:
    return PedagogyEvalRun(
        id=run_id,
        learner_input="raw response must not enter the snapshot",
        objective=objective,
        protocol=protocol,
        expected_concepts=("boundary",),
        evidence=("source-1",),
        deterministic_result={"reason": "claim"},
        semantic_result=None,
        confidence=0.8,
        final_decision=decision,
    )


class FakeTruthReader:
    def __init__(self) -> None:
        self.goal = LearningGoal(
            id="goal-current",
            topic_id="topic-current",
            objective="Explain the current boundary",
        )
        self.current_claim = LearningClaim(
            id="claim-current",
            topic_id=self.goal.topic_id,
            claim_kind="invariant",
        )
        self.other_claim = LearningClaim(
            id="claim-other",
            topic_id="topic-other",
            claim_kind="mechanism",
        )
        self.current_revision = ClaimRevisionBundle(
            ClaimRevision(
                id="revision-current",
                claim_id=self.current_claim.id,
                claim_text="Current goal truth",
            )
        )
        self.other_revision = ClaimRevisionBundle(
            ClaimRevision(
                id="revision-other",
                claim_id=self.other_claim.id,
                claim_text="Other goal truth",
            )
        )
        self.understanding = UnderstandingEvidence(
            id="understanding-current",
            user_response="raw understanding response must remain private",
        )
        # 165-B: an active primary durable next step, so the snapshot projection
        # that reads it is exercised rather than merely not crashing.
        self.next_step = NextStep(
            id="next-step-primary",
            goal_id=self.goal.id,
            text="Review the recovery boundary",
            status="active",
            is_primary=True,
        )
        self.calls: list[tuple[str, str]] = []

    def get_focus_goal(self, thread_id: str):
        self.calls.append(("get_focus_goal", thread_id))
        return self.goal

    def list_goal_revisions(self, goal_id: str):
        self.calls.append(("list_goal_revisions", goal_id))
        return [self.current_revision] if goal_id == self.goal.id else [self.other_revision]

    def get_claim(self, claim_id: str):
        self.calls.append(("get_claim", claim_id))
        return self.current_claim if claim_id == self.current_claim.id else self.other_claim

    def list_revisions(self, claim_id: str):
        self.calls.append(("list_revisions", claim_id))
        return [self.current_revision] if claim_id == self.current_claim.id else []

    def list_understanding_for_revision(self, revision_id: str):
        self.calls.append(("list_understanding_for_revision", revision_id))
        if revision_id != self.current_revision.revision.id:
            return []
        return [
            (
                self.understanding,
                UnderstandingClaimResult(
                    understanding_evidence_id=self.understanding.id,
                    claim_revision_id=revision_id,
                    result="pass",
                ),
            )
        ]

    def list_next_steps_for_goal(self, goal_id: str):
        self.calls.append(("list_next_steps_for_goal", goal_id))
        return [self.next_step]

    def list_hypotheses_for_goal(self, goal_id: str):
        self.calls.append(("list_hypotheses_for_goal", goal_id))
        return [
            LearningHypothesis(
                id="hypothesis-open",
                topic_id=self.goal.topic_id,
                goal_id=goal_id,
                text="Current unresolved gap",
            ),
            LearningHypothesis(
                id="hypothesis-resolved",
                topic_id=self.goal.topic_id,
                goal_id=goal_id,
                text="Resolved gap",
                resolved_by_claim_id=self.current_claim.id,
            ),
        ]


class FakeEvaluationReader:
    def __init__(self, runs: list[PedagogyEvalRun]) -> None:
        self.runs = runs
        self.calls: list[str] = []

    def list_for_thread(self, thread_id: str):
        self.calls.append(thread_id)
        return list(self.runs)


PROFILE = """# 学习者档案

## 学习偏好
- 喜欢先看机制再看结论
- 焦虑时需要安慰

## 常用任务类型
- 源码审计
- 年龄：20

## 角色视角
- 某角色认为用户容易分心

## 待确认区
- 喜欢所有回答都很长
"""


def test_snapshot_derives_only_current_goal_and_matching_evaluations() -> None:
    truth = FakeTruthReader()
    evaluations = FakeEvaluationReader(
        [
            _run("eval-accept", objective=truth.goal.objective, decision="accept"),
            _run("eval-review", objective=truth.goal.objective, decision="needs_semantic_review"),
            _run("eval-other", objective="Other goal", decision="reject"),
        ]
    )
    service = LearnerModelService(
        truth,
        evaluations,
        read_confirmed_profile=lambda: PROFILE,
    )

    snapshot = service.build("thread-current")
    payload = snapshot.to_dict()

    assert snapshot.source == "derived_read_only"
    assert snapshot.goal_id == truth.goal.id
    assert snapshot.topic_id == truth.goal.topic_id
    assert snapshot.unresolved_count == 1
    assert [item.claim_id for item in snapshot.claim_states] == ["claim-current"]
    assert snapshot.claim_states[0].understanding_status == "confirmed"
    assert snapshot.evaluation.run_count == 2
    assert snapshot.evaluation.accepted_count == 1
    assert snapshot.evaluation.review_required_count == 1
    assert snapshot.evaluation.rejected_count == 0
    assert "claim-other" not in str(payload)
    assert "raw response" not in str(payload)
    assert "raw understanding" not in str(payload)


def test_confirmed_profile_parser_excludes_pending_role_sensitive_and_placeholders() -> None:
    parsed = parse_confirmed_profile(
        PROFILE
        + """
## 学习偏好
- 待观察记录
- 喜欢先看机制再看结论
## 待确认区
- 尚未确认的偏好
"""
    )

    assert [(item.category, item.value) for item in parsed] == [
        ("learning_preference", "喜欢先看机制再看结论"),
        ("task_preference", "源码审计"),
    ]


def test_snapshot_is_deterministic_immutable_and_uses_read_operations_only() -> None:
    truth = FakeTruthReader()
    evaluations = FakeEvaluationReader(
        [_run("eval-1", objective=truth.goal.objective, decision="accept")]
    )
    service = LearnerModelService(
        truth,
        evaluations,
        read_confirmed_profile=lambda: PROFILE,
    )

    first = service.build("thread-current")
    second = service.build("thread-current")

    assert first == second
    assert first.to_dict() == second.to_dict()
    # 165-B: the primary durable next step is projected read-only.
    assert first.next_step_id == "next-step-primary"
    assert first.next_step_text == "Review the recovery boundary"
    assert first.next_step_status == "active"
    assert ("list_next_steps_for_goal", "goal-current") in truth.calls
    assert not hasattr(first, "id")
    assert not hasattr(first, "created_at")
    assert all(
        name.startswith(("get_", "list_"))
        for name, _argument in truth.calls
    )
    with pytest.raises(FrozenInstanceError):
        first.goal_id = "mutated"  # type: ignore[misc]


def test_snapshot_without_active_goal_keeps_only_confirmed_profile() -> None:
    truth = FakeTruthReader()
    truth.goal = None
    evaluations = FakeEvaluationReader(
        [_run("eval-orphan", objective="Old goal", decision="accept")]
    )

    snapshot = LearnerModelService(
        truth,
        evaluations,
        read_confirmed_profile=lambda: PROFILE,
    ).build("thread-empty")

    assert snapshot.goal_id == ""
    assert snapshot.claim_states == ()
    assert snapshot.evaluation.run_count == 0
    assert evaluations.calls == []
    assert snapshot.confirmed_profile
