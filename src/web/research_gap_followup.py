"""M4-C5: deterministic, bounded follow-up hints from unsatisfied research goals.

No additional model call and no guessed URL. These hints are proposals for the
existing safe search tool, not permission to bypass its discovery or quotas.
"""
from __future__ import annotations

from typing import Any, Mapping


MAX_GAP_QUERIES = 3


def plan_gaps(goals: Mapping[str, Any], state: Mapping[str, Mapping[str, Any]],
              verdicts: list[dict[str, Any]],
              question: str, issued_queries: set[str]) -> list[dict[str, str]]:
    by_goal: dict[str, list[str]] = {}
    for record in verdicts:
        by_goal.setdefault(str(record["goal"]), []).append(str(record["status"]))
    planned: list[dict[str, str]] = []
    used: set[str] = set(issued_queries)
    used.add(" ".join(question.split()).casefold())
    for goal in goals:
        status = str((state.get(goal) or {}).get("status") or "missing")
        if status == "supported":
            continue
        outcomes = by_goal.get(goal, [])
        reason = ("conflicting_assertion" if "conflict" in outcomes else
                  "source_unavailable" if "unavailable" in outcomes else
                  "partial_evidence" if outcomes or status == "explored" else
                  "no_evidence")
        suffix = {
            "conflicting_assertion": "适用条件 版本差异 原始文档",
            "source_unavailable": "完整说明 原文 文档",
            "partial_evidence": "具体机制 限制 代价 示例",
            "no_evidence": "具体原理 工作方式 官方文档",
        }[reason]
        # Keep the exact unsatisfied goal as the subject; don't recycle the broad
        # user question. Suppress short, duplicate and already-issued requests.
        query = " ".join((goal.strip(), suffix)).strip()[:180]
        normalized = " ".join(query.split()).casefold()
        if len(normalized) < 12 or normalized in used:
            continue
        used.add(normalized)
        planned.append({"goal": goal, "reason": reason, "query": query})
        if len(planned) >= MAX_GAP_QUERIES:
            break
    return planned


def useful_followup(query: str, gaps: list[dict[str, str]],
                    issued_queries: set[str], question: str) -> bool:
    """When a verified gap exists, reject a generic repeat of the original task."""
    normalized = " ".join(query.split()).casefold()
    if normalized in issued_queries or normalized == " ".join(question.split()).casefold():
        return False
    # Allow a materially rewritten, topic-specific query or one of our hints.
    return (any(normalized == " ".join(gap["query"].split()).casefold() for gap in gaps)
            or (len(normalized) >= 12 and any(
                str(gap["goal"]).casefold() in normalized for gap in gaps)))
