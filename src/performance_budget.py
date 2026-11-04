from __future__ import annotations

from typing import Any
import re

from src.interactive_history import INTERACTIVE_CAPABILITY_MARKER


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


def interactive_reply_budget(
    default: int, messages: list[dict[str, Any]], user_input: str | None = None
) -> dict[str, Any]:
    """Select a bounded output size from this request, without a classifier call.

    Capability alone is not intent. This is a conservative initial policy, not
    a claim of optimal token sizes or semantic understanding of every request.
    """
    enabled = any(
        message.get("role") == "system"
        and INTERACTIVE_CAPABILITY_MARKER in str(message.get("content", ""))
        for message in messages
    )
    current = (
        user_input
        if user_input is not None
        else next(
            (
                str(m.get("content", ""))
                for m in reversed(messages)
                if m.get("role") == "user"
            ),
            "",
        )
    )
    text = current.lower()
    previous = next(
        (
            str(m.get("content", ""))
            for m in reversed(messages)
            if m.get("role") == "assistant"
        ),
        "",
    )
    existing = bool(
        re.search(
            r'```study-ui\s*\{[\s\S]{0,96000}?"type"\s*:\s*"interactive"', previous
        )
    )
    text_only = bool(
        re.search(
            r"(不要|不用|无需).{0,8}(界面|交互|图表|可视化)|只(用|要)?文字|text.only|no (ui|interactive)",
            text,
        )
    )
    explanation = bool(
        re.match(
            r"\s*(请|please )?(解释|为什么|如何|怎么|什么是|explain|how (to|does)|what is)",
            text,
        )
    )
    create = bool(
        re.search(
            r"(制作|生成|做|创建|构建|设计|实现|画|给我|想要|需要|提供|展示|演示|build|create|make|generate|show|give me).{0,45}(界面|交互|画布|图表|可视化|模拟器|仪表盘|canvas|svg|html|interactive|dashboard)",
            text,
        )
    )
    explore = bool(
        re.search(r"(让我|我想|可以|能否).{0,12}(拖动|调节|逐步运行|逐行执行)", text)
    )
    if re.search(r"(并|再|同时|and).{0,6}(做|制作|生成|create|build)", text):
        explanation = False
    modify = existing and bool(
        re.search(
            r"修改|调整|增加|添加|改成|改为|修复|重做|继续|完整版本|重新生成|按钮|滑块|change|modify|add|fix|continue",
            text,
        )
    )
    kind = "text"
    if enabled and not text_only and not explanation and (modify or create or explore):
        kind = "interactive"
        if re.search(
            r"多面板|多个视图|联动面板|复杂动画|multi.panel|dashboard", text
        ) or (modify and len(previous) > 16000):
            kind = "interactive_complex"
        elif not modify and re.search(
            r"简单|单个滑块|一个滑块|simple|single slider", text
        ):
            kind = "interactive_simple"
    ceiling = {
        "text": default,
        "interactive_simple": 3500,
        "interactive": 9000,
        "interactive_complex": 9000,
    }[kind]
    return {
        "kind": kind,
        "max_tokens": max(default, ceiling),
        "capability_enabled": enabled,
    }


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
