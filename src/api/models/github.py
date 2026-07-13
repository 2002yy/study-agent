"""API models for persistent GitHub repository snapshots."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GitHubSnapshotCreateRequest(BaseModel):
    repo_url: str = Field(min_length=1)
    query: str = ""
    ref: str = ""
    force_refresh: bool = False


class GitHubSnapshotResultResponse(BaseModel):
    result: dict


class GitHubSnapshotRunResponse(BaseModel):
    id: str
    status: str
    request: dict
    result: dict
    error: str
    version: int
    created_at: str
    updated_at: str
    completed_at: str | None


class GitHubSnapshotRunListResponse(BaseModel):
    runs: list[GitHubSnapshotRunResponse]
