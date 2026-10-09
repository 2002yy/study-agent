"""B proposes natural questions; the existing episode owns ids and governance."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from src.web.conversation_query import is_research_resume
from src.web.tool_evidence import _public_url

MAX_TASKS = 24
PLANNING_PROMPT = (
    "Understand latest_message in its episode context and freely propose fine-grained, "
    "independently answerable natural-language research questions. Preserve entities, "
    "versions, time ranges, comparison conditions and all original obligations. "
    "Do not invent answers or evidence. Do not generate database ids or task categories. "
    'Return {"tasks":[{"question":"subquestion", "query":"optional public search query"}]}. '
    "At most 24 tasks; queries are advice, not extra search budget. "
    "You may also provide intent (NEW_RESEARCH, CONTINUE_ACTIVE_RESEARCH, REFINE_RESEARCH, "
    "ANSWER or ABSTAIN) and constraints_delta with focus/source_preference/excluded_page_types/persistence. "
    "When active_task_exists=false, retry/control words cannot create a new research task; abstain. "
    "For continuation preserve the original topic; for a different topic use NEW_RESEARCH. "
    "A provisional episode is not prior research. Do not copy its coarse question as the only plan. "
    "Do not access private resources or authorize evidence, budgets, tools or publication."
)


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError("invalid_task_question_or_query")
    return value.strip()


def public_query(value: Any) -> str:
    query = _text(value)
    if is_research_resume(query):
        raise ValueError("control_query")
    if re.search(r"(?:file:|localhost|127\.0\.0\.1|\[::1\]|\.local\b)", query, re.I):
        raise ValueError("private_query")
    for url in re.findall(r"\b[a-z]+://[^\s]+", query, re.I):
        if not _public_url(url):
            raise ValueError("private_query")
    for host in re.findall(r"site:([^\s)]+)", query, re.I):
        if not _public_url("https://" + host):
            raise ValueError("private_domain")
    return query


def normalize_tasks(
    raw: Any,
    *,
    task_id: str,
    previous: list[dict[str, str]],
    preserve_previous: bool,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > MAX_TASKS:
        raise ValueError("invalid_tasks")
    questions = [dict(row) for row in previous] if preserve_previous else []
    by_text = {row["question"]: row["id"] for row in questions}
    queries: list[dict[str, str]] = []
    provenance: list[dict[str, Any]] = []
    for index, task in enumerate(raw):
        if (
            not isinstance(task, dict)
            or "question" not in task
            or set(task) - {"question", "query"}
        ):
            raise ValueError("task_fields")
        question = _text(task["question"])
        duplicate = question in by_text
        rq_id = (
            by_text.get(question)
            or "rq-"
            + hashlib.sha256((task_id + "\0" + question).encode("utf-8")).hexdigest()[
                :24
            ]
        )
        if not duplicate:
            questions.append({"id": rq_id, "question": question})
            by_text[question] = rq_id
        # Validate every proposal, including duplicates/deferred ones; an unsafe
        # proposal cannot disappear merely because the execution budget is full.
        query = public_query(task.get("query", question))
        if not any(row == {"rq_id": rq_id, "query": query} for row in queries):
            queries.append({"rq_id": rq_id, "query": query})
        provenance.append(
            {"proposal_index": index, "rq_id": rq_id, "exact_duplicate": duplicate}
        )
    if not questions or len(questions) > MAX_TASKS:
        raise ValueError("task_limit_or_missing_tasks")
    unique_queries = list(dict.fromkeys(row["query"] for row in queries))
    selected_queries = set(unique_queries[:5])
    selected = [row for row in queries if row["query"] in selected_queries]
    return (
        questions,
        selected,
        {
            "owner_task_id": task_id,
            "proposal_mapping": provenance,
            "proposed_queries": queries,
            "deferred_queries": [
                {**row, "reason": "planning_query_cap"}
                for row in queries
                if row["query"] not in selected_queries
            ],
            "deferred_rq_ids": [
                row["id"]
                for row in questions
                if row["id"] not in {q["rq_id"] for q in selected}
            ],
            "publication_authority": False,
        },
    )
