"""External data and model-context policy gates.

These policies are separate from task intent: task intent states what sources
are useful, while user policy decides which external calls and private context
are actually allowed for this turn.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Literal

from src.task_intent import SourcePolicy

WebPolicy = Literal["off", "ask", "auto"]
CloudContextPolicy = Literal[
    "question_only",
    "recent_chat",
    "allow_local_evidence",
]
# G16 decision 1: independent read-authorization gate for cross-session
# memory (read_memory_bundle). Write behavior stays under runtime
# memory_mode; this only gates what enters the model context.
MemoryPolicy = Literal["off", "ask", "auto"]

WEB_POLICIES: tuple[WebPolicy, ...] = ("off", "ask", "auto")
CLOUD_CONTEXT_POLICIES: tuple[CloudContextPolicy, ...] = (
    "question_only",
    "recent_chat",
    "allow_local_evidence",
)
MEMORY_POLICIES: tuple[MemoryPolicy, ...] = ("off", "ask", "auto")


@dataclass(frozen=True)
class ExternalDataDecision:
    web_policy: WebPolicy
    cloud_context_policy: CloudContextPolicy
    memory_policy: MemoryPolicy
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


def normalize_memory_policy(value: str | None) -> MemoryPolicy:
    return value if value in MEMORY_POLICIES else "auto"  # type: ignore[return-value]


def decide_external_data(
    *,
    web_policy: str | None,
    web_consent: bool,
    cloud_context_policy: str | None,
    task_source_policy: SourcePolicy,
    memory_policy: str | None = None,
    memory_consent: bool = False,
) -> ExternalDataDecision:
    """G16: memory_consent carries the per-session grant for ask mode.

    AND gate (decision 9): memory needs BOTH the memory policy to allow it
    (auto, or ask with a session grant) AND cloud_context_policy at
    allow_local_evidence. `memory_consent` is ignored in auto mode.
    """
    normalized_web = normalize_web_policy(web_policy)
    normalized_context = normalize_cloud_context_policy(cloud_context_policy)
    normalized_memory = normalize_memory_policy(memory_policy)
    memory_policy_allowed = normalized_memory == "auto" or (
        normalized_memory == "ask" and memory_consent
    )
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
        memory_policy=normalized_memory,
        task_source_policy=task_source_policy,
        web_allowed=web_allowed,
        local_retrieval_allowed=local_retrieval_allowed,
        history_allowed=history_allowed,
        memory_allowed=local_context_allowed and memory_policy_allowed,
        local_evidence_to_model_allowed=local_context_allowed,
        reason=reason,
    )


# -- whether this turn actually searches -------------------------------------------
#
# `web_allowed` answers "may this turn use the web at all". It must not answer
# "should it search": `quick_answer` carries `local_and_web`, so treating the
# permission as an instruction made every static question pay for a web call.
# `decide_web_use` is the second, narrower gate at the tool boundary.

_NO_WEB_INSTRUCTION = re.compile(
    r"(?:不要|别|不用|无需|不需要|不必)\s*(?:联网|上网|搜|查网|查网上|用网)"
    r"|(?:只|仅)(?:用|使用)?本地(?:资料|知识|内容|文件)?"
    r"|(?:不|别)(?:要)?(?:联网|上网|搜索|查网上)"
)
_WEB_ONLY_SOURCES = {"web_only"}


@dataclass(frozen=True)
class WebUseDecision:
    """The tool-boundary answer: run the web agent, and why (or why not)."""

    run_tools: bool
    reason: str


def explicit_no_web_instruction(user_input: str) -> bool:
    """A user instruction that forbids network access for this turn.

    Only ever narrows permission. A setting or a mode can never override it.
    """

    return bool(_NO_WEB_INSTRUCTION.search(user_input or ""))


def decide_web_use(
    *,
    contract: Mapping[str, object] | None,
    user_input: str = "",
    web_allowed: bool = True,
    policy_reason: str = "allowed",
    research_resume: bool = False,
) -> WebUseDecision:
    """Decide whether the web agent should run for this turn.

    Order matters: an explicit "don't go online" wins over a research intent,
    over deep mode, and over the saved web policy. A permission that is already
    denied keeps the permission decision's own reason so the audit trail does
    not blame the task contract for a user setting.
    """

    if explicit_no_web_instruction(user_input):
        return WebUseDecision(False, "web_disabled_by_user")
    if not web_allowed:
        return WebUseDecision(False, policy_reason or "task_does_not_allow_web")
    snapshot = contract or {}
    intent = str(snapshot.get("task_intent", ""))
    source_policy = str(snapshot.get("source_policy", ""))
    if intent == "research" or source_policy in _WEB_ONLY_SOURCES or research_resume:
        return WebUseDecision(True, "task_requires_web")
    return WebUseDecision(False, "task_does_not_require_web")
