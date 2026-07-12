"""Top-level task intent contract.

This is the first G11 slice: keep user intent separate from role, pedagogy
protocol, and memory eligibility. Routing integration is intentionally kept
separate so existing behavior is not silently changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TaskIntent = Literal[
    "quick_answer",
    "research",
    "learn",
    "explain_back",
    "project_execution",
    "conversation",
    "organize",
]

ClosureEligibility = Literal[
    "not_applicable",
    "optional_note",
    "learning_summary",
    "research_summary",
    "project_summary",
]


@dataclass(frozen=True)
class TaskContract:
    """Stable contract passed between routing, pedagogy and memory layers."""

    task_intent: TaskIntent
    closure_eligibility: ClosureEligibility
    explicit_override: bool = False


def default_contract(task_intent: TaskIntent) -> TaskContract:
    """Return conservative closure behavior for a task type."""
    mapping: dict[TaskIntent, ClosureEligibility] = {
        "quick_answer": "optional_note",
        "research": "research_summary",
        "learn": "learning_summary",
        "explain_back": "learning_summary",
        "project_execution": "project_summary",
        "conversation": "not_applicable",
        "organize": "optional_note",
    }
    return TaskContract(
        task_intent=task_intent,
        closure_eligibility=mapping[task_intent],
    )
