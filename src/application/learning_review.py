"""Thread-scoped, read-only access to the §169 review projection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

from src.application.review_projection import project_review
from src.domain.learning_truth import (
    ClaimRevisionBundle,
    LearningGoal,
    UnderstandingClaimResult,
    UnderstandingEvidence,
)


class ReviewTruthReader(Protocol):
    def get_focus_goal(self, thread_id: str) -> LearningGoal | None: ...

    def list_goal_revisions(self, goal_id: str) -> list[ClaimRevisionBundle]: ...

    def list_understanding_for_revision(
        self, revision_id: str
    ) -> list[tuple[UnderstandingEvidence, UnderstandingClaimResult]]: ...


@dataclass(frozen=True)
class LearningReviewItem:
    claim_id: str
    claim_revision_id: str
    claim_text: str
    last_validated_at: str
    next_review_at: str
    due: bool
    reason: str


@dataclass(frozen=True)
class LearningReviewPage:
    thread_id: str
    goal_id: str
    items: tuple[LearningReviewItem, ...]
    total: int
    due_count: int
    limit: int
    offset: int
    source: str = "derived_read_only"

    def to_dict(self) -> dict:
        return asdict(self)


class LearningReviewService:
    def __init__(self, truth: ReviewTruthReader) -> None:
        self.truth = truth

    def build(
        self,
        thread_id: str,
        *,
        now: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
        due_only: bool = False,
    ) -> LearningReviewPage:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid review page bounds")
        goal = self.truth.get_focus_goal(thread_id)
        items: list[LearningReviewItem] = []
        if goal is not None:
            # Repository order is chronological. Only the latest revision linked
            # to this goal is reviewable; earlier passes cannot validate new text.
            latest = {
                bundle.revision.claim_id: bundle.revision
                for bundle in self.truth.list_goal_revisions(goal.id)
            }
            for revision in latest.values():
                projections = project_review(
                    self.truth.list_understanding_for_revision(revision.id), now=now
                )
                for projection in projections:
                    if projection.claim_revision_id != revision.id:
                        continue
                    items.append(
                        LearningReviewItem(
                            claim_id=revision.claim_id,
                            claim_text=revision.claim_text,
                            **asdict(projection),
                        )
                    )
        due_count = sum(item.due for item in items)
        items.sort(
            key=lambda item: (
                not item.due,
                datetime.fromisoformat(item.next_review_at),
                item.claim_revision_id,
            )
        )
        selected = [item for item in items if not due_only or item.due]
        return LearningReviewPage(
            thread_id=thread_id,
            goal_id=goal.id if goal else "",
            items=tuple(selected[offset : offset + limit]),
            total=len(selected),
            due_count=due_count,
            limit=limit,
            offset=offset,
        )
