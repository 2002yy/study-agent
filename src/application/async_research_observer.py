"""Async Deep-1B-6: the SSE observer observes, it does not own execution.

Frozen boundary (Async-1B-6):

* a browser disconnect or refresh must not end a background run;
* a reconnect re-subscribes to the existing run and must never start a second worker;
* an explicit user cancel is a *persisted* fact, and it stops the worker at a safe
  boundary — an already-sent external request is not treated as revoked;
* a background run must complete and persist its result with no observer attached.

This module holds the observer-side decisions so the streaming route stays thin and
so the boundary is testable without a browser.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.repositories.async_research_discovery import _parse_timestamp


def should_cancel_on_disconnect(*, run_is_async: bool) -> bool:
    """Whether an SSE client leaving may cancel the run it was watching.

    Immediate runs keep their historical disconnect-cancel semantics: closing the
    page stops the work it started.  An authorized async run is owned by its
    persistence and its worker, so the observer leaving only ends the observation.
    """

    return not run_is_async


class AsyncResearchObserver:
    """Read-only view of a run; never leases, claims or executes.

    Reconnect is safe by construction: every method here is a read, so subscribing
    to a run that a worker already holds cannot create a second executor.
    """

    def __init__(self, *, runs: Any) -> None:
        self.runs = runs

    def snapshot(self, run_id: str) -> dict[str, Any]:
        """Current persisted state of one run, for streaming as an event."""

        run = self.runs.get(run_id)
        if run is None:
            return {"run_id": run_id, "present": False}
        return {
            "run_id": run_id,
            "present": True,
            "status": str(getattr(run, "status", "")),
            "stage": str(getattr(run, "stage", "")),
            "version": int(getattr(run, "version", 0) or 0),
            "lease_holder": getattr(run, "lease_holder", None),
            "stop_reason": str(getattr(run, "stop_reason", "") or ""),
        }

    def is_observed_by_worker(self, run_id: str) -> bool:
        """True while another party holds a live execution lease on this run."""

        run = self.runs.get(run_id)
        if run is None:
            return False
        if not getattr(run, "lease_holder", None):
            return False
        expires = _parse_timestamp(getattr(run, "lease_expires_at", None))
        if expires is None:
            return True
        return expires > datetime.now(timezone.utc)
