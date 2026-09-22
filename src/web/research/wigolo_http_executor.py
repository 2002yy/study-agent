"""§103 P2-A2d-3 explicit ``wigolo_http`` backend executor.

The legacy Wigolo HTTP call lived *inside* a read: the reader ran, decided the
result was inadequate, and quietly escalated. That made the second backend
invisible to candidate lifecycle, to ``(backend, host)`` health, and to routing.

This module is the same execution, made explicit: it is a
:class:`~src.web.research.chain_executor.BackendExecutor` that the chain executor
can invoke as a chain step.

What it keeps
-------------

The three B2 guards are **not re-implemented here**. Both this executor and the
legacy escalation ask :func:`read_escalation.wigolo_http_execution_plan`, so the
allow/deny verdict, the refusal reason and the effective timeout come from one
budget truth rather than from two copies that happen to agree.

Execution-time preflight still owns the final say: a scheduler that earlier found
this backend eligible does not authorise the call, because the budget may have
been spent by the native attempt in between.

What it does not do
-------------------

It never records an outcome, never touches candidate lifecycle, never routes and
never writes evidence, support or the Gate. The chain executor keeps the
``execute -> record_outcome -> route`` order; this module only performs one
attempt and reports it as a
:class:`~src.web.research.chain_executor.ChainStepResult`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from src.web.research.chain_executor import ChainAttemptRequest, ChainStepResult
from src.web.research.failure_taxonomy import (
    SKIP_REASON_DISABLED,
    SKIP_REASON_INSUFFICIENT_WINDOW,
    SKIP_REASON_PREFLIGHT,
    UNKNOWN_STATE,
    classify,
    from_invocation_state,
    from_read_adequacy,
)
from src.web.research.read_adequacy import ADEQUATE_SHAPE, classify_reader_result
from src.web.research.read_escalation import (
    ESCALATION_OFF,
    escalation_mode,
    wigolo_http_execution_plan,
)
from src.web.research.retrieval_backends import RawReadArtifact, ReadRequest

WIGOLO_HTTP_BACKEND = "wigolo_http"

#: Policy skip reasons this executor can produce (A0's closed set).
SKIP_REASON_BUDGET = SKIP_REASON_INSUFFICIENT_WINDOW


def _skip_result(
    backend: str,
    *,
    state: str,
    skip_reason: str,
    detail: str,
    adequacy_reason: str = "",
    cost: Mapping[str, Any] | None = None,
) -> ChainStepResult:
    """A policy skip: the backend was never tried, so nothing may be claimed."""

    outcome = classify(
        backend=backend,
        raw_state=state,
        detail=detail,
        skip_reason=skip_reason,
        attempted=False,
    )
    return ChainStepResult(
        backend=backend,
        retrieval_state=outcome.state,
        attempted=False,
        usable_content=False,
        content="",
        adequacy_reason=adequacy_reason or detail,
        cost=dict(cost or {}),
        policy=outcome.to_policy_dict(),
    )


@dataclass
class WigoloHttpBackendExecutor:
    """One explicit ``wigolo_http`` attempt, with the B2 guards applied."""

    backend: Any = None
    max_chars: int = 0
    hard_seconds_left: Callable[[], float] | None = None
    charge_envelope: Callable[[float], None] | None = None
    mode: Callable[[], str] | None = None
    name: str = WIGOLO_HTTP_BACKEND
    calls: int = field(default=0, init=False)

    def _mode(self) -> str:
        if self.mode is not None:
            return str(self.mode())
        return escalation_mode()

    def execute(self, request: ChainAttemptRequest) -> ChainStepResult:
        backend_name = str(getattr(self.backend, "name", "") or self.name)

        # 1. Availability of the capability itself (configuration, not health).
        if self._mode() == ESCALATION_OFF:
            return _skip_result(
                backend_name,
                state=UNKNOWN_STATE,
                skip_reason=SKIP_REASON_DISABLED,
                detail="escalation_disabled",
            )
        if self.backend is None:
            return _skip_result(
                backend_name,
                state=UNKNOWN_STATE,
                skip_reason=SKIP_REASON_PREFLIGHT,
                detail="backend_unavailable",
            )

        # 2. The shared B2 budget truth, evaluated *now* (not at scheduling time).
        plan = wigolo_http_execution_plan(
            hard_seconds_left=(
                self.hard_seconds_left() if self.hard_seconds_left else None
            )
        )
        if not plan.allowed:
            return _skip_result(
                backend_name,
                state="budget_exhausted",
                skip_reason=SKIP_REASON_BUDGET,
                detail=plan.deny_reason,
                adequacy_reason=plan.deny_reason,
                cost={
                    "deny_layer": plan.deny_layer,
                    "hard_headroom": plan.hard_headroom,
                    "envelope_remaining_ms": round(plan.envelope_remaining_ms, 1),
                    "effective_timeout_seconds": round(
                        plan.effective_timeout_seconds, 3
                    ),
                },
            )

        # 3. Fail closed on an unavailable or misconfigured provider.
        preflight = getattr(self.backend, "preflight", None)
        preflight_status = ""
        if callable(preflight):
            preflight_status = str(preflight() or "")
            if preflight_status != "ready":
                return _skip_result(
                    backend_name,
                    state=UNKNOWN_STATE,
                    skip_reason=SKIP_REASON_PREFLIGHT,
                    detail=f"preflight:{preflight_status}",
                    cost={"preflight": preflight_status},
                )

        # 4. The one real attempt.
        self.calls += 1
        effective_timeout = round(plan.effective_timeout_seconds, 3)
        try:
            artifact = self.backend.fetch(
                ReadRequest(
                    url=request.url,
                    max_chars=self.max_chars or 0,
                    timeout_seconds=effective_timeout or None,
                )
            )
        except Exception as exc:  # noqa: BLE001 - a backend must never raise upward
            self._charge(0.0)
            outcome = classify(
                backend=backend_name,
                raw_state="transport_error",
                detail=f"{type(exc).__name__}",
            )
            return ChainStepResult(
                backend=backend_name,
                retrieval_state=outcome.state,
                attempted=True,
                usable_content=False,
                content="",
                cost={
                    "effective_timeout_seconds": effective_timeout,
                    "preflight": preflight_status,
                    "error_type": type(exc).__name__,
                },
                policy={"attempted": True, "skip_reason": "", "backend": backend_name},
            )

        if artifact is None:
            return ChainStepResult(
                backend=backend_name,
                retrieval_state=UNKNOWN_STATE,
                attempted=True,
                usable_content=False,
                content="",
                cost={"effective_timeout_seconds": effective_timeout},
                policy={"attempted": True, "skip_reason": "", "backend": backend_name},
            )

        # 5. The attempt is charged whether it succeeded or not.
        self._charge(float(artifact.latency_ms or 0.0))
        return self._project(request, artifact, effective_timeout, preflight_status)

    # ------------------------------------------------------------------ helpers

    def _charge(self, latency_ms: float) -> None:
        if self.charge_envelope is not None:
            self.charge_envelope(float(latency_ms))

    def _project(
        self,
        request: ChainAttemptRequest,
        artifact: RawReadArtifact,
        effective_timeout: float,
        preflight_status: str,
    ) -> ChainStepResult:
        """Canonical projection of one artifact (no authority, no lifecycle)."""

        metadata = artifact.external_metadata or {}
        payload = {
            "ok": artifact.usable,
            "content": artifact.content,
            "title": str(metadata.get("title") or ""),
            "url": artifact.url or request.url,
            "method": artifact.retrieval_mode,
            "backend": artifact.backend,
        }
        adequacy = classify_reader_result(payload)
        raw_state = str(metadata.get("state") or "")
        if artifact.usable:
            outcome = from_read_adequacy(adequacy.shape, backend=artifact.backend)
        else:
            outcome = from_invocation_state(
                raw_state or "empty",
                backend=artifact.backend,
                detail=raw_state or "empty_content",
            )
        usable = bool(artifact.usable and adequacy.shape == ADEQUATE_SHAPE)
        return ChainStepResult(
            backend=str(artifact.backend or self.name),
            retrieval_state=outcome.state,
            attempted=True,
            usable_content=usable,
            content=artifact.content if usable else "",
            adequacy_reason=adequacy.shape,
            cost={
                "latency_ms": round(float(artifact.latency_ms or 0.0), 1),
                "bytes": int(artifact.bytes or 0),
                "content_type": str(artifact.content_type or ""),
                "cache_hit": artifact.cache_hit,
                "rendered": artifact.rendered,
                "effective_timeout_seconds": effective_timeout,
                "preflight": preflight_status,
                "raw_state": raw_state,
            },
            policy={
                "attempted": True,
                "skip_reason": "",
                "breaker_state": "",
                "backend": str(artifact.backend or self.name),
            },
        )


__all__ = [
    "SKIP_REASON_BUDGET",
    "WIGOLO_HTTP_BACKEND",
    "WigoloHttpBackendExecutor",
]
