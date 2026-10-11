"""C. Gap-driven follow-up planning: turn "what is missing" into a concrete next query.

Deterministic and answer-free: the query is built from the goal's OWN terms plus the
verifier's description of what is missing, reusing the shared tokenizer. Queries already
issued are never repeated, and no topic's answer is ever written into a query.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.web.link_discovery import question_terms
from src.web.research_claim_verifier import ClaimVerdict

MAX_FOLLOWUPS = 2
QUERY_CHARS = 160


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
        if any(row.internal_supported for row in rows):
            continue                                    # a settled goal is not re-searched
        gap_words: list[str] = []
        contradicted = False
        for row in rows:
            if row.verdict == "contradicted":
                contradicted = True
            if row.verdict in {"insufficient", "contradicted", "unavailable"}:
                gap_words.extend(_tokens(row.missing))
        base = [str(term) for term in goals.get(goal_id, ())[:4]]
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
