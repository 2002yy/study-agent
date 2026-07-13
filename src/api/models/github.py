"""API models for persistent GitHub repository snapshots."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GitHubSnapshotCreateRequest(BaseModel):
    repo_url: str = Field(min_length=1)
    query: str = ""
    ref: str = ""
    force_refresh: bool = False


class GitHubStructureQueryRequest(BaseModel):
    repo_url: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    ref: str = ""
    top_k: int = Field(default=20, gt=0, le=50)


class GitHubImpactQueryRequest(BaseModel):
    repo_url: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    ref: str = ""
    depth: int = Field(default=2, ge=1, le=4)
    max_files: int = Field(default=30, ge=1, le=100)
    max_edges: int = Field(default=120, ge=1, le=500)


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
