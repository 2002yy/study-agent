"""Pydantic models for memory-related endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryStatusResponse(BaseModel):
    writable: bool
    memory_mode: str
    safe_mode: bool
    reason: str
    context_mode: str
    groups: dict[str, list[str]]
    files: list[dict]
    latest_section: str = ""
    latest_updated_at: str = ""


class MemoryUpdate(BaseModel):
    target: str
    content: str = Field(min_length=1)
    append: bool = True
    learner_pending: bool = False


class MemoryPreviewRequest(BaseModel):
    updates: list[MemoryUpdate] = Field(min_length=1)


class MemoryPreviewItem(BaseModel):
    target: str
    path: str
    action: str
    allowed: bool
    preview: str


class MemoryPreviewResponse(BaseModel):
    writable: bool
    memory_mode: str
    safe_mode: bool
    updates: list[MemoryPreviewItem]


class MemoryCommitResponse(BaseModel):
    writable: bool
    results: list[dict[str, str]]
    errors: list[dict[str, str]] | None = None
