"""Public contracts for derived review state; no raw learner responses."""

from typing import Literal

from pydantic import BaseModel, Field


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


class ReviewPromptPreviewResponse(BaseModel):
    thread_id: str
    goal_id: str
    claim_revision_id: str
    last_validated_at: str
    question: str
    status: Literal["preview"]
    source: Literal["derived_read_only"]


class StartReviewPromptRequest(BaseModel):
    turn_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)


class StartReviewPromptResponse(BaseModel):
    thread_id: str
    prompt_turn_id: str
    question: str
    status: Literal["completed"]
