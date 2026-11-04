"""Models for host-owned interactive-UI state snapshots."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class InteractiveStateSaveRequest(BaseModel):
    component_id: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"
    )
    revision: int = Field(ge=1, le=999)
    # A snapshot is data the document published; it is never a document source
    # and never executable. Only a JSON object is accepted.
    state: dict[str, Any]


class InteractiveStateResponse(BaseModel):
    component_id: str
    revision: int
    state: dict[str, Any]
    updated_at: str
