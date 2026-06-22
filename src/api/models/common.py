"""Pydantic models for session, tool, workflow, and misc endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .chat import ChatMessage


class SessionListResponse(BaseModel):
    sessions: list[dict]


class SessionDetailResponse(BaseModel):
    session_id: str
    kind: str
    path: str
    messages: list[ChatMessage]
    settings: dict = Field(default_factory=dict)
    route: dict = Field(default_factory=dict)
    rag: dict = Field(default_factory=dict)
    conversation_instruction: str = ""
    turns: list[dict] = Field(default_factory=list)
    raw: str = ""


class SessionNewResponse(BaseModel):
    session_id: str
    settings: dict


class SessionArchiveResponse(BaseModel):
    session_id: str
    kind: str
    path: str
    archived: bool


class ToolInvocationRequest(BaseModel):
    args: dict = Field(default_factory=dict)
    run_id: str | None = None


class ToolInvocationResponse(BaseModel):
    tool_name: str
    status: str
    output: dict
    reason: str
    elapsed_ms: int
    run_id: str


class ToolRunCreateRequest(BaseModel):
    tool_name: str = Field(min_length=1)
    args: dict = Field(default_factory=dict)


class ToolRunResponse(BaseModel):
    id: str
    tool_name: str
    args: dict
    args_hash: str
    status: str
    preview: dict
    result: dict
    reason: str
    elapsed_ms: int
    active_operation_id: str | None
    active_operation_started_at: str | None
    previewed_at: str | None
    completed_at: str | None
    version: int
    created_at: str
    updated_at: str


class ToolRunListResponse(BaseModel):
    runs: list[ToolRunResponse]


class ToolListResponse(BaseModel):
    tools: list[dict]


class WorkflowListResponse(BaseModel):
    runs: list[dict]


class WorkflowRunResponse(BaseModel):
    run: dict


class HealthResponse(BaseModel):
    status: str
    service: str
    rag_index_exists: bool


class RoleListResponse(BaseModel):
    roles: list[dict]


class RoleResponse(BaseModel):
    id: str
    label: str
    prompt: str
    summary: str
    description: str
