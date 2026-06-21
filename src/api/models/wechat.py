"""Pydantic models for wechat-related endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class WechatStateResponse(BaseModel):
    group_thread_id: str
    state: dict
    content: str
    unread: str
    has_unread: bool
    started: bool
    message_count: int
    unread_count: int
    summary: str


class WechatOpeningRequest(BaseModel):
    group_thread_id: str | None = None
    selected_role: str = "auto"
    selected_model: str = "auto"
    relationship_mode: str = "standard"
    performance_mode: str | None = None


class WechatMessageRequest(BaseModel):
    message: str = Field(min_length=1)
    selected_model: str = "auto"
    relationship_mode: str = "standard"
    performance_mode: str | None = None
    session_id: str | None = None
    group_thread_id: str | None = None
    rag_enabled: bool = False
    rag_top_k: int = Field(default=3, gt=0, le=20)
    rag_search_top_k: int | None = Field(default=None, gt=0, le=20)
    rag_chat_top_k: int | None = Field(default=None, gt=0, le=20)
    rag_retrieval_mode: str = "hybrid"
    rag_min_score: float = Field(default=0.01, ge=0)

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class WechatMessageResponse(BaseModel):
    reply: str
    content: str
    state: dict
    session_id: str
    group_thread_id: str
    rag: dict
    message_count: int = 0
    unread_count: int = 0
    has_unread: bool = False


class WechatSearchRequest(BaseModel):
    keyword: str = Field(min_length=1)
    max_results: int = Field(default=10, gt=0, le=50)
    group_thread_id: str | None = None


class WechatSearchResponse(BaseModel):
    keyword: str
    results: list[dict]
