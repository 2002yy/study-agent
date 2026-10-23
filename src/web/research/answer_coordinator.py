"""AR-1C-1: one pure coordinator for "an event changed the answer".

The old path already writes state: a supplement is marked stale by
``mark_additions_stale``, a term correction supersedes the replies that spoke
about it, and only afterwards is a motion event recorded. If a coordinator then
replayed that event it would write a second time - double version bumps,
``already_stale`` churn, and a targeted ``superseded`` degrading into a global
``stale``.

This module is the single place an event may become a state change, and it is
**pure**: no IO, no persistence, identical input (including the set of already
consumed event ids) produces identical output. AR-1C-2 will call it from the
existing transaction; this slice only proves the transitions.

Two rules are deliberately kept explicit:

* **equivalence first**: for the two transitions the runtime already performs,
  the coordinator reproduces the legacy result field by field, and a pairing
  test proves it. Any difference is a bug until it is approved as a semantic
  change.
* **one consumer**: an event whose id has been consumed is skipped, so a
  redelivery cannot bump a version twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.web.research.answer_revision import RevisionDecision, apply_proposals
from src.web.research.answer_state import StaticAnswerSnapshot, snapshot_from_replies
from src.web.research.motion_events import (
    CONDITION_CORRECTED,
    MotionEvent,
    proposals_for_event,
)
from src.web.research.steering_replies import supersede_affected

#: A duplicate event is not an error; it simply has nothing left to do.
SKIP_DUPLICATE_EVENT = "duplicate_event"

#: The delegated lifecycle transition for a replaced term. Kept out of ACTIONS:
#: it is not a revision of a judgment, it is the judgment losing its subject.
SUPERSEDE = "supersede"


@dataclass(frozen=True)
class CoordinatorResult:
    replies: tuple[dict[str, Any], ...]
    decisions: tuple[RevisionDecision, ...]
    snapshot: StaticAnswerSnapshot
    delegated: tuple[Mapping[str, Any], ...] = ()
    audit: Mapping[str, Any] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.audit.get("applied"))


def coordinate(
    replies: Sequence[Any],
    event: MotionEvent,
    *,
    now: str,
    run_id: str,
    turn_id: str,
    conditions: Sequence[str] = (),
    strict: bool = False,
    attachment_present: bool = False,
    read_evidence: Sequence[Any] = (),
    consumed_event_ids: Iterable[str] = (),
) -> CoordinatorResult:
    """Consume one event and return the resulting replies, decisions and snapshot.

    ``consumed_event_ids`` is the caller's record of events already applied; the
    coordinator never mutates it (that belongs to the durable write in AR-1C-2).
    """

    consumed = {str(item) for item in consumed_event_ids if str(item).strip()}
    identity = event.identity()
    current = [dict(item) for item in replies if isinstance(item, Mapping)]
    snapshot = snapshot_from_replies(
        current,
        run_id=run_id,
        turn_id=turn_id,
        conditions=conditions,
        research_state={
            "round": event.round,
            "notes": event.notes,
            "revision": event.revision,
        },
        attachment_present=attachment_present,
    )
    if identity in consumed:
        return CoordinatorResult(
            replies=tuple(current),
            decisions=(),
            snapshot=snapshot,
            audit={
                "schema_version": "answer-coordination-v1",
                "event_id": identity,
                "kind": event.kind,
                "skipped": SKIP_DUPLICATE_EVENT,
                "applied": [],
            },
        )

    decisions: list[RevisionDecision] = []
    # A correction is a lifecycle transition the revision vocabulary does not
    # name (it is neither retraction nor staleness). It is delegated, and the
    # audit says so instead of inventing a retract proposal for it.
    delegated: list[dict[str, Any]] = []
    if event.kind == CONDITION_CORRECTED:
        # The runtime's correction semantics are "supersede the replies that
        # spoke about the replaced term". The AR-1A action vocabulary has no
        # supersede action, so this transition is delegated to the existing
        # implementation instead of being approximated by `stale` - and the
        # pairing test pins the equivalence.
        old_terms = [
            str(term)
            for term in (event.detail or {}).get("old_terms") or []
            if str(term).strip()
        ]
        before = {item.get("reply_id"): dict(item) for item in current}
        current = [
            dict(item)
            for item in supersede_affected(current, old_terms=old_terms, now=now)
        ]
        for reply in current:
            prior = before.get(reply.get("reply_id")) or {}
            if prior and reply != prior:
                delegated.append(
                    {
                        "reply_id": str(reply.get("reply_id") or ""),
                        "action": SUPERSEDE,
                        "delegated": True,
                        "from_version": int(prior.get("content_version") or 0),
                        "to_version": int(reply.get("content_version") or 0),
                    }
                )
    else:
        proposals = proposals_for_event(event, snapshot, strict=strict)
        current, applied = apply_proposals(
            current, proposals, now=now, read_evidence=read_evidence
        )
        decisions.extend(applied)

    after = snapshot_from_replies(
        current,
        run_id=run_id,
        turn_id=turn_id,
        conditions=conditions,
        research_state={
            "round": event.round,
            "notes": event.notes,
            "revision": event.revision,
        },
        attachment_present=attachment_present,
    )
    applied_summary = [
        {
            "reply_id": decision.proposal.target_reply_id,
            "action": decision.applied,
            "accepted": decision.accepted,
            "refusal": decision.refusal,
            "proposal_action": decision.proposal.action,
            "delegated": False,
        }
        for decision in decisions
        if decision.accepted
    ]
    applied_summary.extend(delegated)
    return CoordinatorResult(
        replies=tuple(current),
        decisions=tuple(decisions),
        snapshot=after,
        delegated=tuple(delegated),
        audit={
            "schema_version": "answer-coordination-v1",
            "event_id": identity,
            "kind": event.kind,
            "skipped": "",
            "applied": applied_summary,
            "before_version": snapshot.content_version,
            "after_version": after.content_version,
        },
    )
