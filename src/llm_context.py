"""Deterministic working-context compression for the model-directed loop.

Every round appends its tool results to the transcript, so a long research run
sends all previously read page bodies again on each paid call. OpenCode's
threshold compaction and Codex's history compaction solve the same problem.
This implementation stays deterministic:

* the original system/user messages are never rewritten;
* the transcript is compressed only after it crosses the caller's budget;
* the most recent rounds keep their results verbatim;
* older tool results become a stable summary (url, status, size, digest-sized
  excerpt) that still answers "what did this call return";
* superseded research-state blocks collapse to a one-line note.

Raw results are already durable in the run trace, so shrinking the transcript
does not lose evidence.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

COMPRESSED_NOTE = "【较早的工具结果已压缩；完整正文保存在研究记录中】"
STATE_NOTE = "【早期研究状态已由最新状态块替代】"
_SUMMARY_KEYS = (
    "ok",
    "status",
    "url",
    "final_url",
    "title",
    "method",
    "chars",
    "chars_total",
    "error",
    "reason",
    "adequacy_reason",
    "truncated",
)


def transcript_chars(transcript: Sequence[dict[str, Any]]) -> int:
    return sum(len(str(message.get("content") or "")) for message in transcript)


def _summarize(content: str, excerpt_chars: int) -> str:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return json.dumps(
            {"_compressed": True, "excerpt": str(content)[:excerpt_chars]},
            ensure_ascii=False,
        )
    if not isinstance(payload, dict):
        return json.dumps(
            {"_compressed": True, "excerpt": str(content)[:excerpt_chars]},
            ensure_ascii=False,
        )
    summary: dict[str, Any] = {
        key: payload[key] for key in _SUMMARY_KEYS if key in payload
    }
    results = payload.get("results")
    if isinstance(results, list):
        summary["results"] = [
            {
                "title": str(item.get("title") or "")[:120],
                "url": str(item.get("url") or item.get("link") or "")[:300],
            }
            for item in results[:5]
            if isinstance(item, dict)
        ]
        summary["results_total"] = len(results)
    errors = payload.get("provider_errors")
    if isinstance(errors, list):
        summary["provider_errors"] = [str(value)[:200] for value in errors[:3]]
    body = payload.get("content") or payload.get("readme")
    if isinstance(body, str) and body:
        summary["content_chars"] = len(body)
        if excerpt_chars > 0:
            summary["excerpt"] = body[:excerpt_chars]
    summary["_compressed"] = True
    return json.dumps(summary, ensure_ascii=False)


def _round_tags(transcript: Sequence[dict[str, Any]]) -> list[int]:
    """Assign each message the 1-based tool round it belongs to."""

    tags: list[int] = []
    round_index = 0
    for message in transcript:
        if message.get("role") == "assistant" and message.get("tool_calls"):
            round_index += 1
        tags.append(round_index)
    return tags


def _is_compressed(content: object) -> bool:
    text = str(content or "")
    return '"_compressed": true' in text or '"_compressed":true' in text


def compress_working_context(
    transcript: list[dict[str, Any]],
    *,
    completed_rounds: int,
    budget: int,
    keep_rounds: int = 2,
    per_result_chars: int = 700,
    state_indexes: Sequence[int] = (),
) -> dict[str, int]:
    """Compress in place; returns before/after sizes for diagnostics."""

    before = transcript_chars(transcript)
    if budget <= 0 or before <= budget:
        return {"before": before, "after": before, "compressed": 0}
    tags = _round_tags(transcript)
    # The newest state block stays authoritative; older snapshots are noise.
    for index in list(state_indexes)[:-1]:
        if 0 <= index < len(transcript):
            transcript[index]["content"] = STATE_NOTE
    cutoff = max(0, completed_rounds - max(1, keep_rounds))
    compressed = 0
    for index, message in enumerate(transcript):
        if message.get("role") != "tool":
            continue
        if tags[index] > cutoff or _is_compressed(message.get("content")):
            continue
        message["content"] = _summarize(str(message.get("content") or ""), per_result_chars)
        compressed += 1
    # A run with many long pages can still exceed the budget after one pass.
    # Keep the metadata and drop the excerpt rather than growing the request.
    if transcript_chars(transcript) > budget:
        for index, message in enumerate(transcript):
            if message.get("role") != "tool" or tags[index] > cutoff:
                continue
            if not _is_compressed(message.get("content")):
                continue
            try:
                payload = json.loads(str(message.get("content") or ""))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and payload.pop("excerpt", None) is not None:
                message["content"] = json.dumps(payload, ensure_ascii=False)
    after = transcript_chars(transcript)
    return {"before": before, "after": after, "compressed": compressed}


__all__ = [
    "COMPRESSED_NOTE",
    "STATE_NOTE",
    "compress_working_context",
    "transcript_chars",
]
