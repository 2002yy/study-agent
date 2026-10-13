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
from typing import Any, Callable, Mapping, Sequence

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


def _prose_score(excerpt: str) -> int:
    """How much a passage reads like an explanation rather than a label or a list."""
    return len(excerpt) if _SENTENCE_PUNCT.search(excerpt) else 0


def _window(text: str, terms: tuple[str, ...]) -> dict[str, Any] | None:
    """The passage around the first goal term the body states."""
    lowered = text.lower()
    for term in terms:
        needle = str(term).lower()
        if not needle:
            continue
        position = lowered.find(needle)
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


_GENERIC_SUBJECT_TOKENS = {"如何", "什么", "为什么", "区别", "代价", "机制", "原理", "是什么",
                           "带来", "避免", "互相", "上的", "哪些", "怎么", "多少", "何时",
                           "the", "and", "for", "with", "what", "why", "how"}
_RELATION_MARKERS = ("因为", "因此", "所以", "由于", "导致", "从而", "使得", "相比", "不同",
                     "区别", "而是", "并不", "不会", "需要", "通过", "依赖", "实现", "基于",
                     "而非", "如果", "若", "除非", "无法", "不能", "只有当", "仅当", "则", "才")
# Behavioural verbs: what a subject DOES. A sole copula ("是") is deliberately absent, so an
# abstract statement such as "MVCC 是一个概念，很重要" cannot pass the candidate filter.
_BEHAVIOUR_MARKERS = ("会", "可以", "可", "能", "用于", "使用", "由", "称为", "属于",
                      "包括", "分为", "具有")
_INHERIT_MARKERS = ("其", "该", "它", "此", "这", "上述", "同样")
_LATIN_WORD = re.compile(r"[a-z][a-z0-9_\-]{2,}")
_QUOTED_TERM = re.compile(
    r"\u300c([^\u300d]{1,24})\u300d"       # \u300c\u300d
    r"|\u300e([^\u300f]{1,24})\u300f"     # \u300e\u300f
    r"|\u201c([^\u201d]{1,24})\u201d"     # curly double quotes
    r"|\"([^\"]{1,24})\"")                # plain ASCII double quotes


def _quoted_terms(text: str) -> list[str]:
    """Terms the question marks as its own subject by quoting them."""
    out: list[str] = []
    for match in _QUOTED_TERM.finditer(text or ""):
        term = next((group.strip() for group in match.groups() if group), "")
        if term and term not in out:
            out.append(term)
    return out


def _goal_tokens(terms: Sequence[str], sides: tuple[str, ...] | None) -> list[str]:
    """The tokens that name what the reader asked about: the goal terms and the compared sides.

    No product glossary: whatever the goal itself names is the subject we must find.
    """
    tokens: list[str] = []
    for token in list(terms) + [str(side) for side in (sides or ()) if side]:
        token = str(token).strip()
        if len(token) >= 2 and token.lower() not in _GENERIC_SUBJECT_TOKENS and token not in tokens:
            tokens.append(token)
    return tokens


def _source_attribution(text: str, tokens: list[str]) -> str:
    """What is this page mainly about? Lexicon-free: the page's own dominant subjects.

    A page whose most repeated latin subject is not any subject of the question is about
    something else (this is how a "MySQL" explainer stops pretending to answer a PostgreSQL
    question); a page naming the question's subject alongside another product is comparative.
    """
    lowered = text.lower()
    target_mass = sum(lowered.count(token.lower()) for token in tokens)
    counts: dict[str, int] = {}
    for match in _LATIN_WORD.finditer(lowered):
        word = match.group(0)
        if any(word in token.lower() for token in tokens):
            continue
        counts[word] = counts.get(word, 0) + 1
    foreign = sorted(((word, count) for word, count in counts.items() if count >= 3),
                     key=lambda item: (-item[1], item[0]))[:4]
    foreign_mass = sum(count for _word, count in foreign)
    # A page that merely MENTIONS the question's subject while its own subject dominates is
    # about something else - mentioning it once may not earn extraction rights.
    if foreign_mass >= 2 * max(1, target_mass):
        return "foreign_subject"
    if target_mass and foreign_mass:
        return "comparative"
    if target_mass:
        return "target_subject"
    if foreign_mass:
        return "foreign_subject"
    return "unclear"


def question_tokens(text: str) -> list[str]:
    """Product/subject words named by the QUESTION itself (latin words, no glossary).

    The goal's own terms can be Chinese-only (snapshot, cost) while the question names the
    product; without these tokens a legitimate page would look like another product's page.
    """
    return sorted({match.group(0) for match in _LATIN_WORD.finditer((text or "").lower())})


def attribution_of(text: str, goal_terms, sides: tuple[str, ...] = (),
                   question_words: list[str] | None = None) -> str:
    """Which product's mechanism does this page describe?

    Public wrapper over the source-attribution rule: target_subject / comparative /
    foreign_subject / unclear. Used to keep a support that rests on a foreign-dominant page
    from being presented as the asked-about product's mechanism.
    """
    tokens = _goal_tokens(list(goal_terms), sides)
    for word in question_words or []:
        if word and word not in tokens:
            tokens.append(word)
    return _source_attribution(text or "", tokens)


def _source_windows(text: str, terms: Sequence[str], tokens: list[str],
                    quoted: Sequence[str] = ()) -> list[dict[str, Any]]:
    """Bounded, de-duplicated candidates anchored at each subject occurrence.

    The window starts at the sentence that carries the subject (so conditions and conclusions
    are not cut off) and never exceeds WINDOW_CHARS. A passage whose subject is a pronoun
    inherits the previous sentence's subject only when that subject is the question's own.
    """
    lowered = text.lower()
    needles = sorted({str(term).lower() for term in terms if str(term)})
    anchors: list[int] = []
    for needle in needles:
        position = lowered.find(needle)
        while position >= 0:
            anchors.append(position)
            position = lowered.find(needle, position + 1)
    seen: set[tuple[int, int]] = set()
    rows: list[dict[str, Any]] = []
    for anchor in sorted(set(anchors)):
        sentence_start = text.rfind("。", 0, anchor) + 1
        if anchor - sentence_start > WINDOW_CHARS // 2:
            sentence_start = anchor
        start = max(0, sentence_start)
        end = min(len(text), start + WINDOW_CHARS)
        if (start, end) in seen:
            continue
        seen.add((start, end))
        excerpt = text[start:end]
        window_low = excerpt.lower()
        subject = any(token.lower() in window_low for token in tokens)
        previous = text[max(0, start - 80):start]
        inherited = (not subject) and any(marker in window_low[:6]
                                          for marker in _INHERIT_MARKERS) \
            and any(token.lower() in previous.lower() for token in tokens)
        relations = [marker for marker in _RELATION_MARKERS if marker in excerpt]
        behaviour = [marker for marker in _BEHAVIOUR_MARKERS if marker in excerpt]
        co_subjects = sum(1 for token in tokens if token.lower() in window_low)
        # candidate_relevant is a CHEAP FILTER for what extraction is shown - it is not a claim
        # that the passage supports a fact. Support is decided by extraction plus the independent
        # verifier. The passage must be about the question's subject and say something (a
        # relation or a behaviour), never a bare mention with a copula.
        specific_hits = [token for token in tokens if token.lower() in window_low]
        if quoted:
            # The question's own quoted terms are what it is about: a passage that
            # never mentions one of them is not material, however often it repeats
            # the topic's name.
            specific_gate = any(str(term).lower() in window_low for term in quoted)
        else:
            specific_gate = (len(specific_hits) >= 2
                             or (len(specific_hits) == 1 and bool(relations or behaviour)))
        relevant = (subject or inherited) and bool(relations or behaviour) and specific_gate
        rows.append({"span_start": start, "span_end": end, "excerpt": excerpt,
                     "window_kind": "term", "subject": subject or inherited,
                     "candidate_relevant": relevant, "relations": len(relations),
                     "behaviour": len(behaviour), "co_subjects": co_subjects,
                     "not_coverable": end - start >= WINDOW_CHARS})
    # Rank before the per-goal limit cuts: best passages of EVERY region of the page, so a long
    # page cannot lose its later mechanism text to its earlier table of contents.
    def rank_key(row: dict[str, Any]) -> tuple:
        return (0 if row["candidate_relevant"] else 1, -row["relations"], -row["behaviour"],
                -row["co_subjects"], row["span_start"])

    by_region: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_region.setdefault(row["span_start"] // (WINDOW_CHARS * 4), []).append(row)
    picked: list[dict[str, Any]] = []
    for region in sorted(by_region):
        picked.extend(sorted(by_region[region], key=rank_key)[:2])
    chosen_keys = {(row["span_start"], row["span_end"]) for row in picked}
    picked.extend(sorted((row for row in rows
                          if (row["span_start"], row["span_end"]) not in chosen_keys),
                         key=rank_key))
    picked.sort(key=rank_key)
    return picked


def candidate_windows(goal_terms: tuple[str, ...], bodies: Mapping[str, Any], *,
                      limit: int = MAX_WINDOWS_PER_GOAL,
                      sides: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Windows for the candidate prompt, best-first: goal-term hits, then prose.

    This is the UNCHANGED selector used outside the evidence loop, so turning the loop off
    keeps behaviour identical to before.
    """
    terms = [str(term).lower() for term in goal_terms if str(term)]
    candidates: list[dict[str, Any]] = []
    for source_id, body in bodies.items():
        text = body.text or ""
        quality = getattr(body, "quality", None) or {}
        prose = int(quality.get("prose_chars", 0) or 0)
        hits = sum(1 for term in terms if term in text.lower())
        term_window = _window(text, goal_terms)
        prose_window = _prose_window(text)
        for rank, window in ((3, term_window), (2, prose_window)):
            if window is None:
                continue
            excerpt = str(window.get("excerpt") or "")
            if looks_like_navigation(excerpt) or looks_like_list(excerpt):
                continue
            if rank == 3 and not (_SENTENCE_PUNCT.search(excerpt) and len(excerpt) >= 60):
                rank = 1
            candidates.append({
                "source_id": source_id, "window": window, "rank": rank, "hits": hits,
                "prose": prose,
                "matched": [term for term in terms if term in excerpt.lower()],
                "sides": [index for index, side in enumerate(sides or ())
                          if side and str(side).lower() in excerpt.lower()],
                "url": str(getattr(body, "url", "")) or source_id})
            break
    ordered = sorted(candidates, key=lambda row: (-row["rank"], -row["hits"], -row["prose"],
                                                  row["url"]))
    if sides:
        chosen: list[dict[str, Any]] = []
        for index in range(len(sides)):
            same = [row for row in ordered if index in row["sides"]]
            if same and same[0] not in chosen:
                chosen.append(same[0])
        for row in ordered:
            if len(chosen) >= limit:
                break
            if row not in chosen:
                chosen.append(row)
        ordered = chosen[:limit]
    return [{"source_id": row["source_id"], **row["window"],
             "url": row["url"], "sides": row["sides"]} for row in ordered]


def evidence_windows(goal_terms: tuple[str, ...], bodies: Mapping[str, Any], *,
                      limit: int = MAX_WINDOWS_PER_GOAL,
                      sides: tuple[str, ...] | None = None,
                      label: str = "") -> list[dict[str, Any]]:
    """Qualified windows for the EVIDENCE LOOP only (B OFF never calls this).

    Two questions are answered before a passage is offered to extraction:
      * is this PAGE about what the reader asked (its dominant subject is not another product)?
      * is this PASSAGE about that subject and does it state a relation, not just a mention?
    A page that is about something else contributes no window at all, and a passage that is only
    about the subject in passing is ranked below one that states a mechanism, so the single
    extraction is not spent on material that cannot answer the goal.
    """
    terms = [str(term).lower() for term in goal_terms if str(term)]
    tokens = _goal_tokens(list(goal_terms), sides)
    # Terms the question itself quotes ("\u300c\u6c14\u300d", "snapshot") name what it
    # asks about; they join the subject set and gate what counts as material.
    quoted = _quoted_terms(label)
    for term in quoted:
        if term not in tokens:
            tokens.append(term)
    candidates: list[dict[str, Any]] = []
    for source_id, body in bodies.items():
        text = body.text or ""
        quality = getattr(body, "quality", None) or {}
        prose = int(quality.get("prose_chars", 0) or 0)
        hits = sum(1 for term in terms if term in text.lower())
        attribution = _source_attribution(text, tokens)
        if attribution == "foreign_subject":
            continue
        for window in _source_windows(text, goal_terms, tokens, quoted):
            excerpt = str(window.get("excerpt") or "")
            # An index or item-list passage is not material for a claim even when the goal's
            # words appear in it.
            if looks_like_navigation(excerpt) or looks_like_list(excerpt):
                continue
            side_hits = [index for index, side in enumerate(sides or ())
                         if side and str(side).lower() in excerpt.lower()]
            candidates.append({
                "source_id": source_id, "window": window,
                "rank": 3 if window["candidate_relevant"] else 1, "hits": hits,
                "prose": prose,
                "matched": [term for term in terms if term in excerpt.lower()],
                "sides": side_hits})
    # Only material passages are offered at all (a bare mention may not consume the one
    # extraction), then the best passage of each side of a comparison, then by score with the
    # page URL only as a STABLE tie-break so registration order cannot change the choice.
    eligible = [row for row in candidates if row["rank"] == 3]
    ordered = sorted(eligible, key=lambda row: (-len(row["matched"]), -len(row["sides"]),
                                                -row["hits"], -row["prose"],
                                                row["source_id"],
                                                row["window"]["span_start"]))
    # Region diversity must survive the final cut: with a per-goal limit of two, a global sort
    # would otherwise return two passages from the same opening section and lose the mechanism
    # text that a long page keeps further down.
    by_region: dict[int, list[dict[str, Any]]] = {}
    for row in ordered:
        region = row["window"]["span_start"] // (WINDOW_CHARS * 4)
        by_region.setdefault(region, []).append(row)
    diverse: list[dict[str, Any]] = []
    for region in sorted(by_region):
        diverse.append(by_region[region][0])
    for row in ordered:
        if row not in diverse:
            diverse.append(row)
    ordered = diverse
    if sides:
        # A comparison question needs BOTH sides examined: take the best candidate for each
        # side before filling any remaining slot by score.
        chosen: list[dict[str, Any]] = []
        for index in range(len(sides)):
            same = [row for row in ordered if index in row["sides"]]
            if same and same[0] not in chosen:
                chosen.append(same[0])
        for row in ordered:
            if len(chosen) >= limit:
                break
            if row not in chosen:
                chosen.append(row)
        ordered = chosen[:limit]
    return [{"source_id": row["source_id"], **row["window"],
             "sides": [sides[index] for index in row["sides"]] if sides else []}
            for row in ordered[:limit]]


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
                   on_reject: Callable[[str], None] | None = None,
                   sides_by_goal: Mapping[str, tuple[str, ...]] | None = None,
                   windows_by_goal: Mapping[str, list[dict[str, Any]]] | None = None,
                   on_input: Callable[[Mapping[str, Any]], None] | None = None,
                   on_response: Callable[[str], None] | None = None) -> list[Claim]:
    """One batched extraction over every unfinished goal. Never raises on bad model output."""
    def reject(reason: str) -> None:
        if on_reject is not None:
            on_reject(reason)

    if not goals or not bodies:
        return []
    if windows_by_goal is None:
        # Only the fallback re-selects; the agent passes the snapshot the gate already
        # computed, so the scheduler and the extractor never disagree again.
        windows_by_goal = {
            goal_id: evidence_windows(terms, bodies,
                                      sides=(sides_by_goal or {}).get(goal_id))
            for goal_id, terms in goals.items()}
    payload: dict[str, Any] = {
        "goals": [{"goal_id": goal_id, "goal": goal_id, "passages": windows_by_goal[goal_id]}
                  for goal_id in goals],
        "rules": "cite only the given source_id; a claim without a passage is not allowed",
    }
    if not any(windows_by_goal.values()):
        # G3: no goal has a qualified window, so the single extraction opportunity is not
        # consumed and no model call is made. The run keeps collecting under its own budget.
        if on_input is not None:
            on_input({"goals": {g: {"windows": []} for g in goals}, "skipped": True})
        return []
    if on_call is not None:
        on_call()                      # the caller counts a REAL model call, never a guess
    if on_input is not None:
        # An immutable snapshot of what the extractor is about to be shown: a later,
        # recomputed view is not the same evidence.
        on_input({"goals": {goal_id: {"terms": list(terms),
                                      "windows": windows_by_goal[goal_id]}
                            for goal_id, terms in goals.items()}})
    try:
        raw = completion(
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            timeout=timeout, task_name="research_claims")
    except Exception:  # noqa: BLE001 - extraction failure must not break the run
        if on_response is not None:
            on_response("")
        reject("call_failed")
        return []
    if on_response is not None:
        on_response(raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False))
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
