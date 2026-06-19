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
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    archived_at: str | None = None
    export_path: str = ""
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
    archived_at: str | None = None
    version: int = 1


@dataclass(frozen=True)
class NewsRun:
    id: str = field(default_factory=lambda: new_id("news"))
    query: str = ""
    stage: str = "created"
    status: str = "running"
    safe_mode: bool = False
    items: list[dict[str, Any]] = field(default_factory=list)
    digest: str = ""
    warnings: list[str] = field(default_factory=list)
    group_thread_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class ToolRun:
    id: str = field(default_factory=lambda: new_id("tool"))
    tool_name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    args_hash: str = ""
    status: str = "previewed"
    preview: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
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
