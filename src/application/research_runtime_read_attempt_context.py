"""Run-scoped read attempt recording without capturing the executor cursor.

The caller owns the current durable cursor and passes it on every transition.
The context binds stable run identity, clocks, cursor publication and the
breaker. Current research context, cursor and budget ceiling stay invocation
inputs because checkpoints and steering can replace them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from src.application.active_research_evidence_projection import _bounded_text
from src.application.research_runtime_failure_projection import (
    with_appended_runtime_failure,
)
from src.application.research_runtime_read_observability import (
    _record_backend_health,
    _record_escalation_diagnostics,
    _record_read_timing,
)
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.chain_executor import ChainStepResult
from src.web.research.health_breaker import NATIVE_HTTP_BACKEND, PerRunBreaker, host_of
from src.web.research.runtime import (
    ResearchRuntimeCursor,
    RuntimeExternalAttemptStart,
    RuntimeReadOutcome,
    begin_external_attempt,
    finish_external_attempt,
)
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY
from src.web.research.wigolo_http_executor import WIGOLO_HTTP_BACKEND


class LiveReadAttemptValues(Protocol):
    """Latest cursor/context with one owner across checkpoint and steering rebinds."""

    def current_cursor(self) -> ResearchRuntimeCursor: ...

    def current_context(self) -> dict[str, Any]: ...

    def set_cursor(self, cursor: ResearchRuntimeCursor) -> None: ...


@dataclass(slots=True)
class ActiveReadAttemptContext:
    """Group real reader-attempt transitions and their derived observations.

    Cursor publication is explicit: every durable transition is sent back to
    the caller before any diagnostic observation. If observation fails, the
    caller's in-memory cursor still contains the attempted read.
    """

    breaker: PerRunBreaker | None
    run_id: str
    utc_now: Callable[[], str]
    live: LiveReadAttemptValues
    research_seconds_left: Callable[[], float]
    elapsed: Callable[[], float]
    escalation_recorder: Callable[..., None] = _record_escalation_diagnostics

    def append_outcome(
        self,
        cursor: ResearchRuntimeCursor,
        candidate: CandidatePoolItem,
        step: ChainStepResult,
    ) -> ResearchRuntimeCursor:
        ok = bool(step.usable_content)
        return replace(
            cursor,
            read_outcomes=(
                *cursor.read_outcomes,
                RuntimeReadOutcome(
                    candidate_id=candidate.id,
                    status="success" if ok else "failed",
                    content_chars=len(step.content) if ok else 0,
                    error_code="" if ok else "read_failed",
                    backend=step.backend,
                    retrieval_state=step.retrieval_state,
                ),
            ),
        )

    def observe_step(
        self,
        context: dict[str, Any],
        *,
        candidate: CandidatePoolItem,
        step: ChainStepResult,
        wave_index: int,
    ) -> None:
        ok = bool(step.usable_content)
        if self.breaker is not None:
            self.breaker.record(
                backend=step.backend,
                host=host_of(candidate.url),
                state=step.retrieval_state,
                attempted=True,
            )
            _record_backend_health(context, self.breaker)
        cost = step.cost if isinstance(step.cost, Mapping) else {}
        _record_read_timing(
            context,
            candidate=candidate,
            wave_index=wave_index,
            status="success" if ok else "failed",
            wall_ms=float(cost.get("latency_ms") or 0.0),
            chars=int(cost.get("chars") or len(step.content or "")),
            raw_read={
                "read_retry": {
                    "retry_fetch_ms": cost.get("fetch_ms"),
                    "retry_backoff_ms": cost.get("backoff_ms"),
                    "attempts": cost.get("attempts"),
                    "retries": cost.get("retries"),
                    "attempts_detail": cost.get("attempts_detail"),
                },
                "retrieval_state": step.retrieval_state,
                "retrieval_policy": dict(step.policy)
                if isinstance(step.policy, Mapping)
                else {},
                "error": "" if ok else step.adequacy_reason,
            },
            backend=str(step.backend),
        )

    def record_chain_attempts(
        self,
        *,
        candidate: CandidatePoolItem,
        chain_steps: Sequence[ChainStepResult],
        attempt_number: int,
        hard_timeout_seconds: float,
    ) -> ResearchRuntimeCursor:
        """Record each real backend attempt before observing its side effects.

        The run-bound live owner is the single cursor/context authority.
        Publishing each cursor transition before observing diagnostics keeps
        the original crash and observation-failure semantics.
        """
        if not chain_steps:
            raise ValueError("cannot record an empty reader chain")

        cursor = self.live.current_cursor()
        native_step = next(
            (item for item in chain_steps if item.backend == NATIVE_HTTP_BACKEND),
            None,
        )
        wigolo_step = next(
            (item for item in chain_steps if item.backend == WIGOLO_HTTP_BACKEND),
            None,
        )
        for step in chain_steps:
            marker = RuntimeExternalAttemptStart(
                call_id=(
                    f"research_read:{self.run_id}:{candidate.id}"
                    f":attempt:{attempt_number}:{step.backend}"
                ),
                purpose="read",
                item_id=candidate.id,
                attempt=attempt_number,
                started_at=self.utc_now(),
            )
            cursor = begin_external_attempt(cursor, marker)
            self.live.set_cursor(cursor)
            cursor = finish_external_attempt(cursor, call_id=marker.call_id)
            self.live.set_cursor(cursor)
            cursor = self.append_outcome(cursor, candidate, step)
            self.live.set_cursor(cursor)
            self.observe_step(
                self.live.current_context(),
                candidate=candidate,
                step=step,
                wave_index=cursor.wave_index,
            )
            if not step.usable_content:
                step_cost = step.cost if isinstance(step.cost, Mapping) else {}
                step_error = str(
                    step_cost.get("error") or step_cost.get("error_type") or ""
                )
                cursor = with_appended_runtime_failure(
                    cursor,
                    self.live.current_context(),
                    "read_failed",
                    "reading",
                    logical_call_id=marker.call_id,
                    item_id=candidate.id,
                    detail=_bounded_text(
                        step_error or step.adequacy_reason or "read_failed",
                        2000,
                    ),
                    provider_code=_bounded_text(
                        str(step.policy.get("skip_reason") or "")
                        if isinstance(step.policy, Mapping)
                        else "",
                        200,
                    ),
                    exception_type=step_error,
                    attempt_id=marker.call_id,
                )
                self.live.set_cursor(cursor)

        self.record_escalation_signal(
            self.live.current_context(),
            candidate=candidate,
            native_step=native_step,
            wigolo_step=wigolo_step,
            wave_index=cursor.wave_index,
            research_seconds_left=self.research_seconds_left,
            hard_timeout_seconds=hard_timeout_seconds,
            elapsed=self.elapsed,
        )
        return cursor

    def record_escalation_signal(
        self,
        context: dict[str, Any],
        *,
        candidate: CandidatePoolItem,
        native_step: ChainStepResult | None,
        wigolo_step: ChainStepResult | None,
        wave_index: int,
        research_seconds_left: Callable[[], float],
        hard_timeout_seconds: float,
        elapsed: Callable[[], float],
    ) -> None:
        """Publish the original wave-scoped escalation signal if applicable.

        The clock callbacks run only for a real Wigolo attempt, preserving
        the previous monotonic-clock sampling and research budget semantics.
        """

        if wigolo_step is not None and wigolo_step.attempted:
            cost = wigolo_step.cost if isinstance(wigolo_step.cost, Mapping) else {}
            signal: dict[str, Any] = {
                "attempted": True,
                "tier": "http",
                "state": str(wigolo_step.retrieval_state),
                "reason": str(wigolo_step.adequacy_reason),
                "rescued": bool(wigolo_step.usable_content),
                "shape_before": str(
                    native_step.adequacy_reason if native_step is not None else ""
                ),
                "shape_after": str(wigolo_step.adequacy_reason),
                "chars_before": int(
                    native_step.cost.get("chars") or 0
                    if native_step is not None
                    and isinstance(native_step.cost, Mapping)
                    else 0
                ),
                "chars_after": len(wigolo_step.content or ""),
                "latency_ms": float(cost.get("latency_ms") or 0.0),
                "cache_hit": cost.get("cache_hit"),
                "max_chars_requested": int(cost.get("max_chars_requested") or 0),
                "preflight": str(cost.get("preflight") or ""),
                "url": candidate.url,
                "attempt_seq": int(
                    context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {}).get(
                        "retrieval_attempt_seq"
                    )
                    or 0
                ),
                "research_seconds_left_at_start": research_seconds_left(),
                "hard_seconds_left_at_start": hard_timeout_seconds - elapsed(),
                "envelope_remaining_at_start_ms": cost.get(
                    "envelope_remaining_at_start_ms"
                ),
                "effective_timeout_seconds": cost.get("effective_timeout_seconds"),
            }
        elif native_step is not None and native_step.usable_content:
            signal = {
                "attempted": False,
                "tier": "http",
                "state": "ok",
                "reason": "already_adequate",
                "rescued": False,
                "shape_before": str(native_step.adequacy_reason),
                "shape_after": str(native_step.adequacy_reason),
            }
        else:
            return
        self.escalation_recorder(context, signal, wave_index=int(wave_index))
