"""C. Gap-driven follow-up planning: turn "what is missing" into a concrete next query.

Deterministic and answer-free: the query is built from the goal's OWN terms plus the
verifier's description of what is missing, reusing the shared tokenizer. Queries already
issued are never repeated, and no topic's answer is ever written into a query.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.web.link_discovery import answer_items, question_terms
from src.web.research_claim_verifier import ClaimVerdict

MAX_FOLLOWUPS = 2
QUERY_CHARS = 160

def uncovered_items(goal_id: str,
                    verdicts: Sequence[ClaimVerdict]) -> list[tuple[int, str]]:
    """Which necessary answer items of a goal no supported claim has covered yet.

    A goal with one correct claim is NOT finished: a PARTIAL answer is a legitimate state and
    must still ask for what is missing.
    """
    items = answer_items(goal_id)
    covered: set[int] = set()
    for verdict in verdicts:
        if verdict.goal_id != goal_id or not verdict.internal_supported:
            continue
        covered.update(index for index in verdict.covers if 0 <= index < len(items))
    return [(index, item) for index, item in enumerate(items) if index not in covered]
def _tokens(text: str) -> list[str]:
    return sorted(question_terms(text))


def plan_followups(*, verdicts: Sequence[ClaimVerdict],
                   goals: Mapping[str, tuple[str, ...]],
                   issued: Sequence[str] = ()) -> list[dict[str, Any]]:
    """At most MAX_FOLLOWUPS targeted questions for goals that are still unresolved."""
    issued_set = {item.strip() for item in issued}
    by_goal: dict[str, list[ClaimVerdict]] = {}
    for verdict in verdicts:
        by_goal.setdefault(verdict.goal_id, []).append(verdict)

    planned: list[dict[str, Any]] = []
    for goal_id, rows in by_goal.items():
        missing = uncovered_items(goal_id, rows)
        if not missing:
            continue                          # every necessary answer item is covered
        gap_words: list[str] = []
        contradicted = False
        for row in rows:
            if row.verdict == "contradicted":
                contradicted = True
            if row.verdict in {"insufficient", "contradicted", "unavailable"}:
                gap_words.extend(_tokens(row.missing))
        # The query names the item that is still missing, not the whole goal again.
        base = [item for _index, item in missing][:2]
        base = [str(term) for item in base for term in _tokens(item)] or \
            [str(term) for term in goals.get(goal_id, ())[:4]]
        words = list(dict.fromkeys(base + gap_words))[:8]
        query = " ".join(word for word in words if word)[:QUERY_CHARS]
        if not query or query in issued_set:
            continue                                    # never repeat an issued query
        planned.append({
            "goal_id": goal_id,
            "query": query,
            "reason": "contradiction needs clarifying material" if contradicted
            else "evidence gap for this goal",
        })
        issued_set.add(query)
        if len(planned) >= MAX_FOLLOWUPS:
            break
    return planned
