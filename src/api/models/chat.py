"""Pydantic models for chat-related endpoints.

Extracted from src/api.py — Batch 3 refactor.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str
    avatarRole: str | None = None


class ChatRequest(BaseModel):
    user_input: str = Field(min_length=1)
    selected_role: str = "auto"
    selected_mode: str = "auto"
    selected_model: str = "auto"
    relationship_mode: str = "standard"
    scene: str = "single"
    conversation_instruction: str = ""
    performance_mode: str | None = None
    context_mode: str | None = None
    previous_mode: str | None = None
    chat_history: list[ChatMessage] = Field(default_factory=list)
    keep_current_role: bool = False
    session_id: str | None = None
    rag_enabled: bool = False
    rag_top_k: int = Field(default=3, gt=0, le=20)
    rag_search_top_k: int | None = Field(default=None, gt=0, le=20)
    rag_chat_top_k: int | None = Field(default=None, gt=0, le=20)
    rag_retrieval_mode: str = "hybrid"
    rag_min_score: float = Field(default=0.01, ge=0)
    web_context: str = ""
    continuation_of_turn_id: str | None = None
    partial_reply: str = ""
    turn_id: str | None = None


class CommitTurnRequest(BaseModel):
    session_id: str
    user_input: str
    agent_reply: str
    role: str = "auto"
    mode: str = "auto"
    model: str = "auto"
    memory_enabled: bool = False
    route_info: dict = Field(default_factory=dict)
    rag_info: dict = Field(default_factory=dict)
    conversation_instruction: str = ""
    turn_id: str | None = None


class CommitTurnResponse(BaseModel):
    session_id: str
    committed: bool
    message: str


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    route: dict
    rag: dict
