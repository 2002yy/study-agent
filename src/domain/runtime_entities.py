"""Runtime domain entities for the Architecture V2 persistence layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ChatThread:
    id: str = field(default_factory=lambda: new_id("chat"))
    status: str = "active"
    settings_snapshot: dict[str, Any] = field(default_factory=dict)
    learning_state: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    archived_at: str | None = None
    export_path: str = ""
    active_operation_id: str | None = None
    active_operation_started_at: str | None = None
    archive_operation_id: str | None = None
    archive_started_at: str | None = None
    version: int = 1


@dataclass(frozen=True)
class ChatTurn:
    id: str = field(default_factory=lambda: new_id("turn"))
    thread_id: str = ""
    user_message: str = ""
    assistant_message: str = ""
    status: str = "pending"
    role: str = ""
    mode: str = ""
    model: str = ""
    route_snapshot: dict[str, Any] = field(default_factory=dict)
    rag_snapshot: dict[str, Any] = field(default_factory=dict)
    pedagogy_snapshot: dict[str, Any] = field(default_factory=dict)
    parent_turn_id: str | None = None
    operation_id: str | None = None
    conversation_instruction: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class GroupThread:
    id: str = field(default_factory=lambda: new_id("group"))
    status: str = "active"
    title: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    archived_at: str | None = None
    settings_snapshot: dict[str, Any] = field(default_factory=dict)
    active_operation_id: str | None = None
    active_operation_started_at: str | None = None
    unread_count: int = 0
    last_read_message_id: str | None = None
    archive_operation_id: str | None = None
    archive_started_at: str | None = None
    export_path: str = ""
    version: int = 1


@dataclass(frozen=True)
class GroupMessage:
    id: str = field(default_factory=lambda: new_id("group_msg"))
    thread_id: str = ""
    speaker: str = ""
    content: str = ""
    status: str = "committed"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    message_type: str = "chat"
    operation_id: str | None = None
    error: str = ""


@dataclass(frozen=True)
class NewsRun:
    id: str = field(default_factory=lambda: new_id("news"))
    query: str = ""
    stage: str = "created"
    status: str = "running"
    safe_mode: bool = False
    items: list[dict[str, Any]] = field(default_factory=list)
    digest: str = ""
    source_block: str = ""
    article_coverage: dict[str, Any] = field(default_factory=dict)
    discussion: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    group_thread_id: str | None = None
    active_operation_id: str | None = None
    active_operation_started_at: str | None = None
    stage_started_at: str | None = None
    completed_at: str | None = None
    version: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class WebLookupRun:
    id: str = field(default_factory=lambda: new_id("web_lookup"))
    query: str = ""
    stage: str = "created"
    status: str = "running"
    research_context: dict[str, Any] = field(default_factory=dict)
    query_attempts: list[dict[str, Any]] = field(default_factory=list)
    selected_sources: list[dict[str, Any]] = field(default_factory=list)
    rejected_sources: list[dict[str, Any]] = field(default_factory=list)
    provider_status: str = ""
    stop_reason: str = ""
    answer_confidence: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    source_block: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    max_items: int = 8
    active_operation_id: str | None = None
    active_operation_started_at: str | None = None
    stage_started_at: str | None = None
    cancel_requested_at: str | None = None
    version: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    completed_at: str | None = None


@dataclass(frozen=True)
class MemoryRun:
    id: str = field(default_factory=lambda: new_id("memory"))
    status: str = "previewed"
    updates: list[dict[str, Any]] = field(default_factory=list)
    updates_hash: str = ""
    preview: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    active_operation_id: str | None = None
    active_operation_started_at: str | None = None
    previewed_at: str | None = None
    completed_at: str | None = None
    version: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class RagRun:
    id: str = field(default_factory=lambda: new_id("rag"))
    kind: str = "query"
    status: str = "running"
    request: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    index_version: int = 0
    version: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    completed_at: str | None = None


@dataclass(frozen=True)
class ToolRun:
    id: str = field(default_factory=lambda: new_id("tool"))
    tool_name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    args_hash: str = ""
    status: str = "previewed"
    preview: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    elapsed_ms: int = 0
    active_operation_id: str | None = None
    active_operation_started_at: str | None = None
    previewed_at: str | None = None
    completed_at: str | None = None
    version: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class OperationRecord:
    id: str = field(default_factory=lambda: new_id("op"))
    scope: str = ""
    owner_id: str | None = None
    status: str = "running"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
