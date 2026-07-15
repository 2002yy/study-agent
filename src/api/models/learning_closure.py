"""Pydantic models for durable learning closure."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.api.models.memory import MemoryRunResponse


class LearningClosureRunResponse(BaseModel):
    id: str
    thread_id: str
    source_thread_version: int
    last_completed_turn_id: str
    source_hash: str
    closure_eligibility: str
    status: str
    committed_snapshot: dict
    generated_result: dict
    memory_run_id: str | None
    memory_run: MemoryRunResponse | None = None
    thread_summary: dict = Field(default_factory=dict)
    error: str
    reason: str
    active_operation_id: str | None
    active_operation_started_at: str | None
    cancel_requested_at: str | None
    created_at: str
    updated_at: str
    completed_at: str | None
    version: int


class LearningClosureRunListResponse(BaseModel):
    runs: list[LearningClosureRunResponse]
