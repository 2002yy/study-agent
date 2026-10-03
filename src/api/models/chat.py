"""Pydantic models for chat-related endpoints.

Extracted from src/api.py — Batch 3 refactor.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from src.task_intent import TaskIntent
from src.turn_context import (
    pack_scene_turn_context,
    unpack_conversation_instruction,
)


class ChatMessage(BaseModel):
    role: str
    content: str
    avatarRole: str | None = None
    turnId: str | None = None
    turnStatus: str | None = None
    parentTurnId: str | None = None


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
    web_context_run_id: str | None = None
    web_policy: str | None = None
    web_consent: bool = False
    cloud_context_policy: str | None = None
    task_intent: TaskIntent | None = None
    continuation_of_turn_id: str | None = None
    retry_of_turn_id: str | None = None
    partial_reply: str = ""
    turn_id: str | None = None
    operation_id: str | None = None

    @model_validator(mode="after")
    def split_transient_turn_context(self) -> ChatRequest:
        instruction, turn_context = unpack_conversation_instruction(
            self.conversation_instruction
        )
        if not turn_context:
            return self
        # The durable instruction is restored before the request reaches the
        # application service.  The UI context rides only in `scene`, which is
        # a per-turn command field and is not written to ChatThread/ChatTurn.
        self.conversation_instruction = instruction
        self.scene = pack_scene_turn_context(self.scene, turn_context)
        return self


class CancelTurnRequest(BaseModel):
    expected_operation_id: str = Field(min_length=1)
    reason: str = "user_cancelled"


class CancelTurnResponse(BaseModel):
    turn_id: str
    outcome: str
    status: str | None = None
    cancel_requested_at: str | None = None


class TurnStatusResponse(BaseModel):
    turn_id: str
    status: str
    operation_id: str | None = None
    cancel_requested_at: str | None = None
    cancel_stage: str | None = None
    cancel_reason: str | None = None
    assistant_message: str = ""


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
    operation_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def discard_transient_turn_context(self) -> CommitTurnRequest:
        instruction, _ = unpack_conversation_instruction(self.conversation_instruction)
        self.conversation_instruction = instruction
        return self


class CommitTurnResponse(BaseModel):
    session_id: str
    committed: bool
    message: str


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    turn_id: str | None = None
    route: dict
    rag: dict
    pedagogy: dict = Field(default_factory=dict)
