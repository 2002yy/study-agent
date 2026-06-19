"""Pydantic models for RAG-related endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RagIndexRequest(BaseModel):
    paths: list[str] = Field(min_length=1)
    index_path: str | None = None
    max_chars: int = Field(default=900, gt=0, le=10_000)
    overlap_chars: int = Field(default=120, ge=0, le=5_000)


class RagIndexResponse(BaseModel):
    documents: int
    chunks: int
    index_path: str
    stages: list[dict] = Field(default_factory=list)


class RagStatusResponse(BaseModel):
    index_path: str
    index_exists: bool
    documents: int = 0
    chunks: int = 0
    vector_backend: dict


class RagQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    index_path: str | None = None
    top_k: int = Field(default=5, gt=0, le=20)
    min_score: float = Field(default=0.01, ge=0)
    retrieval_mode: str = Field(default="hybrid")
    context_max_chars: int = Field(default=3000, gt=0, le=20_000)
    expected_sources: list[str] = Field(default_factory=list)
    expected_terms: list[str] = Field(default_factory=list)


class RagQueryResponse(BaseModel):
    query: str
    retrieval_mode: str
    result_count: int
    context: str
    sources: str
    results: list[dict]
    debug: dict
    evaluation: dict | None = None


class LocalKnowledgeRequest(BaseModel):
    query: str = Field(min_length=1)
    enabled: bool = True
    force: bool = False
    index_path: str | None = None
    top_k: int = Field(default=3, gt=0, le=20)
    min_score: float = Field(default=0.01, ge=0)
    retrieval_mode: str = Field(default="hybrid")
    context_max_chars: int = Field(default=3000, gt=0, le=20_000)
    allow_rewrite: bool = True
    weak_score_threshold: float = Field(default=0.05, ge=0)


class LocalKnowledgeResponse(BaseModel):
    status: str
    query: str
    retrieval_mode: str
    reason: str
    context: str
    sources: str
    result_count: int
    results: list[dict]
    debug: dict
    attempts: list[dict]
    rewritten_query: str
