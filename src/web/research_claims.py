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

from src.web.link_discovery import (PROSE_BLOCK_MIN_CHARS, _SENTENCE_PUNCT,
                                    looks_like_list, looks_like_navigation,
                                    prose_blocks)

MAX_WINDOWS_PER_GOAL = 2
WINDOW_CHARS = 420
MAX_CLAIMS = 8
#: A span from a goal-term-free window must still read as prose, not as a nav item.
MIN_PROSE_SPAN_CHARS = 80
#: Elision markers a model uses when it quotes a passage it read but does not copy whole.
_ELISION = re.compile(r"…+|\.{3,}|⋯+|\[\s*\.{3}\s*\]|（略）")
#: A fragment shorter than this is not evidence of anything on its own.
MIN_FRAGMENT_CHARS = 8

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
    #: Which kind of window the span came from: "term" (goal words present) or "prose".
    window_kind: str = ""
    #: True when the model's quote omitted parts of the passage with an ellipsis; every
    #: fragment still had to occur, in order, in the registered body.
    elided: bool = False
    #: Whether the cited span repeats the goal's own derived words. Recorded for audit; it is
    #: NOT a requirement, because those words are fragments of a question, not a contract.
    goal_terms_present: bool = False


def _window(text: str, terms: tuple[str, ...]) -> dict[str, Any] | None:
    lowered = text.lower()
    for term in terms:
        position = lowered.find(str(term).lower())
        if position < 0:
            continue
        start = max(0, position - WINDOW_CHARS // 2)
        end = min(len(text), start + WINDOW_CHARS)
        return {"span_start": start, "span_end": end, "excerpt": text[start:end],
                "window_kind": "term"}
    return None


def _prose_window(text: str) -> dict[str, Any] | None:
    """A prose passage for a body where the goal's own terms never appear.

    A Chinese question over an English article would otherwise hand the extractor zero
    usable windows even when the article answers it. The window is still drawn from the
    registered body, so nothing becomes citable that the run did not actually read.
    """
    blocks = sorted(prose_blocks(text), key=len, reverse=True)
    for block in blocks:
        excerpt = block[:WINDOW_CHARS]
        position = text.find(excerpt)
        if position < 0:
            excerpt = excerpt[:PROSE_BLOCK_MIN_CHARS]
            position = text.find(excerpt)
        if position >= 0:
            return {"span_start": position, "span_end": position + len(excerpt),
                    "excerpt": excerpt, "window_kind": "prose"}
    return None


def candidate_windows(goal_terms: tuple[str, ...], bodies: Mapping[str, Any], *,
                      limit: int = MAX_WINDOWS_PER_GOAL) -> list[dict[str, Any]]:
    """Windows for the candidate prompt, best-first: goal-term hits, then prose.

    Order matters: with several bodies in hand the model must be shown the passages most
    likely to answer THIS goal. Term windows (the goal's own words) outrank prose windows,
    and among term windows the body mentioning more of the goal's terms comes first.
    """
    terms = [str(term).lower() for term in goal_terms if str(term)]
    ranked: list[tuple[int, int, int, str, dict[str, Any]]] = []
    for source_id, body in bodies.items():
        text = body.text or ""
        lowered = text.lower()
        hits = sum(1 for term in terms if term in lowered)
        quality = getattr(body, "quality", None) or {}
        prose = int(quality.get("prose_chars", 0) or 0)
        term_window = _window(text, goal_terms)
        prose_window = _prose_window(text)
        for rank, window in ((3, term_window), (2, prose_window)):
            if window is None:
                continue
            excerpt = str(window.get("excerpt") or "")
            # An index or item-list passage is not material for a claim even when the goal's
            # words appear in it: showing it invites an empty answer. Fall through to the
            # body's prose window instead of dropping the body.
            if looks_like_navigation(excerpt) or looks_like_list(excerpt):
                continue
            if rank == 3 and not (bool(_SENTENCE_PUNCT.search(excerpt))
                                  and len(excerpt) >= 60):
                rank = 1     # a term that only occurs in a caption or a label
            ranked.append((rank, hits, prose, source_id, window))
            break
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [{"source_id": source_id, **window}
            for _rank, _hits, _prose, source_id, window in ranked[:limit]]


def _find_from(text: str, fragment: str, cursor: int = 0) -> tuple[int, int]:
    """Find a fragment from ``cursor``: exact first, then whitespace-insensitive."""
    found = text.find(fragment, cursor)
    if found >= 0:
        return found, found + len(fragment)
    index: list[int] = []
    characters: list[str] = []
    for position in range(cursor, len(text)):
        char = text[position]
        if char.isspace():
            continue
        characters.append(char)
        index.append(position)
    needle = re.sub(r"\s+", "", fragment)
    if not needle or not characters:
        return -1, -1
    at = "".join(characters).find(needle)
    if at < 0:
        return -1, -1
    return index[at], index[at + len(needle) - 1] + 1


def _locate_loose(text: str, quote: str) -> tuple[int, int]:
    """Locate a quote that differs only by whitespace/width; spans are still raw offsets.

    The model may reflow or re-space a passage it really did read. Matching on the
    whitespace-stripped characters keeps the anti-fabrication property (every character
    must appear, in order, contiguously) without failing on formatting alone.
    """
    if not re.sub(r"\s+", "", quote):
        return -1, -1
    return _find_from(text, quote, 0)


def _locate_elided(text: str, quote: str) -> tuple[int, int]:
    """Locate a quote that ELIDES parts of a passage with an ellipsis.

    Models commonly write "… A … B" when they mean "this passage says A and B". That is
    acceptable evidence: every fragment must occur in the registered body (verbatim, or
    differing only by whitespace) and IN ORDER, so the model may omit text but never invent
    it. The span covers the whole range from the first fragment to the last.
    """
    fragments = [fragment.strip() for fragment in _ELISION.split(quote)]
    fragments = [fragment for fragment in fragments if len(fragment) >= MIN_FRAGMENT_CHARS]
    if len(fragments) < 2:
        return -1, -1              # a single fragment is ordinary matching, not elision
    cursor = 0
    start, end = -1, -1
    for fragment in fragments:
        found, stop = _find_from(text, fragment, cursor)
        if found < 0:
            return -1, -1
        if start < 0:
            start = found
        end = max(end, stop)
        cursor = stop
    return start, end


def locate_quote(text: str, quote: str) -> tuple[int, int, bool]:
    """Locate a quote in a body: exact, then whitespace-reflowed, then elided.

    The single locator both the extractor and the verifier use, so a passage the model
    legitimately quoted (perhaps with an ellipsis, perhaps respaced) is never judged
    "unlocatable" by one stage after the other accepted it. Returns (start, end, elided).
    """
    if not quote:
        return -1, -1, False
    position = text.find(quote)
    if position >= 0:
        return position, position + len(quote), False
    start, end = _locate_loose(text, quote)
    if start >= 0:
        return start, end, False
    start, end = _locate_elided(text, quote)
    return (start, end, True) if start >= 0 else (-1, -1, False)


def _valid_claim(raw: Mapping[str, Any], *, goal_ids: set[str],
                 bodies: Mapping[str, Any], goals: Mapping[str, tuple[str, ...]],
                 windows: Mapping[str, list[dict[str, Any]]] | None = None,
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
    elided = False
    span_start, span_end, elided = locate_quote(text, quote)
    if span_start < 0:
        reject("quote_not_found")
        return None
    if not (0 <= span_start < span_end <= len(text)):
        reject("span_out_of_range")
        return None
    span_text = text[span_start:span_end]
    # The span must sit inside a window the model was actually shown: that ties the citation
    # to a passage this run chose, and keeps the check language-agnostic.
    shown = list((windows or {}).get(source_id) or [])
    inside = [w for w in shown
              if int(w.get("span_start", -1)) <= span_start and span_end <= int(w.get("span_end", -1))]
    if shown and not inside:
        reject("span_outside_windows")
        return None
    if not shown and not _SENTENCE_PUNCT.search(span_text) \
            and len(span_text.strip()) < MIN_PROSE_SPAN_CHARS:
        # With no window to anchor to, the span itself must at least read as prose.
        reject("span_not_prose")
        return None
    kinds = {str(w.get("window_kind") or "term") for w in inside} or {"term"}
    # Whether the span repeats the goal's own derived words is RECORDED, not required: those
    # words are fragments of a question ("么代", "何避" for a Chinese one), and demanding them
    # would throw away a claim that answers the goal from a passage this run selected itself.
    goal_terms_present = any(term and str(term).lower() in span_text.lower()
                             for term in goals.get(goal_id, ()))
    # a URL in the model's output is dropped: only registered sources are citable
    claim = re.sub(r"https?://\S+", "", claim).strip()
    return Claim(goal_id=goal_id, claim=claim, source_id=source_id,
                 span_start=span_start, span_end=span_end, quote=quote,
                 window_kind="prose" if kinds == {"prose"} else "term", elided=elided,
                 goal_terms_present=goal_terms_present)


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
    windows_by_goal: dict[str, list[dict[str, Any]]] = {
        goal_id: candidate_windows(terms, bodies) for goal_id, terms in goals.items()}
    payload: dict[str, Any] = {
        "goals": [{"goal_id": goal_id, "goal": goal_id, "passages": windows_by_goal[goal_id]}
                  for goal_id in goals],
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
    windows_by_source: dict[str, list[dict[str, Any]]] = {}
    for windows in windows_by_goal.values():
        for window in windows:
            windows_by_source.setdefault(str(window["source_id"]), []).append(window)
    claims: list[Claim] = []
    for row in (rows or [])[:MAX_CLAIMS]:
        if not isinstance(row, Mapping):
            reject("malformed_row")
            continue
        claim = _valid_claim(row, goal_ids=set(goals), bodies=bodies, goals=goals,
                             windows=windows_by_source, on_reject=on_reject)
        if claim is not None:
            claims.append(claim)
    return claims
