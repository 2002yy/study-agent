"""Bounded resume projection derived from durable P2-D learning truth.

ResumeContext is navigation, not a second truth owner. It is rebuilt from durable
Topic/Goal/ClaimRevision/Evidence/Understanding/Hypothesis/NextStep state on read.
Legacy learning_state is used only when a thread has never acquired durable Goal
context.
"""

from __future__ import annotations

from typing import Any, Protocol

from src.application.learning_authority_projection import (
    classify_durable_understanding_status,
    classify_legacy_confirmed_points,
)
from src.domain.learning_truth import (
    ClaimRevisionBundle,
    LearningGoal,
    NextStep,
)
from src.repositories.learning_truth_repository import LearningTruthRepository


class FreshnessEvaluator(Protocol):
    """On-demand source-freshness evaluation for a Claim revision bundle."""

    def evaluate(
        self,
        bundle: ClaimRevisionBundle,
        *,
        ref: str = "",
    ) -> Any: ...


_MAX_RESUME_CLAIMS = 3
_MAX_RESUME_HYPOTHESES = 3
_MAX_OPTIONAL_NEXT_STEPS = 2


class LearningResumeService:
    """Build the compact semantic state needed to continue learning."""

    def __init__(
        self,
        repository: LearningTruthRepository,
        freshness_evaluator: FreshnessEvaluator | None = None,
    ) -> None:
        self.repository = repository
        self.freshness_evaluator = freshness_evaluator

    def build(
        self,
        thread_id: str,
        *,
        legacy_navigation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        durable_goals = self.repository.list_goals_for_thread(thread_id)
        if not durable_goals:
            return self._legacy_fallback(legacy_navigation or {})

        goal = self.repository.get_focus_goal(thread_id)
        if goal is None:
            return {
                "source": "durable",
                "status": "no_active_goal",
                "topic": {},
                "goal": {},
                "claims": [],
                "claim_count": 0,
                "unresolved": [],
                "next_step": {},
                "optional_next_steps": [],
            }

        topic = self.repository.get_topic(goal.topic_id)
        latest_revisions = _latest_revision_per_claim(
            self.repository.list_goal_revisions(goal.id)
        )
        claim_count = len(latest_revisions)
        selected_revisions = latest_revisions[-_MAX_RESUME_CLAIMS:]
        if self.freshness_evaluator is None:
            claims = [
                self._claim_projection(bundle) for bundle in selected_revisions
            ]
        else:
            claims = [
                self._claim_projection(
                    bundle, freshness=self._evaluate_freshness(bundle)
                )
                for bundle in selected_revisions
            ]

        hypotheses = [
            item
            for item in self.repository.list_hypotheses_for_goal(goal.id)
            if item.resolved_by_claim_id is None
        ][-_MAX_RESUME_HYPOTHESES:]
        active_steps = [
            item
            for item in self.repository.list_next_steps_for_goal(goal.id)
            if item.status == "active"
        ]
        primary_step, optional_steps = _select_next_steps(active_steps)

        return {
            "source": "durable",
            "status": "active",
            "topic": (
                {
                    "topic_id": topic.id,
                    "title": topic.title,
                    "scope": topic.scope,
                }
                if topic is not None
                else {}
            ),
            "goal": _goal_projection(goal),
            "claims": claims,
            "claim_count": claim_count,
            "unresolved": [
                {
                    "hypothesis_id": item.id,
                    "text": item.text,
                    "reason": item.unresolved_reason,
                }
                for item in hypotheses
            ],
            "next_step": _next_step_projection(primary_step),
            "optional_next_steps": [
                _next_step_projection(item) for item in optional_steps
            ],
        }

    def _claim_projection(
        self,
        bundle: ClaimRevisionBundle,
        *,
        freshness: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        claim = self.repository.get_claim(bundle.revision.claim_id)
        validations = self._understanding_for_lineage(bundle)
        latest_validation = validations[-1] if validations else None
        validation_result = (
            latest_validation[1].result if latest_validation is not None else "none"
        )
        understanding_status = {
            "pass": "confirmed",
            "partial": "partial",
            "fail": "attempted",
            "none": "proposed",
        }[validation_result]
        primary = next(
            (item for item in bundle.evidence if item.role == "primary"),
            None,
        )
        supporting = [item for item in bundle.evidence if item.role != "primary"]
        projection = {
            "claim_id": bundle.revision.claim_id,
            "revision_id": bundle.revision.id,
            "text": bundle.revision.claim_text,
            "claim_kind": claim.claim_kind if claim is not None else "",
            "scope": claim.scope if claim is not None else "",
            "understanding_status": understanding_status,
            "validation_result": validation_result,
            # Learning State-1 §2.1/§6: read-only authority. Only a durable
            # confirmed understanding is mastery evidence; the caller resolves
            # lineage-validated status, this label does not re-derive it.
            "authority": classify_durable_understanding_status(
                understanding_status,
                text=bundle.revision.claim_text,
                source_id=bundle.revision.id,
            ).to_dict(),
            "latest_validation": (
                {
                    "method": latest_validation[0].method,
                    "result": latest_validation[1].result,
                    "verified_at": latest_validation[0].verified_at,
                }
                if latest_validation is not None
                else {}
            ),
            "primary_evidence": _evidence_projection(primary),
            "supporting_evidence": [
                _evidence_projection(item) for item in supporting
            ],
        }
        if freshness is not None:
            projection["freshness"] = freshness
        return projection


    def _understanding_for_lineage(
        self,
        bundle: ClaimRevisionBundle,
    ) -> list[tuple[Any, Any]]:
        """Resolve understanding evidence along the Claim lineage.

        Understanding belongs to the Claim, not to a single Revision snapshot, so
        an explicit revalidation (which never decides mastery) must not reset the
        projection to ``proposed`` just because the newest Revision has no
        evidence row of its own yet.
        """
        validations = self.repository.list_understanding_for_revision(
            bundle.revision.id
        )
        if validations:
            return validations
        for older in reversed(
            self.repository.list_revisions(bundle.revision.claim_id)
        ):
            if older.revision.id == bundle.revision.id:
                continue
            validations = self.repository.list_understanding_for_revision(
                older.revision.id
            )
            if validations:
                return validations
        return []

    def _evaluate_freshness(self, bundle: ClaimRevisionBundle) -> dict[str, Any]:
        if self.freshness_evaluator is None:
            return {}
        try:
            evaluation = self.freshness_evaluator.evaluate(bundle)
        except Exception as exc:  # noqa: BLE001 - provider boundary explicit
            return {
                "status": "unavailable",
                "unavailable_reason": f"{type(exc).__name__}: {exc}",
            }
        primary = _freshness_detail(evaluation.primary, drift=False)
        supporting_drift = tuple(
            _freshness_detail(item, drift=True)
            for item in evaluation.supporting_drift
        )
        return {
            "status": str(evaluation.status),
            "head_commit": str(evaluation.head_commit or ""),
            "reason": str(primary.get("reason") or ""),
            "primary": primary,
            "supporting_drift": supporting_drift,
            "unavailable_reason": str(evaluation.unavailable_reason or ""),
        }

    @staticmethod
    def _legacy_fallback(navigation: dict[str, Any]) -> dict[str, Any]:
        objective = str(navigation.get("objective") or "").strip()
        unresolved_gap = str(navigation.get("unresolved_gap") or "").strip()
        next_action = str(navigation.get("next_action") or "").strip()
        raw_confirmed = navigation.get("confirmed_points")
        legacy_points = (
            [str(item) for item in raw_confirmed[:3]]
            if isinstance(raw_confirmed, list)
            else []
        )
        return {
            "source": "legacy_fallback",
            "status": "legacy" if objective or unresolved_gap or next_action or legacy_points else "empty",
            "topic": {},
            "goal": (
                {
                    "objective": objective,
                    "status": "legacy_unverified",
                }
                if objective
                else {}
            ),
            "claims": [],
            "claim_count": 0,
            "unresolved": (
                [{"text": unresolved_gap, "reason": "legacy_unverified"}]
                if unresolved_gap
                else []
            ),
            "next_step": (
                {"text": next_action, "status": "legacy_unverified"}
                if next_action
                else {}
            ),
            "optional_next_steps": [],
            # Deliberately not exposed as formal Claims/mastery.
            "legacy_confirmed_points": legacy_points,
            # Learning State-1 §2.1: legacy points carry no traceable authority.
            "legacy_confirmed_points_authority": [
                item.to_dict()
                for item in classify_legacy_confirmed_points(legacy_points)
            ],
        }



def _freshness_detail(payload: Any, *, drift: bool) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    keys = (
        "role",
        "path",
        "symbol",
        "reason",
        "head_file_sha",
        "materially_changed",
        "error",
    )
    return {key: payload.get(key) for key in keys if key in payload}


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


def _select_next_steps(
    steps: list[NextStep],
) -> tuple[NextStep | None, tuple[NextStep, ...]]:
    primary = next((item for item in steps if item.is_primary), None)
    if primary is None and steps:
        primary = steps[0]
    optional = tuple(
        item for item in steps if primary is None or item.id != primary.id
    )[:_MAX_OPTIONAL_NEXT_STEPS]
    return primary, optional


def _goal_projection(goal: LearningGoal) -> dict[str, Any]:
    return {
        "goal_id": goal.id,
        "topic_id": goal.topic_id,
        "objective": goal.objective,
        "status": goal.status,
    }


def _next_step_projection(step: NextStep | None) -> dict[str, Any]:
    if step is None:
        return {}
    return {
        "next_step_id": step.id,
        "text": step.text,
        "status": step.status,
        "is_primary": step.is_primary,
    }


def _evidence_projection(binding: Any | None) -> dict[str, Any]:
    if binding is None:
        return {}
    source = binding.source
    return {
        "evidence_id": source.id,
        "role": binding.role,
        "repository": source.repository,
        "commit_sha": source.commit_sha,
        "tree_sha": source.tree_sha,
        "path": source.path,
        "file_sha": source.file_sha,
        "symbol": source.symbol,
        "symbol_kind": source.symbol_kind,
        "start_line": source.start_line,
        "end_line": source.end_line,
        "evidence_kind": source.evidence_kind,
    }
