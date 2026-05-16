from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from src.safe_writer import safe_write_text
from src.session_store import SessionMeta
from src.log_utils import get_logger

logger = get_logger()

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs" / "sessions"
CURRENT_DIR = ROOT / "logs" / "current"

_state: dict[str, dict] = {}
_FLUSH_INTERVALS = {
    "fast": 4,
    "standard": 2,
    "deep": 2,
}


def _ensure_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    CURRENT_DIR.mkdir(parents=True, exist_ok=True)


def init_session() -> str:
    sid = uuid.uuid4().hex[:12]
    _state[sid] = {
        "entries": [],
        "meta": SessionMeta(),
        "flushed_count": 0,
    }
    return sid


def get_or_create_session(session_id: str) -> dict:
    if session_id not in _state:
        _state[session_id] = {
            "entries": [],
            "meta": SessionMeta(),
            "flushed_count": 0,
        }
    return _state[session_id]


def set_after_session_status(session_id: str, status: str) -> None:
    get_or_create_session(session_id)["meta"].after_session_status = status


def set_wechat_status(session_id: str, status: str) -> None:
    get_or_create_session(session_id)["meta"].wechat_status = status


def set_wechat_unread_cleared(session_id: str) -> None:
    get_or_create_session(session_id)["meta"].wechat_unread_cleared = True


def set_wechat_interactive(session_id: str, status: str) -> None:
    get_or_create_session(session_id)["meta"].wechat_interactive = status


def set_wechat_memory_capture(session_id: str, status: str) -> None:
    get_or_create_session(session_id)["meta"].wechat_memory_capture = status


def set_wechat_memory_candidates(session_id: str, status: str) -> None:
    get_or_create_session(session_id)["meta"].wechat_memory_candidates = status


def set_interaction_mode(session_id: str, mode: str) -> None:
    get_or_create_session(session_id)["meta"].interaction_mode = mode


def log(
    session_id: str,
    role: str,
    mode: str,
    model: str,
    user_input: str,
    agent_reply: str,
    memory_enabled: bool = False,
    route_info: dict | None = None,
) -> None:
    get_or_create_session(session_id)["entries"].append(
        {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "role": role,
            "mode": mode,
            "model": model,
            "memory": memory_enabled,
            "route": route_info,
            "user": user_input,
            "agent": agent_reply,
        }
    )


def _pending_entry_count(sess: dict) -> int:
    return len(sess["entries"]) - sess["flushed_count"]


def _flush_interval_for_mode(
    performance_mode: str,
    debug_mode: bool = False,
) -> int:
    if debug_mode:
        return 1
    return _FLUSH_INTERVALS.get(performance_mode, _FLUSH_INTERVALS["standard"])


def should_flush_current_session(
    session_id: str,
    performance_mode: str = "standard",
    debug_mode: bool = False,
    force: bool = False,
) -> bool:
    sess = get_or_create_session(session_id)
    pending = _pending_entry_count(sess)
    if pending <= 0:
        return False
    if force:
        return True
    return pending >= _flush_interval_for_mode(
        performance_mode,
        debug_mode=debug_mode,
    )


def _current_file(session_id: str) -> Path:
    return CURRENT_DIR / f"{session_id}.md"


def flush_current_session(
    session_id: str,
    performance_mode: str = "standard",
    debug_mode: bool = False,
    force: bool = False,
) -> bool:
    sess = get_or_create_session(session_id)
    entries = sess["entries"]
    if not entries:
        return False

    flushed = sess["flushed_count"]
    if flushed >= len(entries):
        return False
    if not should_flush_current_session(
        session_id,
        performance_mode=performance_mode,
        debug_mode=debug_mode,
        force=force,
    ):
        return False

    _ensure_dir()
    current_file = _current_file(session_id)
    lines = []
    for entry in entries[flushed:]:
        lines.append(f"[{entry['time']}] ({entry['role']}/{entry['mode']}/{entry['model']})")
        lines.append(f"User: {entry['user'][:100]}")
        lines.append(f"Agent: {entry['agent'][:200]}")
        lines.append("")
    existing = ""
    if current_file.exists() and flushed > 0:
        existing = current_file.read_text(encoding="utf-8")

    chunk = "\n".join(lines)
    if chunk:
        chunk += "\n"

    safe_write_text(current_file, existing + chunk)
    sess["flushed_count"] = len(entries)
    return True


def save(session_id: str) -> str:
    if session_id not in _state:
        return ""
    sess = _state[session_id]
    entries = sess["entries"]
    meta = sess["meta"]
    if not entries:
        return ""

    flush_current_session(session_id, force=True)
    _ensure_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    first = entries[0]
    filepath = LOG_DIR / f"{timestamp}_session_{session_id}_{first['role']}_{first['model']}.md"

    lines = [f"# Session {timestamp}\n"]
    lines.append(f"- session_id: {session_id}")
    lines.append(f"- after_session: {meta.after_session_status}")
    lines.append(f"- wechat_status: {meta.wechat_status}")
    lines.append(f"- wechat_interactive: {meta.wechat_interactive}")
    lines.append(f"- wechat_memory_capture: {meta.wechat_memory_capture}")
    if meta.wechat_memory_candidates != "none":
        lines.append(f"- wechat_memory_candidates: {meta.wechat_memory_candidates}")
    lines.append(f"- interaction_mode: {meta.interaction_mode}")
    if meta.wechat_unread_cleared:
        lines.append("- wechat_unread: cleared")
    lines.append("")

    try:
        from src.mode_manager import load_runtime_modes

        runtime = load_runtime_modes()
        lines.append("## Runtime Modes")
        lines.append(f"- relationship_mode: {runtime.relationship_mode}")
        lines.append(f"- wechat_mode: {runtime.wechat_mode}")
        lines.append(f"- user_has_joined_group: {'true' if runtime.user_has_joined else 'false'}")
        lines.append(f"- memory_capture_enabled: {'true' if runtime.memory_capture_enabled else 'false'}")
        lines.append(f"- memory_mode: {runtime.memory_mode}")
        lines.append(f"- route_mode: {runtime.route_mode}")
        lines.append(f"- performance_mode: {runtime.performance_mode}")
        lines.append(f"- debug_mode: {'true' if runtime.debug_mode else 'false'}")
        lines.append(f"- safe_mode: {'true' if runtime.safe_mode else 'false'}")
        lines.append("")
    except Exception:
        logger.warning("Failed to load runtime modes for session log", exc_info=True)

    for entry in entries:
        lines.append(f"## {entry['time']}")
        lines.append(f"- role: {entry['role']}")
        lines.append(f"- mode: {entry['mode']}")
        lines.append(f"- model: {entry['model']}")
        if entry.get("route"):
            route = entry["route"]
            lines.append(f"- resolved_role: {route.get('role', '')}")
            lines.append(f"- resolved_mode: {route.get('mode', '')}")
            lines.append(f"- resolved_model: {route.get('model_profile', '')}")
            lines.append(f"- reason: {route.get('reason', '')}")
        lines.append("")
        lines.append(f"**User**\n{entry['user']}\n")
        lines.append(f"**Agent**\n{entry['agent']}\n")
        lines.append("---\n")

    safe_write_text(filepath, "\n".join(lines))

    sess["entries"].clear()
    sess["flushed_count"] = 0
    meta.reset()
    try:
        current = _current_file(session_id)
        if current.exists():
            os.remove(current)
    except Exception:
        logger.warning("Failed to clean up session file", exc_info=True)

    return str(filepath)
