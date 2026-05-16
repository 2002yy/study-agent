"""Pure text/formatting utilities extracted from wechat.py."""

from __future__ import annotations

import re

# ── Constants ──────────────────────────────────────────────────────────

STYLE_PROMPTS = {
    "简短": "\n【风格要求】每条消息 1-2 句，每位不超过 60 字，总长度不超过 400 字。",
    "标准": "\n【风格要求】每条消息 2-3 句，每位不超过 100 字，总长度不超过 600 字。",
    "稍微有温度": "\n【风格要求】每条消息 2-4 句，每位不超过 120 字，总长度不超过 800 字。",
}

WECHAT_ROLE_ORDER = ["三月七", "刻晴", "纳西妲", "流萤"]

WECHAT_BLOCK_PATTERN = re.compile(r"【(.+?)】\s*(.+?)(?=\n【|\Z)", re.DOTALL)

WECHAT_MISSING_ROLE_FALLBACKS = {
    "三月七": "我这边也接住啦，这句我听到了。那我先把气氛接上，我们继续往下聊。",
    "刻晴": "我补一句重点：先把你刚刚提到的核心问题记住，接下来按最关键的一步继续推进就好。",
    "纳西妲": "从这个角度看，你刚刚那句话其实已经给了线索。顺着它往下想，通常就能把眼前这一步理清一些。",
    "流萤": "我也在。别急，我们就顺着你刚刚这句话慢慢接下去，一点点把现在的感觉和事情放稳。",
}

ROLE_ID_TO_NAME = {
    "auto": "自动",
    "march7": "三月七",
    "keqing": "刻晴",
    "nahida": "纳西妲",
    "firefly": "流萤",
}

PERFORMANCE_STYLE_HINTS = {
    "fast": "整体更轻、更快、更短，每位角色 1 到 2 句即可。",
    "standard": "整体自然平衡，每位角色 1 到 3 句。",
    "deep": "可以稍微多一点层次，但仍然保持轻盈，不要写成长文。",
}

LEGACY_OPENING_MARKERS = (
    "要是你正好看到",
    "就把这里当成轻松一点的学习搭子小群也行",
)


# ── WeChat message block helpers ──────────────────────────────────────


def _message_blocks(content: str) -> list[tuple[str, str]]:
    return [
        (speaker.strip(), text.strip())
        for speaker, text in WECHAT_BLOCK_PATTERN.findall(content)
    ]


def _format_role_blocks(blocks: list[tuple[str, str]]) -> str:
    return "\n\n".join(
        f"【{speaker}】\n{text.strip()}" for speaker, text in blocks if text.strip()
    ).strip()


def _ensure_all_roles_reply(content: str) -> str:
    blocks = _message_blocks(content)
    if not blocks:
        return _format_role_blocks(
            [
                (speaker, WECHAT_MISSING_ROLE_FALLBACKS[speaker])
                for speaker in WECHAT_ROLE_ORDER
            ]
        )

    by_speaker: dict[str, list[str]] = {}
    for speaker, text in blocks:
        if speaker not in WECHAT_ROLE_ORDER:
            continue
        by_speaker.setdefault(speaker, []).append(text.strip())

    normalized_blocks: list[tuple[str, str]] = []
    for speaker in WECHAT_ROLE_ORDER:
        parts = [part for part in by_speaker.get(speaker, []) if part]
        if parts:
            normalized_blocks.append((speaker, "\n".join(parts)))
        else:
            normalized_blocks.append((speaker, WECHAT_MISSING_ROLE_FALLBACKS[speaker]))
    return _format_role_blocks(normalized_blocks)


def _is_legacy_opening(content: str) -> bool:
    if "【用户】" in content:
        return False
    return all(marker in content for marker in LEGACY_OPENING_MARKERS)
