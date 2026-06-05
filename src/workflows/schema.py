from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

WorkflowStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]


@dataclass(frozen=True)
class WorkflowEvent:
    run_id: str
    step_id: str
    event_type: str
    status: WorkflowStatus
    workflow_name: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0
    created_at: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkflowRun:
    run_id: str
    workflow_name: str
    status: WorkflowStatus
    started_at: str
    completed_at: str = ""
    elapsed_ms: int = 0
    events: tuple[WorkflowEvent, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed_ms": self.elapsed_ms,
            "events": [event.to_dict() for event in self.events],
        }
