"""§37B-selection: bounded selection provenance for discovery candidates.

The collector is a pure observation container. Instrumented call sites report
decisions the production code already made (canonicalization, dedupe, pool
caps, the assessment window, the read scheduler and the read loop). It never
re-derives a selection, never reorders candidates, never changes a budget and
is never persisted into the runtime cursor: its payload is written to the run
metrics as a diagnostic only.

Terminal attribution follows *first observed drop*: ``observed_drops`` is an
ordered observation log (provisional intermediate states included), and the
terminal reason is finalised from its first entry when the payload is produced
- and only for candidates that were never read. A candidate that was never
observed anywhere simply does not appear in the trace; joins treat it as
``unobserved``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

SELECTION_TRACE_VERSION = "research-selection-trace-v1"

TERMINAL_REASONS = (
    "not_materialized",
    "canonical_duplicate",
    "authority_or_policy_filter",
    "candidate_pool_excluded",
    "scheduler_not_selected",
    "read_budget_exhausted",
    "already_read",
    "unsupported_url",
    "other_observed_reason",
    "unobserved",
)


@dataclass
class SelectionTraceEntry:
    """One candidate's observed journey through the selection chain."""

    canonical_url: str
    seen_in_provider: bool = False
    normalized: bool = False
    materialized: bool = False
    deduped_survivor: bool = False
    filter_decision: str = ""
    filter_reason: str = ""
    entered_candidate_pool: bool = False
    candidate_pool_class: str = ""
    entered_scheduler: bool = False
    scheduler_rank: int | None = None
    scheduler_decision: str = ""
    scheduler_reason: str = ""
    read_dispatched: bool = False
    read_skip_reason: str = ""
    duplicate_merges: int = 0
    observed_drops: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "canonical_url": self.canonical_url,
            "seen_in_provider": self.seen_in_provider,
            "normalized": self.normalized,
            "materialized": self.materialized,
            "deduped_survivor": self.deduped_survivor,
            "filter_decision": self.filter_decision,
            "filter_reason": self.filter_reason,
            "entered_candidate_pool": self.entered_candidate_pool,
            "candidate_pool_class": self.candidate_pool_class,
            "entered_scheduler": self.entered_scheduler,
            "scheduler_rank": self.scheduler_rank,
            "scheduler_decision": self.scheduler_decision,
            "scheduler_reason": self.scheduler_reason,
            "read_dispatched": self.read_dispatched,
            "read_skip_reason": self.read_skip_reason,
            "duplicate_merges": self.duplicate_merges,
            "terminal_reason": self.final_terminal_reason(),
            "observed_drops": list(self.observed_drops),
        }
        return payload

    def final_terminal_reason(self) -> str:
        """First observed drop for unread candidates; empty when read."""

        if self.read_dispatched:
            return ""
        return self.observed_drops[0] if self.observed_drops else "unobserved"


class SelectionTraceCollector:
    """Bounded, deterministic recorder; a disabled collector is a no-op."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        max_candidates: int = 120,
        max_text: int = 160,
    ) -> None:
        self.enabled = bool(enabled)
        self.max_candidates = max(1, int(max_candidates))
        self.max_text = max(1, int(max_text))
        self._entries: dict[str, SelectionTraceEntry] = {}

    # -- internals ---------------------------------------------------------
    def _text(self, value: Any) -> str:
        return " ".join(str(value or "").split())[: self.max_text]

    def _entry(self, url: Any) -> SelectionTraceEntry | None:
        if not self.enabled:
            return None
        key = self._text(url)
        if not key:
            return None
        entry = self._entries.get(key)
        if entry is None:
            if len(self._entries) >= self.max_candidates:
                return None
            entry = SelectionTraceEntry(canonical_url=key)
            self._entries[key] = entry
        return entry

    def _drop(self, entry: SelectionTraceEntry, reason: str, detail: str = "") -> None:
        # Ordered observation log. The terminal attribution is finalised from
        # the first observed drop when the payload is produced, so provisional
        # intermediate states can never overwrite an earlier cause.
        if reason not in TERMINAL_REASONS:
            raise ValueError(f"unknown terminal reason: {reason}")
        if not entry.observed_drops or entry.observed_drops[-1] != reason:
            entry.observed_drops.append(reason)
        if detail and reason != "unobserved" and not entry.filter_reason:
            entry.filter_reason = self._text(detail)

    # -- observed events, in pipeline order --------------------------------
    def note_seen(self, url: Any) -> None:
        entry = self._entry(url)
        if entry is not None:
            entry.seen_in_provider = True

    def note_seen_many(self, urls: Iterable[Any]) -> None:
        for url in urls:
            self.note_seen(url)

    def note_normalized(self, url: Any) -> None:
        entry = self._entry(url)
        if entry is not None:
            entry.normalized = True

    def note_unusable(self, url: Any, *, had_canonical: bool) -> None:
        entry = self._entry(url)
        if entry is None:
            return
        entry.normalized = entry.normalized or had_canonical
        self._drop(
            entry,
            "not_materialized" if had_canonical else "unsupported_url",
            "canonical_url_or_title_missing",
        )

    def note_duplicate(self, url: Any) -> None:
        """A repeated occurrence merged into its own surviving candidate.

        This is a merge observation, not a drop: the pool item is keyed by the
        canonical URL, so the same URL observed again (or a raw variant that
        canonicalizes to it) always continues as the survivor. The
        ``canonical_duplicate`` terminal remains reserved for an observed
        distinct-URL loss, which the current pipeline does not produce.
        """

        entry = self._entry(url)
        if entry is not None:
            entry.duplicate_merges += 1

    def note_cap_excluded(self, url: Any, *, stage: str) -> None:
        entry = self._entry(url)
        if entry is not None:
            self._drop(entry, "candidate_pool_excluded", f"pool_cap:{stage}")

    def note_materialized(self, url: Any) -> None:
        entry = self._entry(url)
        if entry is not None:
            entry.materialized = True
            entry.deduped_survivor = True

    def note_pool_entered(self, url: Any, *, pool_class: str = "") -> None:
        entry = self._entry(url)
        if entry is not None:
            entry.entered_candidate_pool = True
            if pool_class:
                entry.candidate_pool_class = entry.candidate_pool_class or self._text(pool_class)

    def note_already_read(self, url: Any) -> None:
        entry = self._entry(url)
        if entry is not None:
            self._drop(entry, "already_read", "read_already_completed")

    def note_window(self, url: Any, *, selected: bool, reason: str = "") -> None:
        entry = self._entry(url)
        if entry is None:
            return
        if selected:
            return
        entry.filter_decision = entry.filter_decision or "rejected"
        self._drop(entry, "candidate_pool_excluded", f"assessment_window:{self._text(reason)}")

    def note_scheduler_rank(self, url: Any, *, rank: int) -> None:
        entry = self._entry(url)
        if entry is not None:
            entry.entered_scheduler = True
            if entry.scheduler_rank is None:
                entry.scheduler_rank = int(rank)

    def note_scheduler(self, url: Any, *, decision: str, reason: str = "") -> None:
        entry = self._entry(url)
        if entry is None:
            return
        if decision:
            entry.scheduler_decision = entry.scheduler_decision or self._text(decision)
        if reason:
            entry.scheduler_reason = entry.scheduler_reason or self._text(reason)

    def note_scheduler_rejected(self, url: Any, *, stage: str) -> None:
        entry = self._entry(url)
        if entry is None:
            return
        entry.scheduler_decision = entry.scheduler_decision or "rejected"
        self._drop(
            entry,
            "read_budget_exhausted" if stage == "budget" else "scheduler_not_selected",
            stage,
        )

    def note_scheduler_selected(self, url: Any) -> None:
        entry = self._entry(url)
        if entry is not None:
            entry.scheduler_decision = entry.scheduler_decision or "selected"

    def note_read(self, url: Any, *, dispatched: bool, skip_reason: str = "") -> None:
        entry = self._entry(url)
        if entry is None:
            return
        if dispatched:
            entry.read_dispatched = True
            return
        entry.read_skip_reason = entry.read_skip_reason or self._text(skip_reason)
        reason = (
            "read_budget_exhausted"
            if "budget" in skip_reason
            else "other_observed_reason"
        )
        self._drop(entry, reason, skip_reason)

    def note_policy_filter(self, url: Any, *, reason: str) -> None:
        entry = self._entry(url)
        if entry is not None:
            entry.filter_decision = entry.filter_decision or "rejected"
            self._drop(entry, "authority_or_policy_filter", reason)

    # -- payload -----------------------------------------------------------
    @classmethod
    def from_payload(cls, payload: Any) -> "SelectionTraceCollector":
        """Rebuild a collector from a prior metrics payload (resume-safe)."""

        collector = cls()
        if not isinstance(payload, dict):
            return collector
        for raw in payload.get("entries") or []:
            if not isinstance(raw, dict):
                continue
            url = raw.get("canonical_url")
            entry = collector._entry(url)
            if entry is None:
                continue
            for key, value in raw.items():
                if key == "observed_drops":
                    entry.observed_drops = [
                        item for item in (value or []) if item in TERMINAL_REASONS
                    ]
                elif key == "terminal_reason":
                    # Derived at payload time; never hydrated as storage.
                    continue
                elif hasattr(entry, key):
                    setattr(entry, key, value)
        return collector

    def to_payload(self) -> dict[str, Any]:
        entries = [entry.to_dict() for entry in self._entries.values()]
        return {
            "schema_version": SELECTION_TRACE_VERSION,
            "candidate_count": len(entries),
            "terminal_reasons": list(TERMINAL_REASONS),
            "entries": entries,
        }

    def __len__(self) -> int:
        return len(self._entries)


__all__ = [
    "SELECTION_TRACE_VERSION",
    "TERMINAL_REASONS",
    "SelectionTraceCollector",
    "SelectionTraceEntry",
]
