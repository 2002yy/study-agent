"""Durable learning-closure domain state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import hashlib
import json

from src.domain.runtime_entities import new_id, utc_now


def canonical_closure_source_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LearningClosureRun:
    """Server-owned state for one immutable session closure source."""

    id: str = field(default_factory=lambda: new_id("closure"))
    thread_id: str = ""
    source_thread_version: int = 0
    last_completed_turn_id: str = ""
    source_hash: str = ""
    closure_eligibility: str = ""
    status: str = "created"
    committed_snapshot: dict[str, Any] = field(default_factory=dict)
    generated_result: dict[str, Any] = field(default_factory=dict)
    memory_run_id: str | None = None
    error: str = ""
    reason: str = ""
    active_operation_id: str | None = None
    active_operation_started_at: str | None = None
    cancel_requested_at: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    completed_at: str | None = None
    version: int = 1
