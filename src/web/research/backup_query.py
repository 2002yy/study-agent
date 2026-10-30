"""One bounded planning call for an alternative search query (Search-3A).

The deterministic normalizer usually yields a single query for a plain Chinese
question, so a failed first batch can leave nothing to retry. The chat path
already has a semantic planner that proposes two or three query wordings; this
reuses that session for the Standard lookup rather than inventing a second
planner or a keyword list.

It is called only from the retry gate - never on the normal path - and it is
plain query planning: the returned text is searched like any other variant and
still has to survive reading.
"""

from __future__ import annotations

import time
from typing import Callable

#: The session refuses a request when less than this remains.
_MIN_PLANNING_WINDOW = 2.0


def plan_backup_query(
    *,
    query: str,
    completion: Callable[..., str],
    timeout_seconds: float = 8.0,
    task_id: str = "",
) -> str:
    """Return one different query wording, or "" when none is offered."""

    from src.web.semantic_recovery import ResearchEpisode, ResearchSemanticSession

    normalized = " ".join(str(query or "").split())
    if not normalized:
        return ""
    session = ResearchSemanticSession(
        completion,
        deadline=time.monotonic() + max(_MIN_PLANNING_WINDOW, float(timeout_seconds)),
        should_cancel=lambda: False,
    )
    episode = ResearchEpisode(
        task_id=task_id or "backup-query",
        thread_id="",
        original_question=normalized[:4096],
        questions=[{"id": "rq-question", "question": normalized[:500]}],
    )
    decision = session.interpret(
        episode,
        normalized,
        history="",
        active_task_exists=False,
    )
    for row in getattr(decision, "proposed_queries", ()) or ():
        if not isinstance(row, dict):
            continue
        candidate = " ".join(str(row.get("query") or "").split())
        if candidate and candidate.casefold() != normalized.casefold():
            return candidate[:300]
    return ""
