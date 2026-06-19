"""Pydantic models for runtime settings endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RuntimeSettingsPatch(BaseModel):
    selected_role: str | None = None
    selected_mode: str | None = None
    selected_model: str | None = None
    relationship_mode: str | None = None
    entry_mode: str | None = None
    performance_mode: str | None = None
    memory_mode: str | None = None
    debug_mode: bool | None = None
    safe_mode: bool | None = None
    wechat_memory_capture_enabled: bool | None = None
    rag_enabled: bool | None = None
    rag_retrieval_mode: str | None = None
    rag_search_top_k: int | None = Field(default=None, ge=1, le=20)
    rag_chat_top_k: int | None = Field(default=None, ge=1, le=20)
    rag_top_k: int | None = Field(default=None, ge=1, le=20)
    rag_min_score: float | None = Field(default=None, ge=0)


class RuntimeSettingsResponse(BaseModel):
    settings: dict
    options: dict
    runtime_profile: dict
    warnings: list[str]
