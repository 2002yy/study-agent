"""Public contracts for derived review state; no raw learner responses."""

from typing import Literal

from pydantic import BaseModel


class LearningReviewItemResponse(BaseModel):
    claim_id: str
    claim_revision_id: str
    claim_text: str
    last_validated_at: str
    next_review_at: str
    due: bool
    reason: Literal["elapsed_since_last_validation", "within_review_interval"]


class LearningReviewPageResponse(BaseModel):
    thread_id: str
    goal_id: str
    items: list[LearningReviewItemResponse]
    total: int
    due_count: int
    limit: int
    offset: int
    source: Literal["derived_read_only"]
