"""System and interactive prompt loading for WeChat group generation.

Split from src/wechat.py — Phase 3 decoupling.
"""

from __future__ import annotations

from src.wechat_state import ROOT, _load_text


TEMPLATE_FILE = ROOT / "templates" / "wechat_update.md"
INTERACTIVE_TEMPLATE = ROOT / "templates" / "wechat_interactive_reply.md"


def load_system_prompt() -> str:
    return _load_text(
        TEMPLATE_FILE,
        "你是微信群聊生成器。根据本轮课后更新摘要，生成四位伙伴的群聊消息。输出格式：【角色名】\\n内容",
    )


def load_interactive_prompt() -> str:
    return _load_text(
        INTERACTIVE_TEMPLATE,
        "你是微信群聊互动生成器。根据用户消息和群聊历史生成回复。输出格式：【角色名】\\n内容",
    )
