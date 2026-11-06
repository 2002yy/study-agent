"""Restore one explicitly chosen older interactive version from saved turns.

The learner can reopen any earlier version of a generated document and keep
editing from there. The source for that version must come from the session's own
saved answers, never from the request payload and never from a model's memory:
a summary is not a document, and a model asked to "recreate V1" would be
guessing.

This module only locates and validates the source. It does not regenerate,
patch, or rewrite stored messages.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from src.interactive_history import InteractiveVersion, find_interactive_versions

STATUS_RESTORED = "restored"
STATUS_NOT_FOUND = "not_found"
STATUS_CONFLICT = "conflict"
STATUS_EXHAUSTED = "revision_exhausted"
STATUS_INVALID = "invalid_request"

MAX_REVISION = 999
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class TurnLike(Protocol):
    id: str
    status: str
    assistant_message: str


@dataclass(frozen=True)
class RestoreRequest:
    id: str
    revision: int

    @classmethod
    def from_payload(cls, payload: Any) -> RestoreRequest | None:
        if not isinstance(payload, dict):
            return None
        identifier = payload.get("id")
        revision = payload.get("revision")
        if not isinstance(identifier, str) or not identifier.strip():
            return None
        if not ID_PATTERN.match(identifier):
            return None
        if isinstance(revision, bool) or not isinstance(revision, int):
            return None
        if revision < 1 or revision > MAX_REVISION:
            return None
        return cls(id=identifier, revision=revision)


@dataclass(frozen=True)
class RestoreOutcome:
    request: RestoreRequest
    status: str
    html: str | None
    turn_id: str | None
    next_revision: int | None
    detail: str
    capabilities: tuple[str, ...] = ()

    @property
    def restorable(self) -> bool:
        return self.status == STATUS_RESTORED


def _unsuccessful(request: RestoreRequest, status: str, detail: str) -> RestoreOutcome:
    return RestoreOutcome(
        request=request,
        status=status,
        html=None,
        turn_id=None,
        next_revision=None,
        detail=detail,
    )


def locate_restore_source(
    turns: Iterable[TurnLike], request: RestoreRequest
) -> RestoreOutcome:
    """Find the one saved source for ``id`` + ``revision`` in these turns."""

    matches: list[tuple[str, InteractiveVersion]] = []
    revisions: set[int] = set()
    for turn in turns:
        if getattr(turn, "status", "") != "completed":
            continue
        message = getattr(turn, "assistant_message", "") or ""
        if not message:
            continue
        for version in find_interactive_versions(
            [{"role": "assistant", "content": message}]
        ):
            if version.id != request.id:
                continue
            revisions.add(version.revision)
            if version.revision == request.revision:
                matches.append((getattr(turn, "id", ""), version))

    if not matches:
        return _unsuccessful(
            request,
            STATUS_NOT_FOUND,
            "当前会话记录里没有这个版本的完整源码",
        )

    sources = {(version.html, version.capabilities) for _, version in matches}
    if len(sources) > 1:
        # Two different documents claim the same identity. Picking either one
        # would silently change what the learner is editing.
        return _unsuccessful(
            request,
            STATUS_CONFLICT,
            f"同一 id 与 revision 对应 {len(sources)} 份不同源码，无法确定基线",
        )

    turn_id, version = matches[0]
    next_revision = max(revisions) + 1
    if next_revision > MAX_REVISION:
        return _unsuccessful(
            request,
            STATUS_EXHAUSTED,
            f"该组件版本号已用到 {max(revisions)}，无法再派生新版本",
        )
    return RestoreOutcome(
        request=request,
        status=STATUS_RESTORED,
        html=version.html,
        turn_id=turn_id,
        next_revision=next_revision,
        detail="",
        capabilities=version.capabilities,
    )


def resolve_interactive_restore(
    repository: Any, thread_id: str | None, request: RestoreRequest
) -> RestoreOutcome:
    """Locate the source inside this thread only; nothing is trusted from input."""

    if repository is None or not thread_id:
        return _unsuccessful(request, STATUS_NOT_FOUND, "本轮没有可用的会话记录")
    if repository.get_chat_thread(thread_id) is None:
        return _unsuccessful(request, STATUS_NOT_FOUND, "会话不存在或不可访问")
    try:
        turns = repository.list_chat_turns(thread_id)
    except Exception:  # noqa: BLE001 - a read failure must not invent a source
        return _unsuccessful(request, STATUS_NOT_FOUND, "读取会话记录失败")
    return locate_restore_source(turns, request)


def resolve_command_restore(
    repository: Any, thread_id: str | None, command: Any
) -> RestoreOutcome | None:
    """Turn an optional request on the command into an outcome, or ``None``."""

    request = RestoreRequest.from_payload(getattr(command, "interactive_restore", None))
    if request is None:
        return None
    return resolve_interactive_restore(repository, thread_id, request)


def restore_context_block(outcome: RestoreOutcome) -> str:
    """The exact, bounded statement the model receives about this restore."""

    request = outcome.request
    if outcome.status == STATUS_RESTORED and outcome.html is not None:
        return (
            "[用户选择的旧界面源码 · 本轮修改基线]\n"
            f"component_id: {request.id}\n"
            f"base_revision: {request.revision}\n"
            f"expected_new_revision: {outcome.next_revision}\n"
            + (
                f"capabilities: {list(outcome.capabilities)}，新版本必须保留此宿主能力声明\n"
                if outcome.capabilities
                else ""
            )
            + f"source: 会话历史 {outcome.turn_id}，由用户明确选择，不是模型推测\n"
            "本轮必须基于下面的完整源码修改。输出同一 id、"
            f"revision={outcome.next_revision} 的完整新版本，不输出补丁。\n"
            "历史中的旧版本摘要只是记录；不要重写、重新命名或声称重做其它版本。\n"
            "```html\n"
            f"{outcome.html}\n"
            "```"
        )
    reason = outcome.detail or "未找到源码"
    return (
        "[旧版界面恢复失败]\n"
        f"component_id: {request.id}\n"
        f"requested_revision: {request.revision}\n"
        f"reason: {reason}\n"
        "本轮没有该版本的源码。必须明确告诉用户无法恢复这个版本；"
        "不得凭摘要、记忆或其它版本重建，也不得声称已经恢复。"
    )


def restore_record(outcome: RestoreOutcome) -> dict[str, Any]:
    """A route-snapshot record: identity and derivation, no source text."""

    return {
        "status": outcome.status,
        "component_id": outcome.request.id,
        "base_revision": outcome.request.revision,
        "source_turn_id": outcome.turn_id,
        "expected_new_revision": outcome.next_revision,
        "detail": outcome.detail,
    }
