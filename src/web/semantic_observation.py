"""CL-M3 M3-QB: projecting execution observations back into the planning episode.

Implements §7.2 ("observation write-back") and Q-9 ("stop conditions matter as much as
searching") of ``docs/CL_M3_CAPABILITY_CONTRACT.md``.

Three rules shape this module.

**A projection, not a log.** ``attempts`` and ``source_leads`` are capped planning context
(8 / 5) that the planner reads, not an audit trail. The projection therefore keeps the
newest rows within the cap and never grows; the authoritative execution record stays on the
server side, where ``record_tool_trace`` already writes it.

**Legally parseable.** Every projected row must survive ``ResearchEpisode.parse``:
identical key sets and identical per-field caps. A projection that only *looks* bounded is
worse than none, because the episode becomes unpersistable at the point of failure rather
than here.

**No borrowed authority.** A read that returned ``answer_eligible`` is still only an
observation. Nothing from the executor's evidence judgement is copied into the episode -
the fourth layer of §7.1 keeps source verification and publication where they already are.

Deliberate divergence from the legacy single-round block in ``persistent_web_agent``
(553-565): that block *replaces* ``source_leads`` with the current operation's reads, which
is harmless when there is exactly one round. In a multi-round loop it would erase the
previous round's findings before the planner is asked to replan from them, and the second
round would be "observation driven" over an empty observation. Rows are therefore merged
oldest-first and truncated from the front.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Mapping

from src.web.semantic_recovery import ResearchEpisode

ATTEMPT_CAP = 8
LEAD_CAP = 5

# Mirrors the caps enforced by ``ResearchEpisode.parse``. Kept in one place so the
# projection cannot drift from the schema it has to satisfy.
ATTEMPT_FIELD_CAPS: Mapping[str, int] = {"query": 500, "outcome": 100}
LEAD_FIELD_CAPS: Mapping[str, int] = {
    "url": 500,
    "status": 100,
    "reason": 300,
    "summary": 300,
}
ATTEMPT_FIELDS = frozenset(ATTEMPT_FIELD_CAPS)
LEAD_FIELDS = frozenset(LEAD_FIELD_CAPS)

# Q-9: the four stop conditions must stay distinguishable, so they are separate values
# rather than one "stopped" bucket. ``continue`` is the absence of a stop reason.
CONTINUE = "continue"
STOP_EVIDENCE_SUFFICIENT = "evidence_sufficient"
STOP_NO_NEW_DIRECTION = "no_new_direction"
STOP_BUDGET_EXHAUSTED = "budget_exhausted"
STOP_CANCELLED = "cancelled"
STOP_REASONS = frozenset(
    {
        CONTINUE,
        STOP_EVIDENCE_SUFFICIENT,
        STOP_NO_NEW_DIRECTION,
        STOP_BUDGET_EXHAUSTED,
        STOP_CANCELLED,
    }
)
# Intents that mean "the research round is over" rather than "search again".
_CLOSING_INTENTS = frozenset({"ANSWER"})


def _clip(value: Any, cap: int) -> str:
    """Coerce to ``str`` and bound it, exactly as the parse layer would refuse otherwise."""

    text = "" if value is None else str(value)
    return text[:cap]


def _rows(
    calls: Iterable[Any], name: str, fields: Mapping[str, int]
) -> list[dict[str, str]]:
    """Extract ``fields`` from every call named ``name``, clipping each to its cap."""

    rows: list[dict[str, str]] = []
    for call in calls:
        if not isinstance(call, Mapping) or call.get("name") != name:
            continue
        arguments = call.get("arguments")
        result = call.get("result")
        arguments = arguments if isinstance(arguments, Mapping) else {}
        result = result if isinstance(result, Mapping) else {}
        rows.append(
            {field: _clip(_source(field, arguments, result), cap) for field, cap in fields.items()}
        )
    return rows


def _source(field: str, arguments: Mapping[str, Any], result: Mapping[str, Any]) -> Any:
    """Map one projected field onto the call record it comes from.

    Only literal call facts are read. ``answer_eligible`` is deliberately absent: a read
    verdict is not evidence and must not travel inside the planning episode.
    """

    if field == "query":
        return arguments.get("query", "")
    if field == "outcome":
        return result.get("status", "unknown")
    if field == "url":
        return arguments.get("url", "")
    if field == "status":
        # The executor's own execution status ("ok" / "failed" / ...). The legacy block
        # derived "related_read" from ``answer_eligible``; that verdict is evidence, not an
        # observation, so the status stays a literal execution fact and the relevance
        # judgement stays where the contract puts it.
        return result.get("status", "unknown")
    if field == "summary":
        return result.get("content") or result.get("readme") or ""
    if field == "reason":
        return result.get("adequacy_reason") or result.get("error") or ""
    raise KeyError(field)


def _merge(
    previous: Iterable[Mapping[str, str]],
    fresh: Iterable[Mapping[str, str]],
    *,
    cap: int,
    caps: Mapping[str, int],
    required: str,
) -> list[dict[str, str]]:
    """Oldest-first merge, de-duplicated on the full row, truncated from the front.

    A row without its identifying field (``query`` for an attempt, ``url`` for a lead) is
    not an observation at all, so it is dropped rather than stored as a blank entry that
    would consume one of the eight or five slots.
    """

    merged: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()
    for row in [*previous, *fresh]:
        if not isinstance(row, Mapping):
            continue
        normalised = {name: _clip(row.get(name, ""), limit) for name, limit in caps.items()}
        if not normalised[required]:
            continue
        key = tuple(normalised[name] for name in sorted(caps))
        if key in seen:
            continue
        seen.add(key)
        merged.append(normalised)
    return merged[-cap:]


def project_attempts(
    previous: Iterable[Mapping[str, str]], calls: Iterable[Any]
) -> list[dict[str, str]]:
    """Search queries this round actually issued, merged with the ones already recorded."""

    fresh = _rows(calls, "web_search", ATTEMPT_FIELD_CAPS)
    return _merge(previous, fresh, cap=ATTEMPT_CAP, caps=ATTEMPT_FIELD_CAPS, required="query")


def project_leads(
    previous: Iterable[Mapping[str, str]],
    calls: Iterable[Any],
    *,
    is_public_url: Any,
) -> list[dict[str, str]]:
    """Public reads only.

    ``is_public_url`` is injected rather than imported so that this module makes no claim
    about which URLs are acceptable; the caller keeps using the same predicate the rest of
    the chain uses, and a private/local URL never enters the planning context.
    """

    fresh = [
        row
        for row in _rows(calls, "web_read", LEAD_FIELD_CAPS)
        if row["url"] and is_public_url(row["url"])
    ]
    for row in fresh:
        row["status"] = row["status"] or "unclassified"
    return _merge(previous, fresh, cap=LEAD_CAP, caps=LEAD_FIELD_CAPS, required="url")


def absorb(
    episode: ResearchEpisode,
    calls: Iterable[Any],
    *,
    is_public_url: Any,
) -> ResearchEpisode:
    """Return the episode with this round's observations folded in.

    The result is a *new* episode; the caller keeps ownership of when to persist it.
    """

    materialised = list(calls)
    return replace(
        episode,
        attempts=project_attempts(episode.attempts, materialised),
        source_leads=project_leads(episode.source_leads, materialised, is_public_url=is_public_url),
    )


def new_lead_urls(
    before: Iterable[Mapping[str, str]], after: Iterable[Mapping[str, str]]
) -> set[str]:
    """URLs the round added, used to tell "found something new" from "went in circles"."""

    return {str(row.get("url", "")) for row in after} - {
        str(row.get("url", "")) for row in before
    }


def next_phase(
    *,
    cancelled: bool,
    budget_remaining: int,
    new_leads: int,
    model_intent: str,
) -> str:
    """The one place that decides whether the loop continues or stops, and why.

    Order is deliberate. A user's cancellation outranks everything, because continuing to
    spend against an explicit cancel is the one mistake that cannot be undone. Budget comes
    next: Q-10 makes overrun a billing fact, not a preference. Only then does the model's
    own intent count, because §7.1 layer three gives *the model* the sufficiency judgement
    and this function is not allowed to invent one. ``no_new_direction`` is the mechanical
    last resort: another round that found nothing new is a loop, and Q-9 forbids that.
    """

    if cancelled:
        return STOP_CANCELLED
    if budget_remaining <= 0:
        return STOP_BUDGET_EXHAUSTED
    if model_intent in _CLOSING_INTENTS:
        return STOP_EVIDENCE_SUFFICIENT
    if new_leads <= 0:
        return STOP_NO_NEW_DIRECTION
    return CONTINUE
