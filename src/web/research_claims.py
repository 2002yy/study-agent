"""A. Claim extraction: read bodies -> goal-level candidate claims WITH citations.

The model proposes; the run disposes. Candidate windows are chosen deterministically from
the notebook's own cached bodies, and the model may only cite a ``source_id`` this run has
registered. A free-form URL in the model's output is ignored, so a third party can never
become evidence by writing a link.

One batched call per run: the prompt carries every unfinished goal and its windows.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

MAX_WINDOWS_PER_GOAL = 2
WINDOW_CHARS = 420
MAX_CLAIMS = 8

_SYSTEM = (
    "You extract CANDIDATE claims from research passages. For each goal, if the passage "
    "states something that answers it, output a short claim plus the exact passage span it "
    "comes from. Cite ONLY the provided source_id values; never invent a URL. If a passage "
    "does not answer the goal, output no claim for it. Reply with JSON only: "
    '{"claims":[{"goal_id":"...","source_id":"...","claim":"...","quote":"..."}]}'
)


@dataclass(frozen=True)
class Claim:
    """A candidate conclusion tied to a registered source and a span inside its text."""

    goal_id: str
    claim: str
    source_id: str
    span_start: int
    span_end: int
    quote: str = ""


def _window(text: str, terms: tuple[str, ...]) -> dict[str, Any] | None:
    lowered = text.lower()
    for term in terms:
        position = lowered.find(str(term).lower())
        if position < 0:
            continue
        start = max(0, position - WINDOW_CHARS // 2)
        end = min(len(text), start + WINDOW_CHARS)
        return {"span_start": start, "span_end": end, "excerpt": text[start:end]}
    return None


def candidate_windows(goal_terms: tuple[str, ...], bodies: Mapping[str, Any], *,
                      limit: int = MAX_WINDOWS_PER_GOAL) -> list[dict[str, Any]]:
    """Deterministic windows that mention the goal's own terms (for the candidate prompt)."""
    windows: list[dict[str, Any]] = []
    for source_id, body in bodies.items():
        found = _window(body.text, goal_terms)
        if found is None:
            continue
        windows.append({"source_id": source_id, **found})
        if len(windows) >= limit:
            break
    return windows


def _locate_loose(text: str, quote: str) -> tuple[int, int]:
    """Locate a quote that differs only by whitespace/width; spans are still raw offsets.

    The model may reflow or re-space a passage it really did read. Matching on the
    whitespace-stripped characters keeps the anti-fabrication property (every character
    must appear, in order, contiguously) without failing on formatting alone.
    """
    index: list[int] = []
    characters: list[str] = []
    for position, char in enumerate(text):
        if char.isspace():
            continue
        characters.append(char)
        index.append(position)
    needle = re.sub(r"\s+", "", quote)
    if not needle or not characters:
        return -1, -1
    found = "".join(characters).find(needle)
    if found < 0:
        return -1, -1
    return index[found], index[found + len(needle) - 1] + 1


def _valid_claim(raw: Mapping[str, Any], *, goal_ids: set[str],
                 bodies: Mapping[str, Any], goals: Mapping[str, tuple[str, ...]],
                 on_reject: Callable[[str], None] | None = None) -> Claim | None:
    """Accept only a claim that cites a registered source and a usable span."""
    def reject(reason: str) -> None:
        if on_reject is not None:
            on_reject(reason)

    goal_id = str(raw.get("goal_id") or "")
    source_id = str(raw.get("source_id") or "")
    claim = str(raw.get("claim") or "").strip()
    if goal_id not in goal_ids or source_id not in bodies:
        reject("unknown_goal_or_source")   # an invented source or goal can never be cited
        return None
    if not claim:
        reject("empty_claim")
        return None
    body = bodies[source_id]
    text = body.text
    quote = str(raw.get("quote") or "").strip()
    if not quote:
        # A claim without a locatable quote is not accepted: falling back to the keyword
        # window would let a phrase the model never quoted pass as its citation.
        reject("quote_missing")
        return None
    span_start, span_end = -1, -1
    position = text.find(quote)
    if position >= 0:
        span_start, span_end = position, position + len(quote)
    else:
        span_start, span_end = _locate_loose(text, quote)
    if span_start < 0:
        reject("quote_not_found")
        return None
    if not (0 <= span_start < span_end <= len(text)):
        reject("span_out_of_range")
        return None
    # the cited span must actually mention the goal's terms - otherwise it is not evidence
    span_text = text[span_start:span_end].lower()
    if not any(term and str(term).lower() in span_text for term in goals.get(goal_id, ())):
        reject("span_misses_goal_terms")
        return None
    # a URL in the model's output is dropped: only registered sources are citable
    claim = re.sub(r"https?://\S+", "", claim).strip()
    return Claim(goal_id=goal_id, claim=claim, source_id=source_id,
                 span_start=span_start, span_end=span_end, quote=quote)


def extract_claims(*, goals: Mapping[str, tuple[str, ...]], bodies: Mapping[str, Any],
                   completion: Callable[..., str], timeout: float = 20.0,
                   on_call: Callable[[], None] | None = None,
                   on_reject: Callable[[str], None] | None = None) -> list[Claim]:
    """One batched extraction over every unfinished goal. Never raises on bad model output."""
    def reject(reason: str) -> None:
        if on_reject is not None:
            on_reject(reason)

    if not goals or not bodies:
        return []
    payload = {
        "goals": [{"goal_id": goal_id, "goal": goal_id,
                   "passages": candidate_windows(terms, bodies)}
                  for goal_id, terms in goals.items()],
        "rules": "cite only the given source_id; a claim without a passage is not allowed",
    }
    if on_call is not None:
        on_call()                      # the caller counts a REAL model call, never a guess
    try:
        raw = completion(
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            timeout=timeout, task_name="research_claims")
    except Exception:  # noqa: BLE001 - extraction failure must not break the run
        reject("call_failed")
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        reject("unparseable_output")
        return []
    rows = (data or {}).get("claims") if isinstance(data, dict) else None
    if not rows:
        reject("no_claims_returned")
    claims: list[Claim] = []
    for row in (rows or [])[:MAX_CLAIMS]:
        if not isinstance(row, Mapping):
            reject("malformed_row")
            continue
        claim = _valid_claim(row, goal_ids=set(goals), bodies=bodies, goals=goals,
                             on_reject=on_reject)
        if claim is not None:
            claims.append(claim)
    return claims
