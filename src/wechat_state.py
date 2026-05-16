"""WeChat group state, file I/O, and group lifecycle management.

Split from src/wechat.py — Phase 2 decoupling.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from src.mode_manager import load_runtime_modes, update_wechat_join_state
from src.safe_writer import append_text_safely, safe_write_text
from src.text_utils import file_signature
from src.wechat_format import (
    _ensure_all_roles_reply,
    _is_legacy_opening,
    _message_blocks,
)


# ── File paths ────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
GROUP_FILE = ROOT / "chat" / "wechat_group.md"
UNREAD_FILE = ROOT / "chat" / "wechat_unread.md"
STATE_FILE = ROOT / "chat" / "wechat_state.md"
ARCHIVE_DIR = ROOT / "chat" / "archive"


# ── File I/O helpers ──────────────────────────────────────────────────


@lru_cache(maxsize=32)
def _load_wechat_text_cached(path_str: str, signature: str) -> str:
    path = Path(path_str)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _load_text(path: Path, default: str = "") -> str:
    if not path.is_file():
        return default
    return _load_wechat_text_cached(str(path), file_signature(path))


# ── Group / unread read helpers ───────────────────────────────────────


def read_wechat_unread() -> str:
    return _load_text(UNREAD_FILE)


def read_wechat_group() -> str:
    return _load_text(GROUP_FILE)


def has_wechat_unread() -> bool:
    unread = read_wechat_unread()
    return bool(unread and "暂无未读消息" not in unread and "暂无未读" not in unread)


def has_wechat_group_started() -> bool:
    content = read_wechat_group()
    if not _message_blocks(content):
        return False
    if _is_legacy_opening(content):
        return False
    return True


# ── Group lifecycle ───────────────────────────────────────────────────


def start_wechat_group_with_opening(content: str) -> str:
    normalized = _ensure_all_roles_reply(content)
    safe_write_text(GROUP_FILE, normalized + "\n")
    safe_write_text(UNREAD_FILE, "# 未读消息\n\n> 暂无未读消息。\n")
    update_wechat_join_state(
        user_has_joined=False,
        first_reaction_done=False,
        mode="interactive_group",
    )
    return normalized


def append_new_wechat_feedback(content: str) -> None:
    if not content.strip():
        return
    normalized = _ensure_all_roles_reply(content)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    version = load_runtime_modes().current_version
    thread_id = uuid4().hex[:8]
    header = (
        "# 微信群未读消息\n\n"
        f"- 生成时间: {now}\n"
        "- 状态: unread\n"
        f"- 阶段: {version}\n"
        f"- thread_id: {thread_id}\n\n---\n\n"
    )
    safe_write_text(UNREAD_FILE, header + normalized + "\n")
    append_text_safely(GROUP_FILE, normalized + "\n")
    update_wechat_join_state(
        user_has_joined=False,
        first_reaction_done=False,
        mode="unread_feedback",
    )


def append_system_group_note(content: str) -> None:
    if not content.strip():
        return
    current = read_wechat_group()
    prefix = "" if not current.strip() else "\n\n"
    append_text_safely(GROUP_FILE, prefix + content.strip() + "\n")


def append_interactive_group_reply(content: str) -> None:
    if not content.strip():
        return
    normalized = _ensure_all_roles_reply(content)
    append_text_safely(GROUP_FILE, normalized + "\n")
    unread = read_wechat_unread()
    if has_wechat_unread():
        safe_write_text(UNREAD_FILE, unread + "\n\n" + normalized + "\n")
    else:
        safe_write_text(UNREAD_FILE, normalized + "\n")


def append_wechat_messages(content: str) -> None:
    append_new_wechat_feedback(content)


def clear_wechat_unread() -> None:
    safe_write_text(UNREAD_FILE, "# 未读消息\n\n> 暂无未读消息。\n")


def reset_wechat_group() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if GROUP_FILE.is_file():
        old_content = GROUP_FILE.read_text(encoding="utf-8")
        archive_path = ARCHIVE_DIR / f"wechat_group_{ts}.md"
        safe_write_text(archive_path, old_content)
        safe_write_text(GROUP_FILE, "")

    if UNREAD_FILE.is_file():
        safe_write_text(UNREAD_FILE, "# 未读消息\n\n> 暂无未读消息。\n")

    update_wechat_join_state(False, False, "interactive_group")


def mark_wechat_read() -> None:
    clear_wechat_unread()


# ── State management ──────────────────────────────────────────────────


def read_wechat_state() -> dict:
    modes = load_runtime_modes()
    return {
        "user_has_joined": modes.user_has_joined,
        "first_join_done": modes.first_reaction_done,
        "mode": modes.wechat_mode,
    }


def write_wechat_state(user_has_joined: bool, first_join_done: bool, mode: str):
    update_wechat_join_state(user_has_joined, first_join_done, mode)


def append_user_group_message(user_text: str):
    ts = datetime.now().strftime("%m-%d %H:%M")
    message = f"\n\n【用户】 {ts}\n{user_text}"
    if GROUP_FILE.is_file():
        current = GROUP_FILE.read_text(encoding="utf-8")
        safe_write_text(GROUP_FILE, current + message)
    else:
        safe_write_text(GROUP_FILE, f"# 学习伙伴群\n{message}")


# ── Search / summarize ────────────────────────────────────────────────


def search_wechat(keyword: str, max_results: int = 10) -> list[dict]:
    content = read_wechat_group()
    if not content:
        return []
    results = []
    for speaker, text in _message_blocks(content):
        if keyword.lower() in text.lower():
            results.append({"speaker": speaker, "text": text.strip()[:150]})
            if len(results) >= max_results:
                break
    return results


def summarize_wechat(max_chars: int = 500) -> str:
    content = read_wechat_group()
    if not content:
        return "暂无群聊记录"
    lines = content.splitlines()
    dividers = [
        i for i, line in enumerate(lines) if "---" in line or "课后反馈" in line
    ]
    start = dividers[-1] if dividers else max(0, len(lines) - 60)
    recent = "\n".join(lines[start:])
    return recent[:max_chars] + ("..." if len(recent) > max_chars else "")


def count_wechat_messages(content: str) -> int:
    if not content.strip():
        return 0
    return len(_message_blocks(content))
