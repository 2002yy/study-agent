"""API models for persistent GitHub repository, history, work-item, and change research."""

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


class GitHubRefQueryRequest(BaseModel):
    repo_url: str = Field(min_length=1)
    ref: str = ""


class GitHubCommitQueryRequest(BaseModel):
    repo_url: str = Field(min_length=1)
    ref: str = ""


class GitHubCompareQueryRequest(BaseModel):
    repo_url: str = Field(min_length=1)
    base: str = Field(min_length=1)
    head: str = Field(min_length=1)
    max_files: int = Field(default=100, ge=1, le=300)
    max_patch_chars: int = Field(default=120000, ge=1000, le=1000000)


class GitHubBlameQueryRequest(BaseModel):
    repo_url: str = Field(min_length=1)
    path: str = Field(min_length=1)
    ref: str = ""
    start_line: int = Field(default=1, ge=1)
    end_line: int = Field(default=0, ge=0)


class GitHubPullRequestQueryRequest(BaseModel):
    repo_url: str = Field(min_length=1)
    number: int = Field(gt=0)
    max_files: int = Field(default=50, ge=1, le=100)
    max_patch_chars: int = Field(default=120000, ge=1000, le=1000000)
    max_comments: int = Field(default=100, ge=1, le=100)
    max_reviews: int = Field(default=100, ge=1, le=100)
    include_checks: bool = True


class GitHubIssueQueryRequest(BaseModel):
    repo_url: str = Field(min_length=1)
    number: int = Field(gt=0)
    max_comments: int = Field(default=100, ge=1, le=100)
    max_events: int = Field(default=100, ge=1, le=100)


class GitHubChecksQueryRequest(BaseModel):
    repo_url: str = Field(min_length=1)
    ref: str = ""
    max_runs: int = Field(default=20, ge=1, le=100)
    max_checks: int = Field(default=100, ge=1, le=100)
    max_jobs: int = Field(default=100, ge=1, le=300)
    include_jobs: bool = True


class GitHubCILogsQueryRequest(BaseModel):
    repo_url: str = Field(min_length=1)
    job_id: int = Field(gt=0)
    max_chars: int = Field(default=40000, ge=1000, le=200000)
    max_lines: int = Field(default=400, ge=20, le=2000)


class GitHubChangeImpactQueryRequest(BaseModel):
    repo_url: str = Field(min_length=1)
    base: str = Field(min_length=1)
    head: str = Field(min_length=1)
    max_files: int = Field(default=20, ge=1, le=50)
    max_symbols: int = Field(default=100, ge=1, le=300)
    depth: int = Field(default=2, ge=1, le=4)
    max_impact_files: int = Field(default=40, ge=1, le=100)
    max_edges: int = Field(default=160, ge=1, le=500)


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
