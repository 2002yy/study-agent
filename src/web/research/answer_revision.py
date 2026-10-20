"""Answer revision: keep, mark stale, retract or replace one displayed judgment.

A provisional reply is a statement the reader may already have acted on. When a
new condition or a contradicting read arrives, the system has to say which of
those statements still stands - and it must never "revise" by appending new text
to the old text, or by collapsing retraction into a soft ``stale`` flag.

This module is the deterministic half: it decides *whether* a proposed revision
is allowed to touch a reply, not whether a model thinks two sentences contradict
each other. Every proposal is a **request**, never a publication permit:

* ``keep``    - the statement is unaffected; nothing changes.
* ``stale``   - we cannot yet tell whether it still holds; it may not be read as
               a current conclusion.
* ``retract`` - it must no longer be used as a conclusion; the text and the
               reason stay visible for traceability.
* ``replace`` - new content replaces the old one, but only after it passes the
               same evidence rules as any other publication (and, in strict
               mode, only when it is evidence-backed).

Guards, all deterministic:

* the proposal must name the exact content version it was derived from, so a
  concurrent writer cannot be overwritten (same rule as ``based_on_version``);
* the proposal must not be derived from an *older* research state than the reply
  already reflects (``round``/``notes`` are monotone; the interim revision hash is
  an identity, never an ordering);
* a reply that is retracted or superseded is terminal for that reply: a late
  writer cannot revive it, and the merge treats both the same way;
* applying the same proposal twice is refused (the version has moved);
* a replacement that makes a claim without a source binding is refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from src.web.research.answer_layers import claims_need_evidence

KEEP = "keep"
STALE = "stale"
RETRACT = "retract"
REPLACE = "replace"

#: The actions a proposal may ask for.
ACTIONS = frozenset({KEEP, STALE, RETRACT, REPLACE})

#: How many past contents a reply keeps so a retraction stays explainable.
MAX_REVISION_HISTORY = 5

RETRACTED_TEXT_SUFFIX = "（这条判断已撤回，不再作为当前结论）"


class RevisionProposalError(ValueError):
    """A proposal is malformed; nothing is applied."""


@dataclass(frozen=True)
class RevisionProposal:
    target_reply_id: str
    target_content_version: int
    action: str
    reason: str
    research_revision: str = ""
    research_round: int = 0
    research_notes: int = 0
    replacement: str = ""
    source_refs: tuple[str, ...] = ()
    strict: bool = False
    #: Deterministic rules or a model may propose; only the rules decide.
    proposed_by: str = "deterministic"

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise RevisionProposalError(f"unknown revision action: {self.action!r}")
        if not str(self.target_reply_id or "").strip():
            raise RevisionProposalError("target_reply_id is required")
        if int(self.target_content_version) < 0:
            raise RevisionProposalError("target_content_version must be >= 0")
        if not str(self.reason or "").strip():
            raise RevisionProposalError("reason is required")
        if self.action == REPLACE and not str(self.replacement or "").strip():
            raise RevisionProposalError("replace requires a replacement")

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_reply_id": self.target_reply_id,
            "target_content_version": int(self.target_content_version),
            "action": self.action,
            "reason": str(self.reason)[:300],
            "research_revision": str(self.research_revision),
            "research_round": int(self.research_round),
            "research_notes": int(self.research_notes),
            "replacement": str(self.replacement)[:1200],
            "source_refs": list(self.source_refs),
            "strict": bool(self.strict),
            "proposed_by": self.proposed_by,
        }


@dataclass(frozen=True)
class RevisionDecision:
    proposal: RevisionProposal
    accepted: bool
    applied: str = ""
    refusal: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal": self.proposal.to_dict(),
            "accepted": self.accepted,
            "applied": self.applied,
            "refusal": self.refusal,
        }


def _state_key(reply: Mapping[str, Any]) -> tuple[int, int]:
    state = reply.get("content_state")
    if not isinstance(state, Mapping):
        return (0, 0)

    def _int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    return (_int(state.get("round")), _int(state.get("notes")))


def _version(reply: Mapping[str, Any]) -> int:
    try:
        return int(reply.get("content_version") or 0)
    except (TypeError, ValueError):
        return 0


def _terminal_lifecycle(reply: Mapping[str, Any]) -> str:
    lifecycle = str(reply.get("lifecycle") or "")
    if lifecycle in {"retracted", "superseded", "closed"}:
        return lifecycle
    return ""


def evaluate(proposal: RevisionProposal, reply: Mapping[str, Any]) -> RevisionDecision:
    """Decide whether one proposal may touch one reply. No side effects."""

    if str(reply.get("reply_id") or "") != proposal.target_reply_id:
        return RevisionDecision(proposal, False, refusal="wrong_target")
    if _terminal_lifecycle(reply) in {"retracted", "superseded"}:
        # A withdrawn statement is history: a late writer cannot revive it.
        return RevisionDecision(proposal, False, refusal="terminal_lifecycle")
    if _version(reply) != int(proposal.target_content_version):
        return RevisionDecision(proposal, False, refusal="stale_target_version")
    if (int(proposal.research_round), int(proposal.research_notes)) < _state_key(reply):
        return RevisionDecision(proposal, False, refusal="older_research_state")
    if proposal.action == KEEP:
        return RevisionDecision(proposal, True, applied=KEEP)
    if proposal.action == STALE:
        return RevisionDecision(proposal, True, applied=STALE)
    if proposal.action == RETRACT:
        return RevisionDecision(proposal, True, applied=RETRACT)
    # replace: the new text must pass the ordinary publication rules.
    refunds = claims_need_evidence(proposal.replacement)
    if refunds and not proposal.source_refs:
        return RevisionDecision(proposal, False, refusal="replacement_unbacked_claim")
    if proposal.strict and not proposal.source_refs:
        return RevisionDecision(proposal, False, refusal="strict_requires_evidence")
    return RevisionDecision(proposal, True, applied=REPLACE)


def _append_history(reply: Mapping[str, Any], entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    history = [dict(item) for item in (reply.get("revision_history") or []) if isinstance(item, dict)]
    history.append(dict(entry))
    return history[-MAX_REVISION_HISTORY:]


def apply_decision(
    reply: Mapping[str, Any], decision: RevisionDecision, *, now: str
) -> dict[str, Any]:
    """Apply one accepted decision to one reply (pure; returns a new dict)."""

    if not decision.accepted:
        raise RevisionProposalError(f"refused decision: {decision.refusal}")
    from src.web.research.steering_replies import (
        LIFECYCLE_OPEN,
        LIFECYCLE_RETRACTED,
        advance_content,
    )

    current = dict(reply)
    action = decision.applied
    from_version = _version(current)
    if action == KEEP:
        return current
    if action == STALE:
        if current.get("stale"):
            return current
        updated = {**current, "stale": True}
        updated = advance_content(updated, now=now)
        updated["last_revision"] = {
            "action": STALE,
            "reason": decision.proposal.reason[:300],
            "at": now,
            "from_version": from_version,
            "research_revision": decision.proposal.research_revision,
        }
        updated["revision_history"] = _append_history(current, updated["last_revision"])
        return updated
    if action == RETRACT:
        text = str(current.get("text") or "")
        if not text.endswith(RETRACTED_TEXT_SUFFIX):
            text = f"{text}{RETRACTED_TEXT_SUFFIX}"[:1200]
        updated = {
            **current,
            "lifecycle": LIFECYCLE_RETRACTED,
            "stale": True,
            "text": text,
        }
        updated = advance_content(updated, now=now)
        updated["last_revision"] = {
            "action": RETRACT,
            "reason": decision.proposal.reason[:300],
            "at": now,
            "from_version": from_version,
            "research_revision": decision.proposal.research_revision,
        }
        updated["revision_history"] = _append_history(current, updated["last_revision"])
        return updated
    # replace: keep the previous body traceable, then publish the new one.
    kept = {
        "text": str(current.get("text") or "")[:1200],
        "content_version": from_version,
        "stage": str(current.get("stage") or ""),
    }
    updated = {
        **current,
        "lifecycle": LIFECYCLE_OPEN,
        "text": str(decision.proposal.replacement)[:1200],
        "citations": list(current.get("citations") or []),
    }
    updated = advance_content(updated, now=now)
    updated["last_revision"] = {
        "action": REPLACE,
        "reason": decision.proposal.reason[:300],
        "at": now,
        "from_version": from_version,
        "research_revision": decision.proposal.research_revision,
        "source_refs": list(decision.proposal.source_refs),
    }
    history = _append_history(current, updated["last_revision"])
    history.append(kept)
    updated["revision_history"] = history[-MAX_REVISION_HISTORY:]
    return updated


def apply_proposals(
    replies: Sequence[Any],
    proposals: Iterable[RevisionProposal],
    *,
    now: str,
) -> tuple[list[dict[str, Any]], list[RevisionDecision]]:
    """Evaluate and apply proposals in order; return the replies and the audit."""

    current = [dict(item) for item in replies if isinstance(item, dict)]
    decisions: list[RevisionDecision] = []
    for proposal in proposals:
        index = next(
            (i for i, reply in enumerate(current) if reply.get("reply_id") == proposal.target_reply_id),
            None,
        )
        if index is None:
            decisions.append(RevisionDecision(proposal, False, refusal="unknown_reply"))
            continue
        decision = evaluate(proposal, current[index])
        decisions.append(decision)
        if decision.accepted:
            current[index] = apply_decision(current[index], decision, now=now)
    return current, decisions
