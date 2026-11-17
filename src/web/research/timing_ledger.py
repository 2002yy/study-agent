"""F2-S1 causal timing ledger: exclusive spans, per-wave parent records.

Pure observation. It answers two orthogonal questions the F2 characterization
needs, without touching any count, timeout, selector, retry or budget rule:

(a) *why is this phase slow* - call count growth or per-call latency growth -
    via per-kind model wait totals (selector / assessment / extraction), plus a
    separate backoff-wait vs re-fetch split for read retries;
(b) *where in the run is the time going* - via a per-wave parent record.

Timing discipline (frozen for this batch):

* one monotonic clock for every span (the runtime's run-relative milliseconds);
* child spans record **exclusive** wall time: a span's own total is its inclusive
  duration minus the time spent inside nested spans, so summing siblings never
  exceeds the parent;
* ``model_wait_ms`` is a *component* of the phase span that contains the call -
  it is reported next to it, never added on top of it;
* ``unattributed_ms`` = wave wall time minus the mutually exclusive spans the
  ledger actually observed, which is what makes the residual meaningful.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

ACTIVE_RESEARCH_METRICS_KEY = "claim_engine_metrics"

MODEL_KINDS = ("selector", "assessment", "extraction", "planner", "support", "other")

_PURPOSE_TO_KIND = {
    "research_selection_authority": "selector",
    "research_candidate_assessment": "assessment",
    "research_evidence_extraction": "extraction",
    "research_claim_planning": "planner",
    "research_support_formation": "support",
}


def _record_checkpoint_timing(
    context: dict[str, Any],
    diagnostics: Mapping[str, Any],
    *,
    wall_ms: float,
    stage: str | None,
    caller: str,
    phase: str = "",
) -> None:
    """F2-O4a: per-checkpoint persistence cost, without any of its content.

    Records how long one checkpoint took, how much was written and in which
    section, whether it actually differed from the previous checkpoint (by
    section identity, never by storing content), and how long it has been since
    the previous one. Observation only: it never debounces, coalesces or skips a
    checkpoint, and durability semantics are untouched.
    """

    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if not isinstance(metrics, dict):
        return
    entries = metrics.get("checkpoint_timing")
    if not isinstance(entries, list):
        entries = []
    previous = entries[-1] if entries else {}
    previous_hashes = (
        previous.get("section_hashes") if isinstance(previous, Mapping) else None
    )
    hashes = diagnostics.get("section_hashes")
    hashes = hashes if isinstance(hashes, Mapping) else {}
    sizes = diagnostics.get("bytes_by_section")
    sizes = sizes if isinstance(sizes, Mapping) else {}
    changed_sections: list[str] = []
    changed_bytes = 0
    unchanged_bytes = 0
    for section, size in sizes.items():
        same = bool(
            previous_hashes
            and isinstance(previous_hashes, Mapping)
            and previous_hashes.get(section) == hashes.get(section)
        )
        if same:
            unchanged_bytes += int(size)
        else:
            changed_sections.append(str(section))
            changed_bytes += int(size)
    previous_end = previous.get("t_end_ms") if isinstance(previous, Mapping) else None
    entry = {
        "ordinal": len(entries) + 1,
        "t_end_ms": round(float(_checkpoint_now_ms()), 1),
        "wall_ms": round(float(wall_ms), 1),
        "stage": str(stage or ""),
        "caller": str(caller or ""),
        "phase": str(phase or ""),
        "since_previous_ms": (
            round(float(_checkpoint_now_ms()) - float(previous_end), 1)
            if previous_end is not None
            else None
        ),
        "attempts": int(diagnostics.get("attempts") or 0),
        "conflicts": int(diagnostics.get("conflicts") or 0),
        "repo_call_ms": float(diagnostics.get("repo_call_ms") or 0.0),
        "prep_ms": round(
            max(0.0, float(wall_ms) - float(diagnostics.get("repo_call_ms") or 0.0)), 1
        ),
        "load_ms": float(diagnostics.get("load_ms") or 0.0),
        "repo_other_ms": float(diagnostics.get("repo_other_ms") or 0.0),
        "serialize_ms": float(diagnostics.get("serialize_ms") or 0.0),
        "write_ms": float(diagnostics.get("write_ms") or 0.0),
        "hash_ms": float(diagnostics.get("hash_ms") or 0.0),
        "bytes_total": int(diagnostics.get("bytes_total") or 0),
        "bytes_by_section": {str(k): int(v) for k, v in sizes.items()},
        "changed_sections": changed_sections,
        "changed_bytes": changed_bytes,
        "unchanged_bytes": unchanged_bytes,
        "section_hashes": {str(k): str(v) for k, v in hashes.items()},
        "write_targets": int(diagnostics.get("write_targets") or 0),
        "files": int(diagnostics.get("files") or 0),
    }
    entries.append(entry)
    metrics["checkpoint_timing"] = entries[-120:]


def _checkpoint_now_ms() -> float:
    return round(time.monotonic() * 1000.0, 1)


def model_kind(purpose: str) -> str:
    """Map a gateway purpose to a coarse kind (unknown purposes -> ``other``)."""

    return _PURPOSE_TO_KIND.get(str(purpose or ""), "other")


@dataclass
class _Span:
    name: str
    started_ms: float
    child_ms: float = 0.0
    ended_ms: float = 0.0

    @property
    def inclusive_ms(self) -> float:
        return max(0.0, (self.ended_ms or self.started_ms) - self.started_ms)

    @property
    def exclusive_ms(self) -> float:
        return max(0.0, self.inclusive_ms - self.child_ms)


@dataclass
class _WaveRecord:
    wave_index: int
    start_ms: float
    end_ms: float = 0.0
    spans: dict[str, float] = field(default_factory=dict)
    model_calls: dict[str, int] = field(default_factory=dict)
    model_wait_ms: dict[str, float] = field(default_factory=dict)
    model_wait_max_ms: dict[str, float] = field(default_factory=dict)
    retry_count: int = 0
    retry_wait_ms: float = 0.0
    retry_fetch_ms: float = 0.0
    refresh_count: int = 0
    refresh_ms: float = 0.0
    checkpoint_count: int = 0
    checkpoint_ms: float = 0.0

    @property
    def duration_ms(self) -> float:
        return max(0.0, (self.end_ms or self.start_ms) - self.start_ms)

    def to_dict(self) -> dict[str, Any]:
        covered = sum(self.spans.values())
        return {
            "wave_index": self.wave_index,
            "t_start_ms": round(self.start_ms, 1),
            "t_end_ms": round(self.end_ms, 1),
            "duration_ms": round(self.duration_ms, 1),
            "spans_ms": {name: round(value, 1) for name, value in sorted(self.spans.items())},
            "model_calls": dict(sorted(self.model_calls.items())),
            "model_wait_ms": {k: round(v, 1) for k, v in sorted(self.model_wait_ms.items())},
            "model_wait_max_ms": {
                k: round(v, 1) for k, v in sorted(self.model_wait_max_ms.items())
            },
            "retry_count": self.retry_count,
            "retry_wait_ms": round(self.retry_wait_ms, 1),
            "retry_fetch_ms": round(self.retry_fetch_ms, 1),
            "refresh_steering_count": self.refresh_count,
            "refresh_steering_ms": round(self.refresh_ms, 1),
            "checkpoint_count": self.checkpoint_count,
            "checkpoint_ms": round(self.checkpoint_ms, 1),
            "covered_ms": round(covered, 1),
            "unattributed_ms": round(max(0.0, self.duration_ms - covered), 1),
        }


class TimingLedger:
    """Wave-scoped exclusive span accounting on one monotonic clock."""

    def __init__(self, now_ms: Callable[[], float]) -> None:
        self._now_ms = now_ms
        self._stack: list[_Span] = []
        self._waves: list[_WaveRecord] = []
        self._current: _WaveRecord | None = None
        self._open_phases: dict[str, _Span] = {}

    # ---------------------------------------------------------------- waves
    def start_wave(self, wave_index: int) -> None:
        self.end_wave()
        self._current = _WaveRecord(wave_index=int(wave_index), start_ms=self._now_ms())
        self._waves.append(self._current)
        self._waves = self._waves[-12:]

    def end_wave(self) -> None:
        if self._current is None:
            return
        self._current.end_ms = self._now_ms()
        self._current = None

    # ---------------------------------------------------------------- spans
    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        """Exclusive child span; nested time is attributed to the child only."""

        record = self._current
        span = _Span(name=str(name), started_ms=self._now_ms() if record else 0.0)
        if record is not None:
            self._stack.append(span)
        try:
            yield
        finally:
            if record is not None:
                span.ended_ms = self._now_ms()
                if self._stack and self._stack[-1] is span:
                    self._stack.pop()
                if self._stack:
                    # parent's exclusive time excludes this child
                    self._stack[-1].child_ms += span.inclusive_ms
                record.spans[name] = record.spans.get(name, 0.0) + span.exclusive_ms


    # ------------------------------------------------------------- phases
    def _phase_enter(self, name: str) -> None:
        # Open a named phase span inside the current wave.
        record = self._current
        if record is None:
            return
        span = _Span(name=str(name), started_ms=self._now_ms())
        self._stack.append(span)
        self._open_phases[str(name)] = span

    def _phase_exit(self, name: str) -> None:
        # Close the named phase span (tolerant of missing opens).
        record = self._current
        span = self._open_phases.pop(str(name), None)
        if record is None or span is None:
            return
        span.ended_ms = self._now_ms()
        if self._stack and self._stack[-1] is span:
            self._stack.pop()
        if self._stack:
            self._stack[-1].child_ms += span.inclusive_ms
        record.spans[span.name] = record.spans.get(span.name, 0.0) + span.exclusive_ms

    # ------------------------------------------------------- model / I/O waits
    def record_model_call(self, kind: str, wait_ms: float) -> None:
        record = self._current
        if record is None:
            return
        key = str(kind or "other")
        record.model_calls[key] = record.model_calls.get(key, 0) + 1
        record.model_wait_ms[key] = record.model_wait_ms.get(key, 0.0) + max(
            0.0, float(wait_ms)
        )
        record.model_wait_max_ms[key] = max(
            record.model_wait_max_ms.get(key, 0.0), float(wait_ms)
        )

    def record_retry(self, *, wait_ms: float = 0.0, fetch_ms: float = 0.0) -> None:
        record = self._current
        if record is None:
            return
        record.retry_count += 1
        record.retry_wait_ms += max(0.0, float(wait_ms))
        record.retry_fetch_ms += max(0.0, float(fetch_ms))

    def record_refresh(self, ms: float) -> None:
        record = self._current
        if record is None:
            return
        record.refresh_count += 1
        record.refresh_ms += max(0.0, float(ms))

    def record_checkpoint(self, ms: float) -> None:
        record = self._current
        if record is None:
            return
        record.checkpoint_count += 1
        record.checkpoint_ms += max(0.0, float(ms))

    def current_phase(self) -> str:
        """Name of the innermost open phase (diagnostics only)."""

        if not self._open_phases:
            return ""
        return str(next(reversed(self._open_phases)))

    # ---------------------------------------------------------------- output
    def to_metrics(self) -> dict[str, Any]:
        """Snapshot; also flushed into the run metrics by the runtime."""

        return {
            "wave_timeline": [record.to_dict() for record in self._waves],
            "timing_schema": "f2-wave-timeline-v1",
        }


class TimedGateway:
    """Transparent gateway proxy that times model calls into the ledger."""

    def __init__(self, inner: Any, ledger: TimingLedger, now_ms: Callable[[], float]) -> None:
        self._inner = inner
        self._ledger = ledger
        self._now_ms = now_ms

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def complete_structured(self, **kwargs: Any) -> Any:
        started = self._now_ms()
        try:
            return self._inner.complete_structured(**kwargs)
        finally:
            self._ledger.record_model_call(
                model_kind(str(kwargs.get("purpose") or "")),
                self._now_ms() - started,
            )


__all__ = [
    "MODEL_KINDS",
    "TimedGateway",
    "TimingLedger",
    "model_kind",
]
