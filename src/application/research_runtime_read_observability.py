"""Read attempt timing and backend health snapshots for active research.

These records are observations of completed work. They do not select a
reader, decide whether a read may start, or mutate the durable read cursor.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

from src.application.active_research_evidence_projection import _bounded_retrieval_policy
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.candidate_resolution import resolution_summary
from src.web.research.chain_executor import ChainRun, ChainStepResult
from src.web.research.health_breaker import NATIVE_HTTP_BACKEND
from src.web.research.read_retry import error_signature
from src.web.research.runtime import RuntimeReadOutcome
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


def _record_read_history(
    context: dict[str, Any],
    read_outcomes: Sequence[RuntimeReadOutcome],
    *,
    include_resolution: bool = False,
) -> None:
    """Project current durable attempts into diagnostics, without caching state.

    Preserve both original write points: the read-history snapshot is always
    updated first; the candidate lifecycle summary is refreshed *only* after
    a real completed chain. Materialized seeds and exhausted external attempts
    did not write a resolution summary and must continue not to do so.
    """

    context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})["reads"] = [
        outcome.to_dict() for outcome in read_outcomes
    ]
    if include_resolution:
        context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})[
            "candidate_resolution"
        ] = resolution_summary(read_outcomes)


def _record_atomic_routing_decisions(
    context: dict[str, Any],
    *,
    wave_index: int,
    records: Sequence[Mapping[str, Any]],
) -> None:
    """Observe already-decided claim routing without choosing extraction targets."""

    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if not isinstance(metrics, dict):
        return
    entries = metrics.get("atomic_routing")
    entries = entries if isinstance(entries, list) else []
    for record in records:
        entries.append({"wave_index": wave_index, **record})
    metrics["atomic_routing"] = entries[-60:]


def _record_atomic_routing_extractions(
    context: dict[str, Any],
    *,
    wave_index: int,
    routed_pairs: set[tuple[str, str]],
    selected_sources: Sequence[Mapping[str, Any]],
) -> None:
    """Record extracted results for routed pairs; never decide claim support."""

    if not routed_pairs:
        return
    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if not isinstance(metrics, dict):
        return
    observed = metrics.get("atomic_routing_extractions")
    observed = observed if isinstance(observed, list) else []
    for routed_candidate_id, routed_claim_id in sorted(routed_pairs):
        source = next(
            (
                item
                for item in selected_sources
                if item.get("candidate_id") == routed_candidate_id
            ),
            None,
        )
        if source is None:
            continue
        extraction = (source.get("extractions") or {}).get(routed_claim_id)
        if not isinstance(extraction, Mapping):
            continue
        observed.append(
            {
                "wave_index": wave_index,
                "read_artifact_id": routed_candidate_id,
                "origin_claim_id": "",
                "claim_id": routed_claim_id,
                "status": str(extraction.get("status") or ""),
                "relation": str(extraction.get("relation") or ""),
                "source_cluster_id": str(extraction.get("source_cluster_id") or ""),
            }
        )
    metrics["atomic_routing_extractions"] = observed[-60:]


def _record_read_chain_decision(
    context: dict[str, Any],
    *,
    candidate_id: str,
    chain_run: ChainRun,
    chain_steps: list[ChainStepResult],
) -> None:
    """Record routing even when a chain ran no backend; diagnostics only."""

    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if not isinstance(metrics, dict):
        return
    entries = metrics.get("read_chain")
    if not isinstance(entries, list):
        entries = []
    entries.append(
        {
            "candidate_id": candidate_id,
            "action": str(chain_run.action),
            "reason": str(chain_run.reason),
            "attempted_backends": list(chain_run.attempted_backends),
            "steps": [step.to_dict() for step in chain_steps],
        }
    )
    metrics["read_chain"] = entries[-60:]


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


def _record_escalation_diagnostics(
    context: dict[str, Any], escalation: Mapping[str, Any], *, wave_index: int
) -> None:
    """§71C-3a: one escalation outcome -> retrieval attempt + terminal invocation.

    Order matters: the invocation is created (and its id mirrored into the
    escalation payload) BEFORE the attempt row is appended, so the row carries
    the same id the source provenance uses. Not-attempted escalations (already
    adequate, disabled) never create an invocation.

    Reads carry no claim id (the source record keeps that link), so the ledger
    entry is wave-scoped and the funnel joins it per claim. Diagnostics only:
    the read payload already decided the outcome.
    """

    from src.web.research.retrieval_backends import (
        READ_OPERATION,
        TERMINAL_RETRIEVAL_STATES,
        create_retrieval_invocation,
        finalize_retrieval_invocation,
        retrieval_attempt_row,
    )

    def _provider() -> Any:
        metrics = context.get(ACTIVE_RESEARCH_METRICS_KEY)
        return metrics if isinstance(metrics, MutableMapping) else None

    tier = str(escalation.get("tier") or "http")
    state = str(escalation.get("state") or "")
    state = state if state in TERMINAL_RETRIEVAL_STATES else "empty"
    attempted = bool(escalation.get("attempted"))
    latency_ms = float(escalation.get("latency_ms") or 0.0)
    chars_after = int(escalation.get("chars_after") or 0)

    metrics = context.get(ACTIVE_RESEARCH_METRICS_KEY)
    if not isinstance(metrics, dict):
        return

    entry: dict[str, Any] | None = None
    if attempted:
        entry = create_retrieval_invocation(
            _provider,
            claim_id="read",
            wave_index=int(wave_index),
            backend="wigolo",
            operation=READ_OPERATION,
        )
        entry["tier"] = tier
        if isinstance(escalation, MutableMapping):
            # B1: the source provenance links to the ledger by invocation_id
            escalation["invocation_id"] = entry["invocation_id"]

    rows = metrics.get("retrieval_attempts")
    if not isinstance(rows, list):
        rows = []
    rows.append(
        retrieval_attempt_row(
            backend="wigolo",
            operation=READ_OPERATION,
            claim_id="",
            wave_index=int(wave_index),
            latency_ms=latency_ms,
            result_count=1 if attempted else 0,
            bytes=chars_after,
            cache_hit=bool(escalation.get("cache_hit")),
            escalation_reason=str(escalation.get("reason") or ""),
        )
        | {
            "tier": tier,
            "transition": str(escalation.get("shape_before") or "")
            + " -> "
            + str(escalation.get("shape_after") or ""),
            "preflight": str(escalation.get("preflight") or ""),
            "max_chars_requested": int(escalation.get("max_chars_requested") or 0),
            "url": str(escalation.get("url") or ""),
            "attempt_seq": int(escalation.get("attempt_seq") or 0),
            "research_seconds_left_at_start": escalation.get(
                "research_seconds_left_at_start"
            ),
            "hard_seconds_left_at_start": escalation.get("hard_seconds_left_at_start"),
            "invocation_id": str(escalation.get("invocation_id") or ""),
            "envelope_remaining_at_start_ms": escalation.get(
                "envelope_remaining_at_start_ms"
            ),
            "effective_timeout_seconds": escalation.get("effective_timeout_seconds"),
        }
    )
    metrics["retrieval_attempts"] = rows[-60:]
    if entry is not None:
        finalize_retrieval_invocation(
            _provider,
            entry,
            state=state,
            result_count=1 if chars_after else 0,
            bytes=chars_after,
            cache_hit=bool(escalation.get("cache_hit")),
            escalation_reason=str(escalation.get("reason") or ""),
            latency_ms=latency_ms,
        )
