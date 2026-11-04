from __future__ import annotations

from typing import Any


def normalize_performance_mode(mode: str | None) -> str:
    if mode in {"fast", "standard", "deep"}:
        return mode
    return "standard"


def chat_max_tokens(mode: str | None) -> int:
    mode = normalize_performance_mode(mode)
    return {
        "fast": 700,
        "standard": 1100,
        "deep": 1600,
    }[mode]


def interactive_reply_max_tokens(default: int, messages: list[dict[str, Any]]) -> int:
    """Allow complete small UIs when the current system capability enables them.

    User/history text does not opt in. The same spend guard reserves this output
    ceiling before sending; no extra model call or automatic continuation.
    """
    enabled = any(
        message.get("role") == "system"
        and "【自由交互界面 v1】" in str(message.get("content", ""))
        for message in messages
    )
    return max(default, 6000) if enabled else default


def wechat_history_lines(mode: str | None) -> int:
    mode = normalize_performance_mode(mode)
    return {
        "fast": 16,
        "standard": 28,
        "deep": 40,
    }[mode]


def wechat_reply_max_tokens(mode: str | None) -> int:
    mode = normalize_performance_mode(mode)
    return {
        "fast": 520,
        "standard": 760,
        "deep": 1050,
    }[mode]


def wechat_opening_max_tokens(mode: str | None) -> int:
    mode = normalize_performance_mode(mode)
    return {
        "fast": 420,
        "standard": 620,
        "deep": 850,
    }[mode]


def news_digest_max_tokens(mode: str | None) -> int:
    mode = normalize_performance_mode(mode)
    return {
        "fast": 650,
        "standard": 950,
        "deep": 1300,
    }[mode]


def news_discussion_max_tokens(mode: str | None) -> int:
    mode = normalize_performance_mode(mode)
    return {
        "fast": 520,
        "standard": 760,
        "deep": 1000,
    }[mode]
