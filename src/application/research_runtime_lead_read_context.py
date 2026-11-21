"""One bounded lead read, including its durable external-attempt lifecycle.

Lead pages are discovery inputs, never evidence reads. The executor owns
admission, checkpoint calls and subsequent model discovery; this context owns
the related attempt and result transitions, but never calls a checkpoint.
Keeping those calls in the executor preserves both their durable ordering and
the existing checkpoint-caller diagnostic label.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from src.application.active_research_evidence_projection import _bounded_text
from src.application.research_runtime_discovery_diagnostics import (
    ActiveDiscoveryDiagnosticsContext,
)
from src.application.research_runtime_failure_projection import (
    with_appended_runtime_failure,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_read_budget_context import ReadWaveBudgetContext
from src.application.research_runtime_read_quota_context import ReadWaveQuotaContext
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.runtime import (
    RuntimeExternalAttemptStart,
    _attempt_number,
    begin_external_attempt,
    finish_external_attempt,
)


@dataclass(frozen=True, slots=True)
class ActiveLeadReadAttemptContext:
    """Bind stable run dependencies, but take the current wave quota per read."""

    live: ActiveRuntimeLiveValues
    run_id: str
    utc_now: Callable[[], str]
    gateway_read: Callable[..., Mapping[str, Any]]
    diagnostics: ActiveDiscoveryDiagnosticsContext

    def start(self, candidate: CandidatePoolItem) -> RuntimeExternalAttemptStart:
        """Begin a physical attempt; the caller must checkpoint before fetch."""
        candidate_id = candidate.id
        # Interrupted failures store the full physical call ID, not the
        # ``lead:{id}`` item_id of the inflight marker. Match the stable call
        # prefix so both pre-refactor failures and future v1/v2 recoveries
        # consume the same two-attempt ceiling, without counting evidence
        # reads of this candidate as lead attempts.
        call_prefix = f"research_lead_read:{self.run_id}:{candidate_id}:attempt:"
        attempt = _attempt_number(self.live.current_cursor(), call_prefix)
        marker = RuntimeExternalAttemptStart(
            call_id=f"{call_prefix}{attempt}",
            purpose="read",
            item_id=f"lead:{candidate_id}",
            attempt=attempt,
            started_at=self.utc_now(),
        )
        self.live.set_cursor(begin_external_attempt(self.live.current_cursor(), marker))
        self.diagnostics.bump_lead("lead_read_started")
        return marker

    def fetch(
        self, candidate: CandidatePoolItem, *, source_limit: int
    ) -> tuple[Mapping[str, Any], str]:
        """Bound the gateway read; its paired finish belongs in caller finally."""
        read_exception = ""
        try:
            raw_read = self.gateway_read(candidate.url, max_chars=source_limit)
        except Exception as exc:
            read_exception = type(exc).__name__
            raw_read = {
                "ok": False,
                "status": "failed",
                "url": candidate.url,
                "error": read_exception,
            }
        return raw_read, read_exception

    def finish(self, marker: RuntimeExternalAttemptStart) -> None:
        """Finish even on a gateway exception; the caller checkpoints next."""
        self.live.set_cursor(
            finish_external_attempt(self.live.current_cursor(), call_id=marker.call_id)
        )

    def complete(
        self,
        *,
        candidate: CandidatePoolItem,
        marker: RuntimeExternalAttemptStart,
        raw_read: Mapping[str, Any],
        read_exception: str,
        source_limit: int,
        quota: ReadWaveQuotaContext,
        budget: ReadWaveBudgetContext,
    ) -> str | None:
        """Publish the lead ID and failure/charge; caller checkpoints next.

        This is called only after finish is durable and cancellation is
        rechecked. Failure still consumes a lead ID, but no successful-read
        slot. Both paths resolve current live values after checkpoint rebinding.
        """
        candidate_id = candidate.id
        content = str(raw_read.get("content") or raw_read.get("readme") or "")[
            :source_limit
        ]
        self.live.set_cursor(
            replace(
                self.live.current_cursor(),
                lead_read_ids=(*self.live.current_cursor().lead_read_ids, candidate_id),
            )
        )
        if not (raw_read.get("ok") is True and content.strip()):
            self.live.set_cursor(
                with_appended_runtime_failure(
                    self.live.current_cursor(),
                    self.live.current_context(),
                    "read_failed",
                    "reading",
                    logical_call_id=marker.call_id,
                    item_id=candidate_id,
                    detail=_bounded_text(raw_read.get("error") or "lead_read_failed", 2000),
                    exception_type=read_exception,
                    attempt_id=marker.call_id,
                )
            )
            self.diagnostics.bump_lead("lead_read_failed")
            return None

        quota.charge_read(content)
        self.live.state = budget.project()
        return content
