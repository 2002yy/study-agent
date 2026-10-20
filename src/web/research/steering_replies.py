"""Durable, display-only provisional replies for accepted supplements.

Two reply scopes exist:

* ``steering`` - one reply per accepted supplement, bound to that message.
* ``research`` - exactly one research-level reply per run, used whenever a
  provisional judgment cannot be attributed to a single supplement.

Replies carry no evidence authority.  They never become the chat turn's
``assistant_message``, never enter ``done.reply`` and never enter formal chat
history.  Every content change advances a monotonic ``content_version`` that is
only ever allocated by a successful atomic write; two writers may not publish
different content under the same version.

Pure functions only: persistence and CAS live in the repository/service layers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

STEERING_REPLY_SCHEMA = "steering-reply-v1"

ACKNOWLEDGEMENT_TEXT = "已收到这条补充要求；评估范围将按它调整（尚未生成模型分析）。"
NOT_COVERED_TEXT = "本轮未生成模型分析：这条补充没有被本轮模型调用覆盖。"
STALE_TEXT_SUFFIX = "（尚未覆盖后续新增的条件）"
SUPERSEDED_TEXT_SUFFIX = "（这条判断已被后续纠正取代）"

LIFECYCLE_OPEN = "open"
LIFECYCLE_SUPERSEDED = "superseded"
#: The statement was withdrawn: it may not be read as a current conclusion, and
#: it is terminal for that reply like ``superseded``.
LIFECYCLE_RETRACTED = "retracted"
LIFECYCLE_CLOSED = "closed"
LIFECYCLES = (LIFECYCLE_OPEN, LIFECYCLE_SUPERSEDED, LIFECYCLE_CLOSED)

STAGE_ACKNOWLEDGEMENT = "acknowledgement"
#: A general opening from the planner: useful immediately, never presented as
#: verified, and superseded by the sourced judgment once one exists.
STAGE_KNOWLEDGE = "knowledge"
STAGE_ANALYSIS = "analysis"
STAGE_EVIDENCE = "evidence_update"

#: Later stages win, so an opening never overwrites a sourced judgment.
STAGE_RANK = {
    STAGE_ACKNOWLEDGEMENT: 0,
    STAGE_KNOWLEDGE: 1,
    STAGE_ANALYSIS: 2,
    STAGE_EVIDENCE: 3,
}
STAGES = (STAGE_ACKNOWLEDGEMENT, STAGE_ANALYSIS, STAGE_EVIDENCE)

# Bounded display sizes; nothing here is authority-bearing.
MAX_FOCUS_CHARS = 300
MAX_REASON_CHARS = 300
MAX_QUESTION_CHARS = 200
MAX_QUESTIONS = 3
MAX_TEXT_CHARS = 1200
MAX_CITATIONS = 3


def reply_id_for_steering(run_id: str, steering_id: str) -> str:
    return f"{run_id}:steer:{steering_id}"


def research_reply_id(run_id: str) -> str:
    return f"{run_id}:research"


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def acknowledgement_reply(
    *, run_id: str, steering_id: str, turn_id: str, now: str
) -> dict[str, Any]:
    """The only content that may exist before any model has seen the supplement."""
    return {
        "schema": STEERING_REPLY_SCHEMA,
        "reply_id": reply_id_for_steering(run_id, steering_id),
        "scope": "steering",
        "steering_id": steering_id,
        "turn_id": turn_id,
        "lifecycle": LIFECYCLE_OPEN,
        "stage": STAGE_ACKNOWLEDGEMENT,
        "content_version": 1,
        "content_state": {"round": 0, "notes": 0, "revision": ""},
        "stale": False,
        "analysis_state": "pending",
        "focus": "",
        "reason": "",
        "questions": [],
        "text": ACKNOWLEDGEMENT_TEXT,
        "citations": [],
        "updated_at": now,
        "timing": {"acknowledged_at": now},
    }


def research_reply(*, run_id: str, turn_id: str, now: str) -> dict[str, Any]:
    return {
        "schema": STEERING_REPLY_SCHEMA,
        "reply_id": research_reply_id(run_id),
        "scope": "research",
        "steering_id": "",
        "turn_id": turn_id,
        "lifecycle": LIFECYCLE_OPEN,
        "stage": STAGE_ACKNOWLEDGEMENT,
        "content_version": 0,
        "content_state": {"round": 0, "notes": 0, "revision": ""},
        "stale": False,
        "analysis_state": "pending",
        "focus": "",
        "reason": "",
        "questions": [],
        "text": "",
        "citations": [],
        "updated_at": now,
        "timing": {"acknowledged_at": ""},
    }


def content_fingerprint(reply: Mapping[str, Any]) -> tuple[Any, ...]:
    """Identity of one reply's *content*, used to detect same-version conflicts."""
    citations = reply.get("citations")
    return (
        str(reply.get("stage") or ""),
        str(reply.get("lifecycle") or ""),
        str(reply.get("analysis_state") or ""),
        str(reply.get("text") or ""),
        tuple(
            (str(item.get("url") or ""), str(item.get("quote") or ""))
            for item in (citations if isinstance(citations, list) else [])
            if isinstance(item, dict)
        ),
        str(reply.get("focus") or ""),
        str(reply.get("reason") or ""),
        tuple(str(item) for item in (reply.get("questions") or [])),
        bool(reply.get("stale")),
        state_key(reply),
        str((reply.get("analysis_provenance") or {}).get("revision") or "")
        if isinstance(reply.get("analysis_provenance"), Mapping)
        else "",
        str((reply.get("content_state") or {}).get("revision") or "")
        if isinstance(reply.get("content_state"), Mapping)
        else "",
    )


def content_state(*, round_index: Any, notes: int, revision: str = "") -> dict[str, Any]:
    """The research state a piece of content was derived from.

    ``content_version`` only orders writes.  Freshness must be provable from the
    research itself, so every content write records the round it was produced in,
    how many notes existed then, and (for sourced judgments) the interim
    revision it was validated against.
    """
    try:
        round_value = int(round_index or 0)
    except (TypeError, ValueError):
        round_value = 0
    return {"round": round_value, "notes": max(0, int(notes or 0)), "revision": str(revision or "")}


def advance_content(
    reply: Mapping[str, Any], *, now: str
) -> dict[str, Any]:
    """Apply one *state* change as a legitimate, version-based write.

    Bumping the version alone is not enough: a state change is written against
    the durable version it invalidates, so it must carry that version in
    ``based_on_version``. Otherwise the persistence merge sees a same-research
    write whose base is older than the durable version and refuses it as a stale
    writer - which silently loses the invalidation itself.
    """
    item = dict(reply)
    try:
        previous = int(item.get("content_version") or 0)
    except (TypeError, ValueError):
        previous = 0
    item["content_version"] = previous + 1
    item["based_on_version"] = previous
    item["updated_at"] = now
    return item


def state_key(reply: Mapping[str, Any]) -> tuple[int, int]:
    """The only provably monotone axes of a reply's research state.

    `round` and `notes` never decrease within a run, so they can order two
    contents.  The interim `revision` is a hash of the task state: it is an
    identity, never an ordering, and comparing it lexicographically would let an
    arbitrary digest decide which analysis is newer.
    """
    state = reply.get("content_state")
    if not isinstance(state, Mapping):
        return (0, 0)
    try:
        round_value = int(state.get("round") or 0)
    except (TypeError, ValueError):
        round_value = 0
    try:
        notes = int(state.get("notes") or 0)
    except (TypeError, ValueError):
        notes = 0
    return (round_value, notes)


def state_dominates(incoming: Mapping[str, Any], durable: Mapping[str, Any]) -> bool:
    """True when the incoming content is derived from at least as much research.

    Both monotone axes must be non-decreasing; anything else is a conflict to be
    reported, not an ordering to be guessed.
    """
    incoming_round, incoming_notes = state_key(incoming)
    durable_round, durable_notes = state_key(durable)
    return incoming_round >= durable_round and incoming_notes >= durable_notes


def find_reply(replies: Sequence[Any], reply_id: str) -> dict[str, Any] | None:
    for reply in replies:
        if isinstance(reply, dict) and str(reply.get("reply_id") or "") == reply_id:
            return dict(reply)
    return None


CLOSED_BY_RUN_TERMINAL = "run_terminal"

#: An accepted supplement that the final answer does not cover.
RESULT_NOT_INCLUDED = "not_included"


def bump_version(reply: Mapping[str, Any]) -> int:
    """Advance the content version for *any* change to a reply.

    The frozen contract is that every content change is monotonic in version:
    text, stale/scope flags and lifecycle all go through here, so a reader can
    never see two different states under one version.
    """
    try:
        current = int(reply.get("content_version") or 0)
    except (TypeError, ValueError):
        current = 0
    return current + 1


def next_content_version(reply: Mapping[str, Any] | None) -> int:
    try:
        current = int((reply or {}).get("content_version") or 0)
    except (TypeError, ValueError):
        current = 0
    return current + 1


def _replace(replies: Sequence[Any], updated: Mapping[str, Any]) -> list[dict[str, Any]]:
    reply_id = str(updated.get("reply_id") or "")
    kept = [
        dict(reply)
        for reply in replies
        if isinstance(reply, dict) and str(reply.get("reply_id") or "") != reply_id
    ]
    kept.append(dict(updated))
    kept.sort(key=lambda item: str(item.get("reply_id") or ""))
    return kept


def analysis_text(understanding: Mapping[str, Any]) -> str:
    """Render the model's task understanding. Never states an external fact."""
    focus = _text(understanding.get("changed_focus"), MAX_FOCUS_CHARS)
    reason = _text(understanding.get("reason_to_check"), MAX_REASON_CHARS)
    questions = [
        _text(item, MAX_QUESTION_CHARS)
        for item in (understanding.get("questions_to_verify") or [])
        if _text(item, MAX_QUESTION_CHARS)
    ][:MAX_QUESTIONS]
    parts: list[str] = []
    if focus:
        parts.append(f"评估重点变化：{focus}")
    if reason:
        parts.append(f"需要重新核查的原因：{reason}")
    if questions:
        parts.append("接下来核查：" + "；".join(questions))
    return "\n".join(parts)[:MAX_TEXT_CHARS]


def _based_on(current: Mapping[str, Any], based_on: int | None) -> int:
    """The durable version this writer had read when it produced its content.

    A same-state update must be able to prove it was written against the current
    durable version; otherwise a stale writer could still win on a higher number.
    """
    if based_on is not None:
        return int(based_on)
    try:
        return int(current.get("content_version") or 0)
    except (TypeError, ValueError):
        return 0


def apply_knowledge(
    replies: Sequence[Any],
    *,
    run_id: str,
    turn_id: str,
    text: str,
    now: str,
    version: int | None = None,
) -> list[dict[str, Any]]:
    """Publish the planner's general opening as the research reply.

    It exists so the reader gets something useful at the start of a run. It is
    replaced (never silently kept) once a sourced judgment exists, and it is
    marked stale when a later supplement changes the question.
    """

    body = _text(text, MAX_TEXT_CHARS)
    if not body:
        return [dict(reply) for reply in replies if isinstance(reply, dict)]
    reply_id = research_reply_id(run_id)
    current = find_reply(replies, reply_id)
    if current is None:
        updated = research_reply(run_id=run_id, turn_id=turn_id, now=now)
        updated["stage"] = STAGE_KNOWLEDGE
        updated["text"] = body
        updated["content_state"] = dict(content_state(round_index=0, notes=0))
        # The placeholder starts empty at version 0; publishing content is a
        # content change, so it must advance the version like any other.
        updated["content_version"] = next_content_version(updated)
        updated["based_on_version"] = 0
        return [dict(reply) for reply in replies if isinstance(reply, dict)] + [updated]
    if current.get("lifecycle") != LIFECYCLE_OPEN:
        return [dict(reply) for reply in replies if isinstance(reply, dict)]
    if STAGE_RANK.get(str(current.get("stage") or ""), 0) > STAGE_RANK[STAGE_KNOWLEDGE]:
        # A sourced judgment or a task understanding already exists: the opening
        # must not replace it.
        return [dict(reply) for reply in replies if isinstance(reply, dict)]
    updated = {
        **current,
        "stage": STAGE_KNOWLEDGE,
        "content_version": version if version is not None else next_content_version(current),
        "text": body,
        "analysis_state": "pending",
        "updated_at": now,
        "based_on_version": int(current.get("content_version") or 0),
        "timing": {**(current.get("timing") or {}), "knowledge_at": now},
    }
    return _replace(replies, updated)


def apply_analysis(
    replies: Sequence[Any],
    *,
    reply_id: str,
    understanding: Mapping[str, Any],
    now: str,
    version: int,
    state: Mapping[str, Any] | None = None,
    based_on: int | None = None,
) -> list[dict[str, Any]]:
    """Attach one model understanding to its reply (stage ``analysis``)."""
    current = find_reply(replies, reply_id)
    if current is None:
        return [dict(reply) for reply in replies if isinstance(reply, dict)]
    if current.get("lifecycle") != LIFECYCLE_OPEN:
        return [dict(reply) for reply in replies if isinstance(reply, dict)]
    text = analysis_text(understanding)
    if not text:
        return [dict(reply) for reply in replies if isinstance(reply, dict)]
    # A sourced judgment that already exists is never downgraded or erased: the
    # task understanding is stored beside it, and the stage only moves forward.
    has_evidence = current.get("stage") == STAGE_EVIDENCE
    understanding_state = dict(state or {})
    updated = {
        **current,
        "stage": STAGE_EVIDENCE if has_evidence else STAGE_ANALYSIS,
        "content_version": version,
        # G1 and G2 provenance are kept apart: when a sourced judgment already
        # exists, its round/notes/revision describe where the *evidence* came
        # from and must not be replaced by a later task understanding.
        "content_state": (
            dict(current.get("content_state") or {})
            if has_evidence
            else understanding_state
        ),
        "analysis_provenance": understanding_state,
        "analysis_state": "ready",
        "focus": _text(understanding.get("changed_focus"), MAX_FOCUS_CHARS),
        "reason": _text(understanding.get("reason_to_check"), MAX_REASON_CHARS),
        "questions": [
            _text(item, MAX_QUESTION_CHARS)
            for item in (understanding.get("questions_to_verify") or [])
            if _text(item, MAX_QUESTION_CHARS)
        ][:MAX_QUESTIONS],
        "text": current.get("text") if has_evidence else text,
        "citations": current.get("citations") if has_evidence else [],
        "updated_at": now,
        "based_on_version": _based_on(current, based_on),
        "timing": {**(current.get("timing") or {}), "analysis_at": now},
    }
    return _replace(replies, updated)


def apply_evidence(
    replies: Sequence[Any],
    *,
    reply_id: str,
    analysis: Mapping[str, Any],
    now: str,
    version: int,
    state: Mapping[str, Any] | None = None,
    based_on: int | None = None,
) -> list[dict[str, Any]]:
    """Attach one sourced provisional judgment (stage ``evidence_update``)."""
    current = find_reply(replies, reply_id)
    if current is None:
        return [dict(reply) for reply in replies if isinstance(reply, dict)]
    if current.get("lifecycle") != LIFECYCLE_OPEN:
        return [dict(reply) for reply in replies if isinstance(reply, dict)]
    text = _text(analysis.get("text"), MAX_TEXT_CHARS)
    if not text:
        return [dict(reply) for reply in replies if isinstance(reply, dict)]
    citations = [
        dict(item)
        for item in (analysis.get("citations") or [])
        if isinstance(item, dict)
    ][:MAX_CITATIONS]
    updated = {
        **current,
        "stage": STAGE_EVIDENCE,
        "content_version": version,
        "content_state": dict(state or current.get("content_state") or {}),
        "stale": False,
        "text": text,
        "citations": citations,
        "updated_at": now,
        "based_on_version": _based_on(current, based_on),
        "timing": {**(current.get("timing") or {}), "evidence_at": now},
    }
    return _replace(replies, updated)


def mark_result_not_included(
    replies: Sequence[Any], *, reply_id: str, now: str
) -> list[dict[str, Any]]:
    """Record that an accepted supplement was not part of the final research result.

    "No model analysis was generated" and "this requirement was not covered by
    the answer" are different facts: a run can produce an answer that simply does
    not include a requirement it accepted too late to execute. The second one has
    to be stated, or the reader would take the answer as complete.
    """
    current = find_reply(replies, reply_id)
    if current is None or current.get("result_state") == RESULT_NOT_INCLUDED:
        return [dict(reply) for reply in replies if isinstance(reply, dict)]
    updated = {**current, "result_state": RESULT_NOT_INCLUDED}
    updated = advance_content(updated, now=now)
    return _replace(replies, updated)


def mark_analysis_not_covered(
    replies: Sequence[Any], *, reply_id: str, now: str, version: int | None = None
) -> list[dict[str, Any]]:
    """An accepted supplement the model call did not cover stays visible.

    "No task understanding was generated" is *state*, not content: a sourced
    judgment that already exists keeps its text and citations, and the missing
    analysis is reported through ``analysis_state`` alone.
    """
    current = find_reply(replies, reply_id)
    if current is None or current.get("lifecycle") != LIFECYCLE_OPEN:
        return [dict(reply) for reply in replies if isinstance(reply, dict)]
    if current.get("analysis_state") == "ready":
        return [dict(reply) for reply in replies if isinstance(reply, dict)]
    has_evidence = current.get("stage") == STAGE_EVIDENCE
    updated = {
        **current,
        "analysis_state": "not_generated",
        "text": current.get("text") if has_evidence else NOT_COVERED_TEXT,
        "timing": {**(current.get("timing") or {}), "not_covered_at": now},
    }
    if version is None:
        updated = advance_content(updated, now=now)
    else:
        updated["content_version"] = version
        updated["based_on_version"] = int(current.get("content_version") or 0)
        updated["updated_at"] = now
    return _replace(replies, updated)


def mark_additions_stale(
    replies: Sequence[Any], *, keep_reply_id: str, added_round: int, now: str
) -> list[dict[str, Any]]:
    """One additive supplement marks only judgments older than its own round.

    Passing the round it was incorporated in is what keeps history from being
    replayed: an earlier addition must never mark a later one as stale, and
    processing A then B must not make A and B invalidate each other.
    """
    updated: list[dict[str, Any]] = []
    for reply in replies:
        if not isinstance(reply, dict):
            continue
        item = dict(reply)
        if (
            str(item.get("reply_id") or "") != keep_reply_id
            and item.get("lifecycle") == LIFECYCLE_OPEN
            and item.get("stage") in {STAGE_KNOWLEDGE, STAGE_ANALYSIS, STAGE_EVIDENCE}
            and not item.get("stale")
            and state_key(item)[0] < int(added_round or 0)
        ):
            item["stale"] = True
            if not str(item.get("text") or "").endswith(STALE_TEXT_SUFFIX):
                item["text"] = f"{item.get('text') or ''}{STALE_TEXT_SUFFIX}"[:MAX_TEXT_CHARS]
            item = advance_content(item, now=now)
        updated.append(item)
    return updated


def supersede_affected(
    replies: Sequence[Any], *, old_terms: Sequence[str], now: str
) -> list[dict[str, Any]]:
    """Only genuinely superseded judgments are invalidated.

    ``old_terms`` are the terms a correction replaced; a reply that speaks about
    them no longer describes the current task.
    """
    terms = [term.casefold() for term in old_terms if str(term).strip()]
    if not terms:
        return [dict(reply) for reply in replies if isinstance(reply, dict)]
    updated: list[dict[str, Any]] = []
    for reply in replies:
        if not isinstance(reply, dict):
            continue
        item = dict(reply)
        haystack = " ".join(
            [
                str(item.get("text") or ""),
                str(item.get("focus") or ""),
                str(item.get("reason") or ""),
                " ".join(str(question) for question in (item.get("questions") or [])),
            ]
        ).casefold()
        if item.get("lifecycle") == LIFECYCLE_OPEN and any(term in haystack for term in terms):
            item["lifecycle"] = LIFECYCLE_SUPERSEDED
            item["stale"] = True
            if not str(item.get("text") or "").endswith(SUPERSEDED_TEXT_SUFFIX):
                item["text"] = f"{item.get('text') or ''}{SUPERSEDED_TEXT_SUFFIX}"[:MAX_TEXT_CHARS]
            item = advance_content(item, now=now)
        updated.append(item)
    return updated


def close_replies(
    replies: Sequence[Any],
    *,
    now: str,
    closed_by: str = CLOSED_BY_RUN_TERMINAL,
    run_status: str = "",
) -> list[dict[str, Any]]:
    """Freeze replies because the *authoritative* research run reached a terminal state.

    The provenance is recorded so a merge can tell an authoritative freeze from a
    writer merely claiming that a reply should be closed.
    """
    updated: list[dict[str, Any]] = []
    for reply in replies:
        if not isinstance(reply, dict):
            continue
        item = dict(reply)
        if item.get("lifecycle") == LIFECYCLE_OPEN:
            item["lifecycle"] = LIFECYCLE_CLOSED
            item["lifecycle_closed_by"] = closed_by
            item["closed_run_status"] = str(run_status or "")
            item["timing"] = {**(item.get("timing") or {}), "closed_at": now}
            item = advance_content(item, now=now)
        updated.append(item)
    return updated


def attribute_analysis(
    analysis: Mapping[str, Any],
    *,
    plan: Sequence[Any],
    entry: Mapping[str, Any],
) -> bool:
    """True only when every citation was read for a task this supplement created.

    Task association alone is not causal evidence: the material must also have
    been read *after* the supplement entered the plan.  Anything weaker belongs
    to the research-level reply instead.
    """
    incorporated = entry.get("incorporated_in_round")
    if not isinstance(incorporated, int):
        return False
    entry_id = str(entry.get("id") or "")
    if not entry_id:
        return False
    questions: set[str] = set()
    for task in plan if isinstance(plan, list) else []:
        if not isinstance(task, dict) or task.get("status") in {"superseded", "cancelled"}:
            continue
        ids = [str(value) for value in task.get("steering_ids") or []]
        # Only the creator of the task may claim the material as this
        # supplement's finding; a task that merely gained the id predates it.
        if not ids or ids[0] != entry_id:
            continue
        question = " ".join(str(task.get("sub_question") or "").split())[:160]
        if question:
            questions.add(question)
    if not questions:
        return False
    citations = [
        item for item in (analysis.get("citations") or []) if isinstance(item, dict)
    ]
    if not citations:
        return False
    for citation in citations:
        question = " ".join(str(citation.get("question") or "").split())[:160]
        if question not in questions:
            return False
        read_round = citation.get("round")
        if not isinstance(read_round, int) or read_round < incorporated:
            return False
    return True


def reply_projection(
    context: Mapping[str, Any], *, run_id: str, turn_id: str, active: bool
) -> list[dict[str, Any]]:
    """Read-only projection; a terminal run always reads as closed."""
    replies = context.get("steering_replies")
    projected: list[dict[str, Any]] = []
    for reply in replies if isinstance(replies, list) else []:
        if not isinstance(reply, dict) or reply.get("schema") != STEERING_REPLY_SCHEMA:
            continue
        item = dict(reply)
        if not item.get("turn_id"):
            item["turn_id"] = turn_id
        if not item.get("text"):
            continue
        if not active and item.get("lifecycle") == LIFECYCLE_OPEN:
            # The projection is derived from the authoritative run row, so it
            # states that authority instead of emitting an anonymous close.
            item["lifecycle"] = LIFECYCLE_CLOSED
            item["lifecycle_closed_by"] = CLOSED_BY_RUN_TERMINAL
        projected.append(item)
    projected.sort(key=lambda item: str(item.get("reply_id") or ""))
    return projected


def _flagged_conflict(
    durable: Mapping[str, Any], incoming: Mapping[str, Any], *, reason: str
) -> dict[str, Any]:
    """Keep the authoritative content and make the refused write detectable.

    A conflicting write is never applied, but it must not vanish either: the
    durable reply records how many writes it refused and the last one's stage, so
    an operator can see that a writer lost a race instead of assuming silence.
    """
    kept = dict(durable)
    try:
        refused = int(kept.get("conflicts_refused") or 0)
    except (TypeError, ValueError):
        refused = 0
    kept["conflicts_refused"] = refused + 1
    kept["last_conflict"] = {
        "reason": reason,
        "stage": str(incoming.get("stage") or ""),
        "content_version": int(incoming.get("content_version") or 0),
        "at": str(incoming.get("updated_at") or ""),
    }
    return kept


def merge_steering_replies(
    incoming: Mapping[str, Any], durable: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge the ``steering_replies`` section of two context snapshots.

    A checkpoint written by the research executor must never erase a reply the
    API thread just persisted.  Freshness is decided by the **research state**
    each content was derived from (round, notes, interim revision), never by the
    write order alone: a stale writer cannot promote its older analysis by
    carrying a higher ``content_version``.  When two writers produced different
    content from the same state, the first successful atomic write is
    authoritative and the loser is dropped instead of overwriting silently.
    """
    updated = dict(incoming)
    merged: dict[str, dict[str, Any]] = {}
    for reply in durable.get("steering_replies") or []:
        if isinstance(reply, dict) and reply.get("reply_id"):
            merged[str(reply["reply_id"])] = dict(reply)
    for reply in incoming.get("steering_replies") or []:
        if not isinstance(reply, dict) or not reply.get("reply_id"):
            continue
        key = str(reply["reply_id"])
        prior = merged.get(key)
        if prior is None:
            merged[key] = dict(reply)
            continue
        # An invalidation is one-way. A reply the run already superseded must not
        # be revived by a writer that still holds an older "open" snapshot, however
        # new its research round claims to be: `open -> superseded` has no reverse.
        # The lifecycle is authority, so it is protected before any state or
        # version comparison - a newer round may replace content, never the fact
        # that this judgment was invalidated.
        prior_lifecycle = prior.get("lifecycle")
        if prior_lifecycle in {LIFECYCLE_SUPERSEDED, LIFECYCLE_RETRACTED}:
            # A withdrawn statement is history: a late writer cannot revive it,
            # and its body is frozen so the two layers cannot disagree.
            if reply.get("lifecycle") != prior_lifecycle:
                merged[key] = _flagged_conflict(
                    prior, reply, reason=f"{prior_lifecycle}_reopen"
                )
            elif content_fingerprint(reply) != content_fingerprint(prior):
                merged[key] = _flagged_conflict(
                    prior, reply, reason=f"{prior_lifecycle}_immutable"
                )
            continue
        # A freeze is only authoritative when it came from the research run's
        # terminal state, never when a writer merely claims the reply is closed.
        # A durable freeze counts only when it came from the run's terminal
        # state. A stored "closed" without that provenance is not a state we may
        # keep, or an illegitimate close would be permanent.
        prior_closed = (
            prior.get("lifecycle") == LIFECYCLE_CLOSED
            and prior.get("lifecycle_closed_by") == CLOSED_BY_RUN_TERMINAL
        )
        incoming_closed = (
            reply.get("lifecycle") == LIFECYCLE_CLOSED
            and reply.get("lifecycle_closed_by") == CLOSED_BY_RUN_TERMINAL
        )
        if prior_closed and not incoming_closed:
            continue
        if incoming_closed and not prior_closed:
            merged[key] = dict(reply)
            continue
        if not incoming_closed and reply.get("lifecycle") == LIFECYCLE_CLOSED:
            # A non-authoritative "closed" claim is ignored entirely.
            continue
        prior_version = int(prior.get("content_version") or 0)
        version = int(reply.get("content_version") or 0)
        if content_fingerprint(reply) == content_fingerprint(prior):
            # Identical content: nothing to do.
            continue
        dominates = state_dominates(reply, prior)
        strictly_newer_state = dominates and state_key(reply) != state_key(prior)
        if version > prior_version and strictly_newer_state:
            # A later write of provably more research: accept it.
            merged[key] = dict(reply)
            continue
        if version > prior_version and dominates:
            # Same research state: accept only a write that was produced against
            # the current durable version, so a stale snapshot cannot win on its
            # number alone.
            try:
                based_on = int(reply.get("based_on_version") or 0)
            except (TypeError, ValueError):
                based_on = 0
            if based_on >= prior_version:
                merged[key] = dict(reply)
            else:
                merged[key] = _flagged_conflict(prior, reply, reason="stale_base")
            continue
        if strictly_newer_state:
            # The write order does not advance, but the research state provably
            # does: publish under a version that cannot collide with the durable
            # one, and record the race so a lost write stays auditable.
            renumbered = dict(reply)
            renumbered["content_version"] = prior_version + 1
            renumbered["last_conflict"] = {
                "reason": "same_version_race",
                "stage": str(reply.get("stage") or ""),
                "content_version": version,
                "at": str(reply.get("updated_at") or ""),
            }
            merged[key] = renumbered
            continue
        # Older research state, or a stale write of the same state: refuse it and
        # keep the refusal visible instead of dropping it silently.
        merged[key] = _flagged_conflict(
            prior, reply, reason="older_state" if not dominates else "stale_write"
        )
    if merged:
        updated["steering_replies"] = sorted(
            merged.values(), key=lambda item: str(item.get("reply_id") or "")
        )
    return updated
