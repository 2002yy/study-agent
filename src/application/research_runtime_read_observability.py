"""Read attempt timing and backend health snapshots for active research.

These records are observations of completed work. They do not select a
reader, decide whether a read may start, or mutate the durable read cursor.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.application.active_research_evidence_projection import _bounded_retrieval_policy
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.health_breaker import NATIVE_HTTP_BACKEND
from src.web.research.read_retry import error_signature
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


def _record_backend_health(context: dict[str, Any], breaker: Any) -> None:
    """Flush the per-run breaker snapshot into the run metrics (no new ledger)."""

    if breaker is None:
        return
    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if not isinstance(metrics, dict):
        return
    metrics["backend_health"] = breaker.snapshot()


def _record_read_timing(
    context: dict[str, Any],
    *,
    candidate: CandidatePoolItem,
    wave_index: int,
    status: str,
    wall_ms: float,
    chars: int,
    raw_read: Mapping[str, Any],
    backend: str = NATIVE_HTTP_BACKEND,
) -> None:
    """F2-O3a: split read wall time into network wait, backoff and local work.

    Observation only: this never feeds scheduling, admission or policy. The
    fetch component includes retry fetches; the rest is local work, while
    escalation has a separate component.
    """

    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if not isinstance(metrics, dict):
        return
    retry = raw_read.get("read_retry")
    retry = retry if isinstance(retry, Mapping) else {}
    escalation = raw_read.get("escalation")
    escalation = escalation if isinstance(escalation, Mapping) else {}
    fetch_ms = float(retry.get("retry_fetch_ms") or 0.0) if retry else float(wall_ms)
    backoff_ms = float(retry.get("retry_backoff_ms") or 0.0)
    entry = {
        "candidate_id": candidate.id,
        "backend": str(backend),
        "host": str(candidate.url).split("//")[-1].split("/")[0][:120],
        "wave_index": int(wave_index),
        "status": str(status),
        "wall_ms": round(float(wall_ms), 1),
        "fetch_ms": round(fetch_ms, 1),
        "backoff_ms": round(backoff_ms, 1),
        "escalation_ms": round(float(escalation.get("latency_ms") or 0.0), 1),
        "local_ms": round(max(0.0, float(wall_ms) - fetch_ms - backoff_ms), 1),
        "attempts": int(retry.get("attempts") or 1),
        "retries": int(retry.get("retries") or 0),
        "chars": int(chars),
        "error_signature": error_signature(raw_read),
        "retrieval_state": str(raw_read.get("retrieval_state") or ""),
        "retrieval_policy": _bounded_retrieval_policy(raw_read),
        "attempts_detail": [
            dict(item)
            for item in (retry.get("attempts_detail") or [])
            if isinstance(item, Mapping)
        ][:4],
    }
    timing = metrics.get("read_timing")
    if not isinstance(timing, list):
        timing = []
    timing.append(entry)
    metrics["read_timing"] = timing[-80:]
