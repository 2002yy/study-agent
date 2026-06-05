from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.workflows.schema import WorkflowEvent, WorkflowRun, WorkflowStatus

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKFLOW_DIR = ROOT / "logs" / "workflows"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def elapsed_ms_since(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


class WorkflowStore:
    def __init__(self, directory: str | Path = DEFAULT_WORKFLOW_DIR) -> None:
        self.directory = Path(directory)

    def append_event(self, event: WorkflowEvent) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._event_path(event.run_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def record_event(
        self,
        *,
        run_id: str,
        step_id: str,
        event_type: str,
        status: WorkflowStatus,
        workflow_name: str,
        message: str = "",
        data: dict[str, Any] | None = None,
        elapsed_ms: int = 0,
        error: str = "",
    ) -> WorkflowEvent:
        event = WorkflowEvent(
            run_id=run_id,
            step_id=step_id,
            event_type=event_type,
            status=status,
            workflow_name=workflow_name,
            message=message,
            data=data or {},
            elapsed_ms=elapsed_ms,
            created_at=utc_now_iso(),
            error=error,
        )
        self.append_event(event)
        return event

    def load_run(self, run_id: str) -> WorkflowRun | None:
        path = self._event_path(run_id)
        if not path.exists():
            return None
        events = tuple(self._read_events(path))
        if not events:
            return None
        first = events[0]
        last = events[-1]
        completed_at = last.created_at if last.status in {"succeeded", "failed", "skipped"} else ""
        return WorkflowRun(
            run_id=run_id,
            workflow_name=first.workflow_name,
            status=last.status,
            started_at=first.created_at,
            completed_at=completed_at,
            elapsed_ms=last.elapsed_ms,
            events=events,
        )

    def list_runs(self, limit: int = 20) -> list[WorkflowRun]:
        if not self.directory.is_dir():
            return []
        runs: list[WorkflowRun] = []
        for path in sorted(self.directory.glob("*.jsonl"), key=lambda item: item.stat().st_mtime_ns, reverse=True):
            run = self.load_run(path.stem)
            if run is not None:
                runs.append(run)
            if len(runs) >= limit:
                break
        return runs

    def _event_path(self, run_id: str) -> Path:
        safe_run_id = Path(run_id).name
        return self.directory / f"{safe_run_id}.jsonl"

    def _read_events(self, path: Path) -> list[WorkflowEvent]:
        events: list[WorkflowEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            events.append(
                WorkflowEvent(
                    run_id=str(payload["run_id"]),
                    step_id=str(payload["step_id"]),
                    event_type=str(payload["event_type"]),
                    status=payload["status"],
                    workflow_name=str(payload["workflow_name"]),
                    message=str(payload.get("message", "")),
                    data=dict(payload.get("data", {})),
                    elapsed_ms=int(payload.get("elapsed_ms", 0)),
                    created_at=str(payload.get("created_at", "")),
                    error=str(payload.get("error", "")),
                )
            )
        return events
