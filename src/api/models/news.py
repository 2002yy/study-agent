"""Pydantic models for news-related endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NewsRunCreateRequest(BaseModel):
    query: str = Field(default="最新新闻 when:1d", min_length=1)


class NewsRunSearchRequest(BaseModel):
    max_items: int = Field(default=10, gt=0, le=20)


class NewsRunEnrichRequest(BaseModel):
    max_articles: int = Field(default=6, ge=0, le=20)
    max_chars_per_article: int = Field(default=5000, gt=0, le=20000)
    safe_mode: bool | None = None


class NewsRunDigestRequest(BaseModel):
    selected_model: str = "auto"
    performance_mode: str | None = None


class NewsRunDiscussRequest(BaseModel):
    group_thread_id: str | None = None
    selected_model: str = "auto"
    relationship_mode: str = "standard"
    performance_mode: str | None = None


class NewsRunResponse(BaseModel):
    id: str
    query: str
    stage: str
    status: str
    safe_mode: bool
    items: list[dict]
    digest: str
    source_block: str
    article_coverage: dict
    discussion: str
    warnings: list[str]
    error: str
    group_thread_id: str | None
    active_operation_id: str | None
    active_operation_started_at: str | None
    stage_started_at: str | None
    completed_at: str | None
    version: int
    created_at: str
    updated_at: str


class NewsRunListResponse(BaseModel):
    runs: list[NewsRunResponse]


class NewsLookupRequest(BaseModel):
    query: str = Field(default="最新新闻 when:1d", min_length=1)
    max_items: int = Field(default=8, gt=0, le=20)


class ResearchRunCreateRequest(BaseModel):
    query: str = Field(min_length=1)
    max_items: int = Field(default=8, gt=0, le=20)
    owner_thread_id: str | None = Field(default=None, max_length=200)
    parent_run_id: str | None = Field(default=None, max_length=200)
    create_request_id: str | None = Field(default=None, max_length=200)
    suggestion_status: str = Field(default="not_checked", max_length=40)


class ResearchFollowUpCandidateResponse(BaseModel):
    available: bool
    reason: str
    parent_run_id: str | None = None
    parent_query: str = ""
    parent_status: str = ""
    source_count: int = 0
    note_count: int = 0
    overlap_tokens: list[str] = Field(default_factory=list)
    requires_explicit_confirmation: bool = False
    steering_required: bool = False


class ResearchSteerRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    request_id: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")


class ResearchQueueRequest(ResearchSteerRequest):
    request_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")


class ResearchQueueCompleteRequest(BaseModel):
    turn_id: str = Field(min_length=1, max_length=200)


class NewsLookupResponse(BaseModel):
    run_id: str
    query_text: str
    news_items: list[dict]
    source_block: str
    warnings: list[str]
    status: str = "completed"
    stage: str = "completed"
    provider_status: str = ""
    stop_reason: str = ""
    query_attempts: list[dict] = Field(default_factory=list)
    error: str = ""


class WebLookupRunResponse(BaseModel):
    id: str
    query: str
    stage: str = "created"
    status: str
    research_context: dict = Field(default_factory=dict)
    query_attempts: list[dict] = Field(default_factory=list)
    selected_sources: list[dict] = Field(default_factory=list)
    rejected_sources: list[dict] = Field(default_factory=list)
    provider_status: str = ""
    stop_reason: str = ""
    answer_confidence: str = ""
    items: list[dict]
    source_block: str
    warnings: list[str]
    error: str
    max_items: int = 8
    active_operation_id: str | None = None
    active_operation_started_at: str | None = None
    stage_started_at: str | None = None
    cancel_requested_at: str | None = None
    owner_thread_id: str | None = None
    parent_run_id: str | None = None
    root_run_id: str | None = None
    lineage_depth: int = 0
    create_request_id: str | None = None
    lineage_summary: dict = Field(default_factory=dict)
    version: int
    created_at: str
    updated_at: str
    completed_at: str | None


class WebLookupRunListResponse(BaseModel):
    runs: list[WebLookupRunResponse]


