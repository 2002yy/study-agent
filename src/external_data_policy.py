"""External data and model-context policy gates.

These policies are separate from task intent: task intent states what sources
are useful, while user policy decides which external calls and private context
are actually allowed for this turn.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from src.task_intent import SourcePolicy

WebPolicy = Literal["off", "ask", "auto"]
CloudContextPolicy = Literal[
    "question_only",
    "recent_chat",
    "allow_local_evidence",
]

WEB_POLICIES: tuple[WebPolicy, ...] = ("off", "ask", "auto")
CLOUD_CONTEXT_POLICIES: tuple[CloudContextPolicy, ...] = (
    "question_only",
    "recent_chat",
    "allow_local_evidence",
)


@dataclass(frozen=True)
class ExternalDataDecision:
    web_policy: WebPolicy
    cloud_context_policy: CloudContextPolicy
    task_source_policy: SourcePolicy
    web_allowed: bool
    local_retrieval_allowed: bool
    history_allowed: bool
    memory_allowed: bool
    local_evidence_to_model_allowed: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def normalize_web_policy(value: str | None) -> WebPolicy:
    return value if value in WEB_POLICIES else "auto"  # type: ignore[return-value]


def normalize_cloud_context_policy(value: str | None) -> CloudContextPolicy:
    if value in CLOUD_CONTEXT_POLICIES:
        return value  # type: ignore[return-value]
    return "allow_local_evidence"


def decide_external_data(
    *,
    web_policy: str | None,
    web_consent: bool,
    cloud_context_policy: str | None,
    task_source_policy: SourcePolicy,
) -> ExternalDataDecision:
    normalized_web = normalize_web_policy(web_policy)
    normalized_context = normalize_cloud_context_policy(cloud_context_policy)
    task_allows_web = task_source_policy in {
        "web_only",
        "local_and_web",
        "ask_before_external",
    }
    web_allowed = task_allows_web and (
        normalized_web == "auto"
        or (normalized_web == "ask" and web_consent)
    )
    local_retrieval_allowed = task_source_policy in {
        "local_only",
        "local_and_web",
    }
    history_allowed = normalized_context in {
        "recent_chat",
        "allow_local_evidence",
    }
    local_context_allowed = normalized_context == "allow_local_evidence"
    reason = (
        "web_disabled_by_user"
        if normalized_web == "off"
        else "web_consent_required"
        if normalized_web == "ask" and not web_consent
        else "task_does_not_allow_web"
        if not task_allows_web
        else "allowed"
    )
    return ExternalDataDecision(
        web_policy=normalized_web,
        cloud_context_policy=normalized_context,
        task_source_policy=task_source_policy,
        web_allowed=web_allowed,
        local_retrieval_allowed=local_retrieval_allowed,
        history_allowed=history_allowed,
        memory_allowed=local_context_allowed,
        local_evidence_to_model_allowed=local_context_allowed,
        reason=reason,
    )
