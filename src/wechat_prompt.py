"""System and interactive prompt loading for WeChat group generation.

Self-contained module — no dependency on wechat_state or wechat_generator.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.text_utils import file_signature

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_FILE = ROOT / "templates" / "wechat_update.md"
INTERACTIVE_TEMPLATE = ROOT / "templates" / "wechat_interactive_reply.md"


@lru_cache(maxsize=32)
def _load_prompt_cached(path_str: str, signature: str, default: str) -> str:
    path = Path(path_str)
    if not path.is_file():
        return default
    return path.read_text(encoding="utf-8").strip()


def load_system_prompt() -> str:
    return _load_prompt_cached(
        str(TEMPLATE_FILE),
        file_signature(TEMPLATE_FILE),
        "你是微信群聊生成器。根据本轮课后更新摘要，生成四位伙伴的群聊消息。输出格式：【角色名】\\n内容",
    )


def load_interactive_prompt() -> str:
    return _load_prompt_cached(
        str(INTERACTIVE_TEMPLATE),
        file_signature(INTERACTIVE_TEMPLATE),
        "你是微信群聊互动生成器。根据用户消息和群聊历史生成回复。输出格式：【角色名】\\n内容",
    )
