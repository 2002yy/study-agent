"""Static-state semantics: what is true, right now, in this answer snapshot.

Two semantics live in this runtime and must not be conflated:

* **static** - a snapshot of what currently holds: which statements exist, what
  kind each one is, what the verification verdict is, which conditions are in
  force, and which gaps remain;
* **motion** - what is happening over time: planning, searching, reading,
  verifying, revising, blocked, cancelled, and *why* a change is proposed.

This module defines the static side only. It reads the structures the runtime
already has (provisional replies, their content state, their citations) and turns
them into one auditable snapshot. It never writes.

Three distinctions the code keeps:

1. **content kind** (`knowledge` / `evidence` / `conditional` / `unverified`) is
   *what a statement is*;
2. **verification** (`supported` / `conflict` / `insufficient` /
   `pending_verification` / `withheld`) is *how far it has been checked*;
3. **lifecycle** (`current` / `superseded` / `retracted` / `closed`) is *whether
   it may still be read as the current answer*.

A finished run is not a verified conclusion, and "verifying" never means "there
is nothing to answer": supported and knowledge statements stay readable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

#: What a statement is.
CONTENT_KINDS = frozenset({"knowledge", "evidence", "conditional", "unverified"})

#: How far the statement has been checked.
SUPPORTED = "supported"
CONFLICT = "conflict"
INSUFFICIENT = "insufficient"
PENDING_VERIFICATION = "pending_verification"
WITHHELD = "withheld"
VERIFICATION_STATES = frozenset(
    {SUPPORTED, CONFLICT, INSUFFICIENT, PENDING_VERIFICATION, WITHHELD}
)

#: Whether the statement may still be read as the current answer.
CURRENT = "current"
SUPERSEDED = "superseded"
RETRACTED = "retracted"
CLOSED = "closed"
LIFECYCLE_VIEWS = frozenset({CURRENT, SUPERSEDED, RETRACTED, CLOSED})

#: The motion vocabulary this snapshot understands (defined here so the two sets
#: cannot drift; the research loop owns the transitions).
MOTION_STATES = frozenset(
    {"planning", "searching", "reading", "verifying", "revising", "blocked", "cancelled", "completed"}
)

#: Directives the static side may hand to the motion side (bidirectional loop).
GAP_MISSING_EVIDENCE = "missing_evidence"
GAP_UNREAD_ATTACHMENT = "unread_attachment"
GAP_UNVERIFIED_CLAIM = "unverified_claim"
GAP_KINDS = frozenset({GAP_MISSING_EVIDENCE, GAP_UNREAD_ATTACHMENT, GAP_UNVERIFIED_CLAIM})


@dataclass(frozen=True)
class StatementState:
    reply_id: str
    kind: str
    verification: str
    lifecycle: str
    text: str
    content_version: int
    reason: str = ""
    source_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "reply_id": self.reply_id,
            "kind": self.kind,
            "verification": self.verification,
            "lifecycle": self.lifecycle,
            "text": self.text,
            "content_version": self.content_version,
            "reason": self.reason,
            "source_refs": list(self.source_refs),
        }


@dataclass(frozen=True)
class GapDirective:
    """A gap the static side asks the motion side to close."""

    kind: str
    text: str
    reply_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text, "reply_id": self.reply_id}


@dataclass(frozen=True)
class StaticAnswerSnapshot:
    run_id: str
    turn_id: str
    statements: tuple[StatementState, ...]
    conditions: tuple[str, ...]
    gaps: tuple[GapDirective, ...]
    research_state: Mapping[str, Any]
    content_version: int
    schema_version: str = "static-answer-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "statements": [item.to_dict() for item in self.statements],
            "conditions": list(self.conditions),
            "gaps": [item.to_dict() for item in self.gaps],
            "research_state": dict(self.research_state),
            "content_version": self.content_version,
        }

    def verified_statements(self) -> tuple[StatementState, ...]:
        """Only what a real read supports."""

        return tuple(
            item for item in self.current_statements() if item.verification == SUPPORTED
        )

    def current_statements(self) -> tuple[StatementState, ...]:
        """What the reader may treat as the current answer, right now.

        A statement that is not withheld, not conflicting and still current. This
        is independent of the motion state: "verifying" does not empty this list.
        """

        return tuple(
            item
            for item in self.statements
            if item.lifecycle == CURRENT
            and item.verification not in {WITHHELD, CONFLICT}
        )


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def statement_kind(reply: Mapping[str, Any]) -> str:
    stage = str(reply.get("stage") or "")
    if stage == "evidence_update":
        return "evidence"
    if stage == "analysis":
        return "conditional"
    if stage == "knowledge":
        return "knowledge"
    if stage in {"acknowledgement", ""}:
        return "unverified"
    return "knowledge"


def statement_verification(reply: Mapping[str, Any]) -> str:
    """The evidence verdict, kept strictly apart from the content kind."""

    lifecycle = str(reply.get("lifecycle") or "")
    if lifecycle in {"superseded", "retracted"}:
        return INSUFFICIENT
    if reply.get("stale") is True:
        return PENDING_VERIFICATION
    if reply.get("analysis_state") == "not_generated":
        return PENDING_VERIFICATION
    if str(reply.get("result_state") or "") == "not_included":
        # The run itself says this requirement is not in the result: it may not
        # be read as a conclusion at all.
        return WITHHELD
    citations = reply.get("citations") or []
    if citations:
        return SUPPORTED
    if str(reply.get("stage") or "") == "evidence_update":
        # A sourced judgment without a citation cannot be supported.
        return INSUFFICIENT
    return PENDING_VERIFICATION


def statement_lifecycle(reply: Mapping[str, Any]) -> str:
    lifecycle = str(reply.get("lifecycle") or "")
    if lifecycle in {"superseded", "retracted", "closed"}:
        return lifecycle
    return CURRENT


def _source_refs(reply: Mapping[str, Any]) -> tuple[str, ...]:
    refs = []
    for citation in reply.get("citations") or []:
        if isinstance(citation, Mapping) and citation.get("url"):
            refs.append(str(citation["url"]))
    return tuple(refs)


def gaps_from_statements(
    statements: Sequence[StatementState], *, attachment_present: bool = False
) -> tuple[GapDirective, ...]:
    """What the static side wants the motion side to go and check."""

    directives: list[GapDirective] = []
    seen: set[tuple[str, str]] = set()
    for item in statements:
        if item.lifecycle != CURRENT:
            continue
        if item.verification in {PENDING_VERIFICATION, INSUFFICIENT} and item.text:
            key = (item.reply_id, item.verification)
            if key not in seen:
                seen.add(key)
                directives.append(
                    GapDirective(
                        kind=GAP_MISSING_EVIDENCE
                        if item.kind in {"evidence", "conditional"}
                        else GAP_UNVERIFIED_CLAIM,
                        text=item.text[:200],
                        reply_id=item.reply_id,
                    )
                )
    if attachment_present:
        directives.append(
            GapDirective(kind=GAP_UNREAD_ATTACHMENT, text="附件未被模型读取，不能引用其中内容。")
        )
    return tuple(directives)


def snapshot_from_replies(
    replies: Iterable[Any],
    *,
    run_id: str,
    turn_id: str,
    conditions: Sequence[str] = (),
    research_state: Mapping[str, Any] | None = None,
    attachment_present: bool = False,
) -> StaticAnswerSnapshot:
    """Build the static snapshot from the provisional replies (read-only)."""

    statements: list[StatementState] = []
    for reply in replies:
        if not isinstance(reply, Mapping):
            continue
        if str(reply.get("lifecycle") or "") == "closed" and not str(reply.get("text") or "").strip():
            continue
        statements.append(
            StatementState(
                reply_id=str(reply.get("reply_id") or ""),
                kind=statement_kind(reply),
                verification=statement_verification(reply),
                lifecycle=statement_lifecycle(reply),
                text=str(reply.get("text") or ""),
                content_version=_int(reply.get("content_version")),
                reason=str(reply.get("last_revision", {}).get("reason") if isinstance(reply.get("last_revision"), Mapping) else ""),
                source_refs=_source_refs(reply),
            )
        )
    statements.sort(key=lambda item: item.reply_id)
    model_tokens = 0
    for reply in replies:
        if isinstance(reply, Mapping):
            model_tokens = max(model_tokens, _int(reply.get("content_version")))
    return StaticAnswerSnapshot(
        run_id=run_id,
        turn_id=turn_id,
        statements=tuple(statements),
        conditions=tuple(str(item) for item in conditions if str(item).strip()),
        gaps=gaps_from_statements(
            tuple(statements), attachment_present=attachment_present
        ),
        research_state=dict(research_state or {}),
        content_version=model_tokens,
    )
