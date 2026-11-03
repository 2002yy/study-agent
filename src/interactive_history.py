"""Compress superseded interactive UI versions in the model input only.

An answer may carry a full HTML application. When the learner iterates on it,
the next request would otherwise include every earlier version verbatim, paying
their input cost again and giving the model a chance to copy a defect that a
later version already fixed.

This module keeps the stored answer untouched. It only rewrites the copy of the
history that is about to be sent to the model:

* the version the learner is working on stays verbatim;
* older revisions of that same ``id`` become a short, factual record;
* anything that cannot be parsed with confidence is left exactly as written.

It deliberately does not summarize what a revision changed. Without a reliable
change note, only fields that already exist (id, revision, title, summary) are
kept, so the model never receives an invented reason as if it were fact.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

# Declared by the frontend answer-UI context. Compression is only useful where
# the learner is working on a UI, so an absent marker leaves history untouched.
INTERACTIVE_CAPABILITY_MARKER = "【自由交互界面 v1】"

MAX_ID_CHARS = 64
MAX_SUMMARY_CHARS = 2000

_OPEN_FENCE = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})[ \t]*study-ui[ \t]*$")
_CLOSE_FENCE = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})[ \t]*$")
# The follow-up button writes `继续探索「标题」（版本 N）`; that is the one
# reliable statement of which component the learner is currently editing.
_TITLE_REFERENCE = re.compile(
    r"继续探索「(?P<title>[^」]{1,120})」(?:（版本 (?P<revision>\d{1,6})）)?"
)

STUB_HEADER = "[历史交互界面摘要 · 已被后续版本替代]"
STUB_FOOTER = "[摘要结束]"
STUB_STATUS = (
    "完整源码未提供；不要据此重建该版本，也不要声称它是原版。"
    "需要旧版源码时，应从已保存的会话记录恢复。"
)


@dataclass(frozen=True)
class InteractiveVersion:
    """One valid ``study-ui`` interactive block found in the history."""

    message_index: int
    id: str
    revision: int
    title: str
    summary: str
    html_chars: int
    start: int
    end: int
    summary_truncated: bool = False


@dataclass(frozen=True)
class InteractiveHistoryResult:
    """The rewritten messages plus the numbers an offline report needs."""

    messages: list[dict[str, Any]]
    report: dict[str, Any]


def _line_spans(content: str) -> list[tuple[int, int, str]]:
    """(start, end, text-without-newline) per line, tolerant of CRLF and LF."""

    spans: list[tuple[int, int, str]] = []
    position = 0
    for line in content.splitlines(keepends=True):
        end = position + len(line)
        spans.append((position, end, line.rstrip("\r\n")))
        position = end
    return spans


def _close_index(
    lines: list[tuple[int, int, str]], start: int, marker: str
) -> int | None:
    for index in range(start + 1, len(lines)):
        match = _CLOSE_FENCE.match(lines[index][2])
        if match and match.group("marker")[0] == marker[0]:
            if len(match.group("marker")) >= len(marker):
                return index
    return None


def _valid_block(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("type") != "interactive":
        return None
    identifier = payload.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        return None
    if len(identifier.strip()) > MAX_ID_CHARS:
        return None
    revision = payload.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        return None
    html = payload.get("html")
    if not isinstance(html, str) or not html.strip():
        return None
    return payload


def find_interactive_versions(
    chat_history: list[dict[str, Any]],
) -> list[InteractiveVersion]:
    """Every complete, valid interactive block, in history order.

    An unclosed fence, a non-object payload, a missing id/revision, or an empty
    document is not a component: it is left alone rather than guessed at.
    """

    found: list[InteractiveVersion] = []
    for message_index, message in enumerate(chat_history):
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, str) or "study-ui" not in content:
            continue
        lines = _line_spans(content)
        for line_index, (_, _, text) in enumerate(lines):
            opening = _OPEN_FENCE.match(text)
            if not opening:
                continue
            closing = _close_index(lines, line_index, opening.group("marker"))
            if closing is None:
                # Half-written markup is not a version; keep the text as it is.
                break
            raw = content[lines[line_index][1] : lines[closing][0]]
            try:
                payload = _valid_block(json.loads(raw))
            except (ValueError, TypeError):
                payload = None
            if payload is None:
                continue
            summary = payload.get("summary")
            summary_text = summary if isinstance(summary, str) else ""
            truncated = len(summary_text) > MAX_SUMMARY_CHARS
            if truncated:
                summary_text = summary_text[:MAX_SUMMARY_CHARS]
            title = payload.get("title")
            found.append(
                InteractiveVersion(
                    message_index=message_index,
                    id=str(payload["id"]).strip(),
                    revision=int(payload["revision"]),
                    title=title if isinstance(title, str) else "",
                    summary=summary_text,
                    html_chars=len(str(payload["html"])),
                    start=lines[line_index][0],
                    end=lines[closing][1],
                    summary_truncated=truncated,
                )
            )
    return found


def _revision_from_user(user_input: str) -> tuple[str | None, int | None]:
    match = _TITLE_REFERENCE.search(user_input or "")
    if not match:
        return None, None
    revision = match.group("revision")
    return match.group("title").strip(), int(revision) if revision else None


def _resolve_target(
    versions: list[InteractiveVersion],
    user_input: str,
    target_id: str | None,
    target_revision: int | None,
) -> tuple[str | None, int | None, str]:
    """Which component and revision the learner is editing, with a reason."""

    if target_id:
        matching = [item for item in versions if item.id == target_id]
        if not matching:
            return None, None, "target_id_not_in_history"
        revision = target_revision or max(item.revision for item in matching)
        return target_id, revision, "explicit_id"

    title, referenced_revision = _revision_from_user(user_input)
    if title:
        matching = [item for item in versions if item.title == title]
        if matching:
            chosen = target_revision or referenced_revision
            if chosen is not None:
                exact = [item for item in matching if item.revision == chosen]
                if exact:
                    matching = exact
                else:
                    chosen = None
            # Same title can appear under two ids when a model renamed the
            # component mid-conversation; keep the newest matching one.
            representative = max(
                matching, key=lambda item: (item.revision, item.message_index)
            )
            return (
                representative.id,
                chosen or representative.revision,
                "followup_title",
            )

    identifiers = sorted({item.id for item in versions})
    if len(identifiers) == 1:
        chosen = target_revision or max(
            item.revision for item in versions if item.id == identifiers[0]
        )
        return identifiers[0], chosen, "single_id"

    # Several components are in play and the learner has not said which one is
    # being changed. Guessing "the last HTML in history" could rewrite a
    # different experiment, so nothing is compressed.
    return None, None, "ambiguous_multiple_ids"


def _stub(version: InteractiveVersion) -> str:
    lines = [STUB_HEADER, f"id: {version.id}", f"revision: {version.revision}"]
    if version.title:
        lines.append(f"title: {version.title}")
    if version.summary:
        lines.append(f"summary: {version.summary}")
    if version.summary_truncated:
        lines.append("summary_truncated: true")
    lines.append(f"status: {STUB_STATUS}")
    lines.append(STUB_FOOTER)
    return "\n".join(lines)


def _heuristic_tokens(chars: int) -> int:
    # Comparison-only estimate, not a provider count: JSON/HTML mixes around
    # three characters per token, CJK prose closer to one. The ratio between
    # before and after is the number that stays meaningful.
    return math.ceil(chars / 3) if chars else 0


def _total_chars(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
    return total


def compress_interactive_history(
    chat_history: list[dict[str, Any]] | None,
    *,
    user_input: str = "",
    capability_enabled: bool = True,
    target_id: str | None = None,
    target_revision: int | None = None,
) -> InteractiveHistoryResult:
    """Return a model-input copy where superseded UI sources are summarized.

    Stored messages, user text and the current version are never rewritten.
    Any failure to parse returns the original list unchanged.
    """

    original = list(chat_history or [])
    report: dict[str, Any] = {
        "status": "unchanged",
        "reason": "",
        "target_id": None,
        "target_revision": None,
        "versions": [],
        "stubbed_revisions": [],
        "untouched_ids": [],
        "removed_fields": [],
        "chars_before": _total_chars(original),
        "chars_after": _total_chars(original),
        "chars_removed": 0,
        "heuristic_tokens_before": _heuristic_tokens(_total_chars(original)),
        "heuristic_tokens_after": _heuristic_tokens(_total_chars(original)),
    }
    if not original:
        report["reason"] = "empty_history"
        return InteractiveHistoryResult(messages=original, report=report)
    if not capability_enabled:
        report["reason"] = "capability_not_declared"
        return InteractiveHistoryResult(messages=original, report=report)

    try:
        versions = find_interactive_versions(original)
    except Exception:  # noqa: BLE001 - an unexpected shape must not break chat
        report["status"] = "error"
        report["reason"] = "parse_failed"
        return InteractiveHistoryResult(messages=original, report=report)
    if not versions:
        report["reason"] = "no_interactive_versions"
        return InteractiveHistoryResult(messages=original, report=report)

    resolved_id, resolved_revision, reason = _resolve_target(
        versions, user_input, target_id, target_revision
    )
    report["reason"] = reason
    if resolved_id is None:
        report["status"] = "unresolved_target"
        report["versions"] = [
            {"id": item.id, "revision": item.revision, "message_index": item.message_index}
            for item in versions
        ]
        return InteractiveHistoryResult(messages=original, report=report)

    report["target_id"] = resolved_id
    report["target_revision"] = resolved_revision
    report["versions"] = [
        {
            "id": item.id,
            "revision": item.revision,
            "title": item.title,
            "message_index": item.message_index,
            "html_chars": item.html_chars,
            "kept": item.id == resolved_id and item.revision == resolved_revision,
        }
        for item in versions
    ]
    report["untouched_ids"] = sorted(
        {item.id for item in versions if item.id != resolved_id}
    )

    superseded = [
        item
        for item in versions
        if item.id == resolved_id and item.revision != resolved_revision
    ]
    if not superseded:
        report["status"] = "nothing_superseded"
        return InteractiveHistoryResult(messages=original, report=report)

    messages = list(original)
    by_message: dict[int, list[InteractiveVersion]] = {}
    for item in superseded:
        by_message.setdefault(item.message_index, []).append(item)
    stubbed: list[InteractiveVersion] = []

    for message_index, items in by_message.items():
        message = original[message_index]
        content = message.get("content")
        if not isinstance(content, str):
            continue
        pieces: list[str] = []
        cursor = 0
        replaced: list[InteractiveVersion] = []
        for item in sorted(items, key=lambda entry: entry.start):
            stub = _stub(item)
            if len(stub) >= item.end - item.start:
                # A tiny document would grow: nobody benefits from a summary
                # that costs more than the source it hides.
                continue
            pieces.append(content[cursor : item.start])
            pieces.append(stub)
            cursor = item.end
            replaced.append(item)
        if not replaced:
            continue
        pieces.append(content[cursor:])
        messages[message_index] = {**message, "content": "".join(pieces)}
        stubbed.extend(replaced)

    if not stubbed:
        report["status"] = "nothing_superseded"
        report["reason"] = "blocks_too_small"
        return InteractiveHistoryResult(messages=original, report=report)

    chars_before = _total_chars(original)
    chars_after = _total_chars(messages)
    report["status"] = "compressed"
    report["stubbed_revisions"] = [
        {"id": item.id, "revision": item.revision, "html_chars": item.html_chars}
        for item in stubbed
    ]
    report["removed_fields"] = ["html"]
    report["chars_before"] = chars_before
    report["chars_after"] = chars_after
    report["chars_removed"] = chars_before - chars_after
    report["heuristic_tokens_before"] = _heuristic_tokens(chars_before)
    report["heuristic_tokens_after"] = _heuristic_tokens(chars_after)
    return InteractiveHistoryResult(messages=messages, report=report)
