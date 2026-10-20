"""Motion-state semantics: what happened, and which revisions it may propose.

The static side answers "what holds right now". This module answers "what is
happening, and what does it ask the answer to reconsider" - and it may only
propose. Nothing here writes a conclusion; a proposal still has to pass the
deterministic gate in :mod:`src.web.research.answer_revision`.

Events (each carries the research state it was observed at, so a proposal can be
refused when it is older than the reply it targets):

| event | meaning |
| --- | --- |
| ``evidence_read`` | a page was really read (and may bound a replacement) |
| ``evidence_conflict`` | a read contests an existing judgment |
| ``condition_added`` | the reader added a requirement |
| ``condition_corrected`` | the reader replaced a requirement |
| ``read_failed`` | a source could not be read |
| ``terminal`` | the run reached a terminal status |

Deliberate limits: an event never invents replacement text. ``evidence_read``
only proposes ``replace`` when the caller supplies text that is bound to a real
source; otherwise it produces nothing. ``read_failed`` and ``terminal`` never
retract anything on their own - a failed read is a gap, not a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping, Sequence

from src.web.research.answer_revision import (
    RETRACT,
    STALE,
    REPLACE,
    RevisionDecision,
    RevisionProposal,
    apply_proposals,
)
from src.web.research.answer_state import (
    CURRENT,
    StaticAnswerSnapshot,
    snapshot_from_replies,
)

EVIDENCE_READ = "evidence_read"
EVIDENCE_CONFLICT = "evidence_conflict"
CONDITION_ADDED = "condition_added"
CONDITION_CORRECTED = "condition_corrected"
READ_FAILED = "read_failed"
TERMINAL = "terminal"

MOTION_EVENTS = frozenset(
    {
        EVIDENCE_READ,
        EVIDENCE_CONFLICT,
        CONDITION_ADDED,
        CONDITION_CORRECTED,
        READ_FAILED,
        TERMINAL,
    }
)

#: Events that may change what the reader should believe.
REVISING_EVENTS = frozenset({EVIDENCE_CONFLICT, CONDITION_ADDED, CONDITION_CORRECTED, EVIDENCE_READ})

TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "cancelled"})

MAX_RECORDED_EVENTS = 20


@dataclass(frozen=True)
class MotionEvent:
    kind: str
    at: str
    #: Stable identity: a redelivered event must not be applied twice. Derived
    #: deterministically when the producer does not supply one.
    event_id: str = ""
    round: int = 0
    notes: int = 0
    revision: str = ""
    cause: str = ""
    #: Free-form but bounded: condition text, conflicting urls, replacement text.
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in MOTION_EVENTS:
            raise ValueError(f"unknown motion event: {self.kind!r}")
        if not str(self.at or "").strip():
            raise ValueError("motion event requires a timestamp")

    def identity(self) -> str:
        if str(self.event_id or "").strip():
            return str(self.event_id)
        payload = "|".join(
            [
                self.kind,
                str(self.at),
                str(int(self.round)),
                str(int(self.notes)),
                str(self.revision),
                json.dumps(_bounded_detail(self.detail), ensure_ascii=False, sort_keys=True),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.identity(),
            "kind": self.kind,
            "at": str(self.at),
            "round": int(self.round),
            "notes": int(self.notes),
            "revision": str(self.revision),
            "cause": str(self.cause)[:200],
            "detail": _bounded_detail(self.detail),
        }


def _bounded_detail(detail: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the trace a diagnostic window, not an unbounded log."""

    bounded: dict[str, Any] = {}
    for index, (key, value) in enumerate(dict(detail or {}).items()):
        if index >= 8:
            break
        if isinstance(value, str):
            bounded[str(key)[:40]] = value[:200]
        elif isinstance(value, (int, float, bool)) or value is None:
            bounded[str(key)[:40]] = value
        elif isinstance(value, (list, tuple)):
            bounded[str(key)[:40]] = [
                (str(item)[:200] if not isinstance(item, dict) else _bounded_detail(item))
                for item in list(value)[:5]
            ]
        elif isinstance(value, Mapping):
            bounded[str(key)[:40]] = _bounded_detail(value)
    return bounded


def record_event(context: dict[str, Any], event: MotionEvent) -> None:
    """Append the event to the run's bounded motion trace (audit only)."""

    history = [
        dict(item)
        for item in (context.get("revision_events") or [])
        if isinstance(item, dict)
    ]
    history.append(event.to_dict())
    context["revision_events"] = history[-MAX_RECORDED_EVENTS:]


def _proposal(
    *,
    statement,
    event: MotionEvent,
    action: str,
    reason: str,
    replacement: str = "",
    source_refs: Sequence[str] = (),
    source_bindings: Sequence[Mapping[str, Any]] = (),
    strict: bool = False,
) -> RevisionProposal:
    return RevisionProposal(
        target_reply_id=statement.reply_id,
        target_content_version=statement.content_version,
        action=action,
        reason=reason,
        research_revision=event.revision,
        research_round=int(event.round),
        research_notes=int(event.notes),
        replacement=replacement,
        source_refs=tuple(source_refs),
        source_bindings=tuple(dict(item) for item in source_bindings),
        strict=strict,
        proposed_by="motion",
    )


def proposals_for_event(
    event: MotionEvent,
    snapshot: StaticAnswerSnapshot,
    *,
    strict: bool = False,
) -> list[RevisionProposal]:
    """What this event may ask the answer to reconsider. Never guesses content."""

    proposals: list[RevisionProposal] = []

    if event.kind == CONDITION_ADDED or event.kind == CONDITION_CORRECTED:
        # A requirement the reply predates cannot be assumed to cover it. This is
        # a *stale* proposal, not a retraction: only evidence settles that.
        condition = str((event.detail or {}).get("condition") or "").strip()
        # The reply that carries the new condition is not "not covering" itself.
        keep_reply_id = str((event.detail or {}).get("keep_reply_id") or "").strip()
        for statement in snapshot.statements:
            if keep_reply_id and statement.reply_id == keep_reply_id:
                continue
            if statement.lifecycle != CURRENT:
                continue
            if statement.kind not in {"knowledge", "conditional", "evidence"}:
                continue
            # Already re-judged in (or after) the round the condition arrived in:
            # marking it again would undo a newer answer with an older event.
            # Round is the axis the runtime already uses for this comparison, so
            # the coordinator stays equivalent to mark_additions_stale.
            if statement.research_round >= int(event.round):
                continue
            proposals.append(
                _proposal(
                    statement=statement,
                    event=event,
                    action=STALE,
                    reason=f"新增条件未覆盖：{condition}" if condition else "新增条件",
                    strict=strict,
                )
            )
        return proposals

    if event.kind == EVIDENCE_CONFLICT:
        contested = {str(url) for url in (event.detail or {}).get("conflicting_urls") or []}
        if not contested:
            # Without a locatable source we cannot say which statement is
            # contested. Retracting everything would be a guess, not a revision.
            return []
        for statement in snapshot.statements:
            if statement.lifecycle != CURRENT:
                continue
            if not (set(statement.source_refs) & contested):
                continue
            # Withdraw the conclusion; do not write a new one from a conflict.
            proposals.append(
                _proposal(
                    statement=statement,
                    event=event,
                    action=RETRACT,
                    reason=str(event.cause or "新证据与旧判断冲突，等待重新核验"),
                    strict=strict,
                )
            )
        return proposals

    if event.kind == EVIDENCE_READ:
        replacement = str((event.detail or {}).get("replacement") or "").strip()
        bindings = tuple(
            dict(item)
            for item in (event.detail or {}).get("source_bindings") or []
            if isinstance(item, dict)
        )
        target = str((event.detail or {}).get("target_reply_id") or "").strip()
        if not replacement or not bindings or not target:
            # A read alone proves nothing about how to phrase the answer.
            return []
        statement = next(
            (item for item in snapshot.statements if item.reply_id == target), None
        )
        if statement is None or statement.lifecycle != CURRENT:
            return []
        proposals.append(
            _proposal(
                statement=statement,
                event=event,
                action=REPLACE,
                reason=str(event.cause or "新证据支持重写"),
                replacement=replacement,
                source_bindings=bindings,
                strict=strict,
            )
        )
        return proposals

    # read_failed / terminal: a gap or an end, never a verdict.
    return []


def apply_event(
    replies: Sequence[Any],
    event: MotionEvent,
    *,
    now: str,
    run_id: str,
    turn_id: str,
    conditions: Sequence[str] = (),
    strict: bool = False,
    attachment_present: bool = False,
) -> tuple[list[dict[str, Any]], list[RevisionDecision], StaticAnswerSnapshot]:
    """Reference implementation: snapshot -> proposals -> decisions."""

    snapshot = snapshot_from_replies(
        replies,
        run_id=run_id,
        turn_id=turn_id,
        conditions=conditions,
        research_state={"round": event.round, "notes": event.notes, "revision": event.revision},
        attachment_present=attachment_present,
    )
    proposals = proposals_for_event(event, snapshot, strict=strict)
    updated, decisions = apply_proposals(replies, proposals, now=now)
    return updated, decisions, snapshot
