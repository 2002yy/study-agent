"""Top-level task intent contract.

Keep user intent separate from role voice, pedagogy protocol, source policy,
and memory eligibility. Classification and runtime integration live in
``src.task_contract`` so this module remains the stable domain contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
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

SourcePolicy = Literal[
    "model_only",
    "local_only",
    "web_only",
    "local_and_web",
    "ask_before_external",
]

ContractConfidence = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class TaskContract:
    """Stable contract passed between routing, pedagogy, sources and memory."""

    task_intent: TaskIntent
    closure_eligibility: ClosureEligibility
    source_policy: SourcePolicy = "local_and_web"
    learning_state_enabled: bool = False
    confidence: ContractConfidence = "low"
    reason: str = ""
    explicit_override: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def default_contract(task_intent: TaskIntent) -> TaskContract:
    """Return conservative source, learning and closure behavior."""

    closure: dict[TaskIntent, ClosureEligibility] = {
        "quick_answer": "optional_note",
        "research": "research_summary",
        "learn": "learning_summary",
        "explain_back": "learning_summary",
        "project_execution": "project_summary",
        "conversation": "not_applicable",
        "organize": "optional_note",
    }
    source: dict[TaskIntent, SourcePolicy] = {
        "quick_answer": "local_and_web",
        "research": "web_only",
        "learn": "local_and_web",
        "explain_back": "local_and_web",
        "project_execution": "local_and_web",
        "conversation": "model_only",
        "organize": "model_only",
    }
    learning_state_enabled = task_intent in {
        "learn",
        "explain_back",
        "project_execution",
    }
    return TaskContract(
        task_intent=task_intent,
        closure_eligibility=closure[task_intent],
        source_policy=source[task_intent],
        learning_state_enabled=learning_state_enabled,
    )
