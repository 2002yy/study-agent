"""Render WeChat-style bubbles as lightweight HTML."""

from __future__ import annotations

import html
import re
from datetime import datetime

from src.ui.avatar import avatar_class, avatar_html

SPEAKER_TO_ROLE = {
    "三月七": "march7",
    "刻晴": "keqing",
    "纳西妲": "nahida",
    "流萤": "firefly",
    "用户": "user",
    "我": "user",
    "系统": "system",
}


def format_wechat_bubbles(text: str) -> str:
    """Convert role-tagged text into styled WeChat bubbles."""
    lines = text.splitlines()
    now = datetime.now().strftime("%m-%d %H:%M")
    result = [
        '<div class="wechat-card">',
        (
            '<div class="group-name">搭子小群 '
            f'<span style="font-weight:400;font-size:0.82rem;color:#a7aed4;">'
            f'· {now} 群聊视图</span></div>'
        ),
    ]

    buffer = ""
    speaker = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("---"):
            result.append('<div class="time-divider">新一轮群聊</div>')
            continue

        match = re.match(r"【(.+?)】\s*(.*)", stripped)
        if match:
            if buffer and speaker:
                _append_bubble(result, speaker, buffer)
            speaker = match.group(1)
            buffer = match.group(2) + "\n"
        elif speaker:
            buffer += stripped + "\n"

    if buffer and speaker:
        _append_bubble(result, speaker, buffer)

    result.append("</div>")
    return "\n".join(result)


def _append_bubble(result: list[str], speaker: str, text: str):
    role_id = _speaker_to_id(speaker)
    safe_speaker = html.escape(speaker)
    safe_text = html.escape(text.strip()).replace("\n", "<br/>")

    if not role_id:
        result.append(
            '<div class="wechat-msg system">'
            f'<div class="bubble system-bubble">[{safe_speaker}] {safe_text}</div>'
            "</div>"
        )
        return

    css_class = avatar_class(role_id)
    side_class = "right" if role_id == "user" else "left"
    avatar = avatar_html(role_id)
    result.append(f'<div class="wechat-msg {css_class} {side_class}">')
    if role_id == "user":
        result.append(
            f'<div class="sender"><span class="name">{safe_speaker}</span>{avatar}</div>'
        )
    else:
        result.append(
            f'<div class="sender">{avatar}<span class="name">{safe_speaker}</span></div>'
        )
    result.append(f'<div class="bubble">{safe_text}</div></div>')


def _speaker_to_id(speaker: str) -> str:
    return SPEAKER_TO_ROLE.get(speaker, "")
