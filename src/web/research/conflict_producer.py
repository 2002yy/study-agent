"""AR-1C-2-E3: turn a model's conflict claim into a verified motion event.

The division of labour is the whole point, and it is enforced here rather than
described in a prompt:

| step | who |
| --- | --- |
| fetch and record what each page actually says | shell (already done: reads carry ``read_id``) |
| decide that two statements disagree *about the same thing* | model |
| judge whether the disagreement is material to the answer | existing evidence quality gate |
| check both sides name a real read, a real target and a valid version | shell (this module) |
| execute the authorised revision | coordinator |
| write the new wording | model |

So this module never decides that a conflict exists. It receives the model's
*claim* - "these two texts disagree, and here is the sentence each side comes
from" - and refuses it unless every element of the claim is backed by something
the run actually persisted. A mismatch of two numbers in two pages is not a
conflict; only the model's interpretation makes it one, and only the shell's
checks make it actionable.

The event may then propose a retraction (withdraw the old conclusion and wait
for re-verification). It never invents replacement text: a conflict says "we do
not know which is right", which is the opposite of a replacement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.web.research.answer_state import CURRENT
from src.web.research.motion_events import EVIDENCE_CONFLICT, MotionEvent
from src.web.research.read_evidence import (
    ReadEvidence,
    _normalize_url,
    _quote_matches,
    verify_binding,
)

#: A quote shorter than this cannot identify a claim; it matches everything.
MIN_QUOTE_CHARS = 8
#: The trace keeps excerpts readable, not complete.
MAX_QUOTE_CHARS = 400

# Refusal codes. Each one names the missing fact, so a caller can log why a
# conflict did not become an event instead of guessing.
CONFLICT_UNEXPLAINED = "conflict_unexplained"
TARGET_MISSING = "target_missing"
TARGET_NOT_CURRENT = "target_not_current"
OLD_QUOTE_NOT_IN_REPLY = "old_quote_not_in_reply"
OLD_SOURCE_NOT_CITED = "old_source_not_cited"
SAME_SOURCE = "same_source"
QUOTES_IDENTICAL = "quotes_identical"
READ_NOT_NEWER = "read_not_newer"


@dataclass(frozen=True)
class ConflictClaim:
    """What the model says is in conflict, and where each side comes from.

    ``claim`` is the model's interpretation and is required: the shell has no way
    to tell "these disagree" from "these are two different measurements of two
    different things", so it must not try.

    ``new_binding`` is the usual source binding (url + quote + ``read_id``) for
    the *new* page. ``old_source_url`` is optional only because an older answer
    may predate per-source citations; when it is present it must be one of the
    reply's own sources.
    """

    target_reply_id: str
    claim: str
    old_quote: str
    new_quote: str
    new_binding: Mapping[str, Any]
    old_source_url: str = ""
    condition: str = ""


def build_conflict_event(
    claim: ConflictClaim,
    *,
    replies: Sequence[Mapping[str, Any]],
    evidence: Sequence[ReadEvidence],
    run_id: str,
    at: str,
    round_index: int = 0,
    notes: int = 0,
    revision: str = "",
) -> tuple[MotionEvent | None, str]:
    """Return ``(event, "")`` when every part of the claim checks out.

    Otherwise return ``(None, refusal)``. Producing no event is the correct
    outcome for an unbacked claim - an event is what grants the retraction.
    """

    if not str(claim.claim or "").strip():
        return None, CONFLICT_UNEXPLAINED

    target_id = str(claim.target_reply_id or "").strip()
    if not target_id:
        return None, TARGET_MISSING
    target = next(
        (item for item in replies if str(item.get("reply_id") or "") == target_id),
        None,
    )
    if target is None:
        return None, TARGET_MISSING
    if str(target.get("lifecycle") or "") != CURRENT:
        return None, TARGET_NOT_CURRENT

    old_quote = str(claim.old_quote or "").strip()
    if len(old_quote) < MIN_QUOTE_CHARS:
        return None, OLD_QUOTE_NOT_IN_REPLY
    if not _quote_matches(old_quote, _reply_text(target)):
        return None, OLD_QUOTE_NOT_IN_REPLY

    cited = {
        _normalize_url(item.get("url"))
        for item in target.get("citations") or []
        if isinstance(item, Mapping)
    }
    old_url = _normalize_url(claim.old_source_url)
    if old_url and cited and old_url not in cited:
        return None, OLD_SOURCE_NOT_CITED

    binding = dict(claim.new_binding or {})
    refusal = verify_binding(binding, evidence)
    if refusal:
        return None, refusal

    new_url = _normalize_url(binding.get("url"))
    if old_url and old_url == new_url:
        # A page cannot contradict itself. A page that *changed* is a re-read,
        # which is the replace path, not this one.
        return None, SAME_SOURCE

    new_quote = str(claim.new_quote or "").strip()
    if len(new_quote) < MIN_QUOTE_CHARS:
        return None, "binding_without_quote"
    if _normalized(new_quote) == _normalized(old_quote):
        return None, QUOTES_IDENTICAL

    read = _read_for(binding, evidence)
    if read is None:
        return None, "source_not_read"
    if not _quote_matches(new_quote, read.excerpt):
        return None, "quote_not_in_read"

    target_round = int((target.get("content_state") or {}).get("round") or 0)
    if int(read.round) < target_round:
        # An older read cannot overturn a conclusion reached after it.
        return None, READ_NOT_NEWER

    event = MotionEvent(
        kind=EVIDENCE_CONFLICT,
        at=at,
        round=int(round_index),
        notes=int(notes),
        revision=str(revision or ""),
        cause=str(claim.claim)[:200],
        detail={
            "target_reply_id": target_id,
            # Both sides, so "which statement is contested" is never a guess.
            "conflicting_urls": [url for url in (old_url, new_url) if url],
            "verified": True,
            "claim": str(claim.claim)[:200],
            "old_quote": old_quote[:MAX_QUOTE_CHARS],
            "new_quote": new_quote[:MAX_QUOTE_CHARS],
            "source_bindings": [binding],
            "condition": str(claim.condition or "")[:200],
        },
    )
    return event, ""


def _normalized(text: str) -> str:
    return " ".join(str(text or "").split())


def _reply_text(reply: Mapping[str, Any]) -> str:
    return _normalized(str(reply.get("text") or ""))


def _read_for(binding: Mapping[str, Any], evidence: Sequence[ReadEvidence]) -> ReadEvidence | None:
    url = _normalize_url(binding.get("url"))
    read_id = str(binding.get("read_id") or "").strip()
    for item in evidence:
        if _normalize_url(item.url) != url:
            continue
        if read_id and item.read_id != read_id:
            continue
        return item
    return None


__all__ = [
    "CONFLICT_UNEXPLAINED",
    "ConflictClaim",
    "OLD_QUOTE_NOT_IN_REPLY",
    "OLD_SOURCE_NOT_CITED",
    "QUOTES_IDENTICAL",
    "READ_NOT_NEWER",
    "SAME_SOURCE",
    "TARGET_MISSING",
    "TARGET_NOT_CURRENT",
    "build_conflict_event",
]
