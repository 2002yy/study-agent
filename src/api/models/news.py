"""Pydantic models for news-related endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NewsSearchRequest(BaseModel):
    query: str = Field(default="最新新闻 when:1d", min_length=1)
    read_articles: bool = True
    selected_model: str = "auto"
    relationship_mode: str = "standard"
    performance_mode: str | None = None
    session_id: str | None = None


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


class NewsStageSearchRequest(BaseModel):
    query: str = Field(default="最新新闻 when:1d", min_length=1)
    max_items: int = Field(default=10, gt=0, le=20)


class NewsStageSearchResponse(BaseModel):
    query_text: str
    news_items: list[dict]


class NewsEnrichRequest(BaseModel):
    query_text: str = Field(default="", min_length=0)
    news_items: list[dict] = Field(min_length=1)
    max_articles: int = Field(default=6, ge=0, le=20)
    max_chars_per_article: int = Field(default=5000, gt=0, le=20000)
    safe_mode: bool | None = None


class NewsEnrichResponse(BaseModel):
    query_text: str
    news_items: list[dict]
    skipped: bool = False
    skipped_reason: str = ""


class NewsDigestRequest(BaseModel):
    query_text: str = Field(default="", min_length=0)
    news_items: list[dict] = Field(min_length=1)
    selected_model: str = "auto"
    performance_mode: str | None = None


class NewsDigestResponse(BaseModel):
    query_text: str
    digest: str
    source_block: str
    article_coverage: dict
    warnings: list[str]


class NewsDiscussRequest(BaseModel):
    digest: str = Field(min_length=1)
    source_block: str = ""
    selected_model: str = "auto"
    relationship_mode: str = "standard"
    performance_mode: str | None = None
    session_id: str | None = None


class NewsDiscussResponse(BaseModel):
    discussion: str
    group_content: str
    session_id: str


class NewsLookupResponse(BaseModel):
    run_id: str
    query_text: str
    news_items: list[dict]
    source_block: str
    warnings: list[str]


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
    version: int
    created_at: str
    updated_at: str
    completed_at: str | None


class WebLookupRunListResponse(BaseModel):
    runs: list[WebLookupRunResponse]


class NewsSearchResponse(BaseModel):
    query_text: str
    news_items: list[dict]
    digest: str
    discussion: str
    group_content: str
    source_block: str
    article_coverage: dict
    elapsed_ms: int
    warnings: list[str]
    audit_markdown_path: str
    audit_json_path: str
    session_id: str
