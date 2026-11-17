"""Run-scoped read attempt recording without capturing the executor cursor.

The caller owns the current durable cursor and passes it on every transition.
The context owns only the per-run breaker; current research context is supplied
at the call site because checkpoints and steering can replace that mapping.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from src.application.research_runtime_read_observability import (
    _record_backend_health,
    _record_escalation_diagnostics,
    _record_read_timing,
)
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.chain_executor import ChainStepResult
from src.web.research.health_breaker import PerRunBreaker, host_of
from src.web.research.runtime import ResearchRuntimeCursor, RuntimeReadOutcome
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


@dataclass(slots=True)
class ActiveReadAttemptContext:
    """Group real reader-attempt transitions and their derived observations.

    Deliberately split ``append_outcome`` from ``observe_step``: the executor
    must assign its new cursor *before* recording diagnostics. If observation
    fails, the in-memory cursor must still contain the attempted read.
    """

    breaker: PerRunBreaker | None
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
