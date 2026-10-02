"""Derive a bounded learner snapshot without creating a second truth owner."""

from __future__ import annotations

from typing import Callable, Protocol

from src.domain.learner_model import (
    ConfirmedLearnerPreference,
    LearnerClaimState,
    LearnerEvaluationSummary,
    LearnerModelSnapshot,
)
from src.domain.learning_truth import (
    NextStep,
    ClaimRevisionBundle,
    LearningClaim,
    LearningGoal,
    LearningHypothesis,
    UnderstandingClaimResult,
    UnderstandingEvidence,
)
from src.pedagogy.evaluation import PedagogyEvalRun


class LearningTruthReader(Protocol):
    def get_focus_goal(self, thread_id: str) -> LearningGoal | None: ...

    def list_goal_revisions(self, goal_id: str) -> list[ClaimRevisionBundle]: ...

    def get_claim(self, claim_id: str) -> LearningClaim | None: ...

    def list_revisions(self, claim_id: str) -> list[ClaimRevisionBundle]: ...

    def list_understanding_for_revision(
        self, revision_id: str
    ) -> list[tuple[UnderstandingEvidence, UnderstandingClaimResult]]: ...

    def list_hypotheses_for_goal(self, goal_id: str) -> list[LearningHypothesis]: ...

    def list_next_steps_for_goal(self, goal_id: str) -> list[NextStep]: ...


class PedagogyEvaluationReader(Protocol):
    def list_for_thread(self, thread_id: str) -> list[PedagogyEvalRun]: ...


_MAX_CLAIM_STATES = 12
_ALLOWED_PROFILE_SECTIONS = {
    "学习偏好": "learning_preference",
    "常用任务类型": "task_preference",
}
_PLACEHOLDERS = {"暂无", "无", "待观察记录", "待确认", "none", "n/a"}
_SENSITIVE_MARKERS = (
    "年龄",
    "性别",
    "住址",
    "地域",
    "身份证",
    "手机号",
    "邮箱",
    "疾病",
    "诊断",
    "焦虑",
    "抑郁",
    "政治",
    "宗教",
    "age:",
    "gender:",
    "address:",
    "diagnosis:",
)


class LearnerModelService:
    """Project current-goal learning state and confirmed preferences on read."""

    def __init__(
        self,
        truth: LearningTruthReader,
        evaluations: PedagogyEvaluationReader,
        *,
        read_confirmed_profile: Callable[[], str],
    ) -> None:
        self.truth = truth
        self.evaluations = evaluations
        self.read_confirmed_profile = read_confirmed_profile

    def build(self, thread_id: str) -> LearnerModelSnapshot:
        goal = self.truth.get_focus_goal(thread_id)
        profile = parse_confirmed_profile(self.read_confirmed_profile())
        if goal is None:
            return LearnerModelSnapshot(
                thread_id=thread_id,
                confirmed_profile=profile,
            )

        latest = _latest_revision_per_claim(
            self.truth.list_goal_revisions(goal.id)
        )[-_MAX_CLAIM_STATES:]
        claim_states = tuple(self._claim_state(bundle) for bundle in latest)
        unresolved_count = sum(
            item.resolved_by_claim_id is None
            for item in self.truth.list_hypotheses_for_goal(goal.id)
        )
        primary_step = next(
            (
                item
                for item in self.truth.list_next_steps_for_goal(goal.id)
                if item.status == "active" and item.is_primary
            ),
            None,
        )
        matching_runs = tuple(
            run
            for run in self.evaluations.list_for_thread(thread_id)
            if run.objective.strip() == goal.objective.strip()
        )
        return LearnerModelSnapshot(
            thread_id=thread_id,
            goal_id=goal.id,
            topic_id=goal.topic_id,
            objective=goal.objective,
            goal_status=goal.status,
            claim_states=claim_states,
            unresolved_count=unresolved_count,
            next_step_id=getattr(primary_step, "id", "") or "",
            next_step_text=getattr(primary_step, "text", "") or "",
            next_step_status=getattr(primary_step, "status", "") or "",
            evaluation=_evaluation_summary(matching_runs),
            confirmed_profile=profile,
        )

    def _claim_state(self, bundle: ClaimRevisionBundle) -> LearnerClaimState:
        validations = self.truth.list_understanding_for_revision(
            bundle.revision.id
        )
        if not validations:
            for older in reversed(
                self.truth.list_revisions(bundle.revision.claim_id)
            ):
                if older.revision.id == bundle.revision.id:
                    continue
                validations = self.truth.list_understanding_for_revision(
                    older.revision.id
                )
                if validations:
                    break
        result = validations[-1][1].result if validations else "none"
        claim = self.truth.get_claim(bundle.revision.claim_id)
        return LearnerClaimState(
            claim_id=bundle.revision.claim_id,
            revision_id=bundle.revision.id,
            claim_kind=claim.claim_kind if claim is not None else "",
            understanding_status={
                "pass": "confirmed",
                "partial": "partial",
                "fail": "attempted",
                "none": "proposed",
            }.get(result, "proposed"),
            validation_result=result,
        )


def parse_confirmed_profile(text: str) -> tuple[ConfirmedLearnerPreference, ...]:
    """Read allowlisted confirmed Markdown sections and ignore pending content."""

    category = ""
    items: list[ConfirmedLearnerPreference] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            category = _ALLOWED_PROFILE_SECTIONS.get(line[3:].strip(), "")
            continue
        if not category or not line.startswith("- "):
            continue
        value = line[2:].strip()
        normalized = value.casefold()
        if (
            not value
            or normalized in _PLACEHOLDERS
            or any(marker in normalized for marker in _SENSITIVE_MARKERS)
        ):
            continue
        key = (category, value)
        if key not in seen:
            seen.add(key)
            items.append(ConfirmedLearnerPreference(category, value))
    return tuple(items)


def _latest_revision_per_claim(
    revisions: list[ClaimRevisionBundle],
) -> list[ClaimRevisionBundle]:
    latest: dict[str, ClaimRevisionBundle] = {}
    order: list[str] = []
    for bundle in revisions:
        claim_id = bundle.revision.claim_id
        if claim_id in latest:
            order.remove(claim_id)
        order.append(claim_id)
        latest[claim_id] = bundle
    return [latest[claim_id] for claim_id in order]


def _evaluation_summary(
    runs: tuple[PedagogyEvalRun, ...],
) -> LearnerEvaluationSummary:
    return LearnerEvaluationSummary(
        run_count=len(runs),
        accepted_count=sum(run.final_decision == "accept" for run in runs),
        rejected_count=sum(run.final_decision == "reject" for run in runs),
        review_required_count=sum(
            run.final_decision == "needs_semantic_review" for run in runs
        ),
        protocols=tuple(sorted({run.protocol for run in runs if run.protocol})),
        evaluator_versions=tuple(
            sorted({run.evaluator_version for run in runs if run.evaluator_version})
        ),
    )
