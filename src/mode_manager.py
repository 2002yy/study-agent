from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from src.safe_writer import safe_write_text

ROOT = Path(__file__).resolve().parent.parent
INTERNAL_STATE = ROOT / "memory" / "internal_state.md"
INTERACTION_SETTINGS = ROOT / "memory" / "interaction_settings.md"
WECHAT_STATE = ROOT / "chat" / "wechat_state.md"


@dataclass
class RuntimeModes:
    memory_mode: str = "preview"
    route_mode: str = "auto_rule"
    debug_mode: bool = False
    safe_mode: bool = False
    current_version: str = "v0.7.2"
    active_task: str = "微信群联网搜索质量收口、正文提取增强与来源展示压缩"
    next_version: str = "v0.7.3"
    relationship_mode: str = "standard"
    wechat_mode: str = "unread_feedback"
    user_has_joined: bool = False
    first_reaction_done: bool = False
    memory_capture_enabled: bool = False
    memory_capture_mode: str = "manual"
    performance_mode: str = "standard"
    entry_mode: str = "wechat"

    @property
    def context_mode(self) -> str:
        if self.performance_mode == "fast":
            return "light"
        if self.performance_mode == "deep":
            return "deep"
        return "light"

    @property
    def allow_llm_router(self) -> bool:
        return self.performance_mode != "fast" and self.route_mode == "hybrid"

    @property
    def preferred_model(self) -> str | None:
        if self.performance_mode == "fast":
            return "flash"
        if self.performance_mode == "deep":
            return "pro"
        return None


def _parse_keyvalue(text: str, key: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"- {key}:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def _parse_bool(text: str, key: str) -> bool:
    return _parse_keyvalue(text, key).lower() == "true"


@st.cache_data(ttl=30)
def load_runtime_modes() -> RuntimeModes:
    modes = RuntimeModes()

    if INTERNAL_STATE.is_file():
        raw = INTERNAL_STATE.read_text(encoding="utf-8")
        mem = _parse_keyvalue(raw, "memory_mode")
        if mem in ("readonly", "preview", "confirm_write", "locked"):
            modes.memory_mode = mem
        route_mode = _parse_keyvalue(raw, "route_mode")
        if route_mode in ("auto_rule", "hybrid"):
            modes.route_mode = route_mode
        modes.debug_mode = _parse_bool(raw, "debug_mode")
        modes.safe_mode = _parse_bool(raw, "safe_mode")
        perf_mode = _parse_keyvalue(raw, "performance_mode")
        if perf_mode in ("fast", "standard", "deep"):
            modes.performance_mode = perf_mode
        entry_mode = _parse_keyvalue(raw, "entry_mode")
        if entry_mode in ("wechat", "single"):
            modes.entry_mode = entry_mode
        current_version = _parse_keyvalue(raw, "current_version")
        if current_version:
            modes.current_version = current_version
        active_task = _parse_keyvalue(raw, "active_task")
        if active_task:
            modes.active_task = active_task
        next_version = _parse_keyvalue(raw, "next_version")
        if next_version:
            modes.next_version = next_version

    if INTERACTION_SETTINGS.is_file():
        raw = INTERACTION_SETTINGS.read_text(encoding="utf-8")
        relationship_mode = _parse_keyvalue(raw, "relationship_mode")
        if relationship_mode in ("standard", "warm", "close"):
            modes.relationship_mode = relationship_mode

    if WECHAT_STATE.is_file():
        raw = WECHAT_STATE.read_text(encoding="utf-8")
        wechat_mode = _parse_keyvalue(raw, "mode")
        if wechat_mode in ("unread_feedback", "first_user_join", "interactive_group"):
            modes.wechat_mode = wechat_mode
        modes.user_has_joined = _parse_bool(raw, "user_has_joined_group")
        modes.first_reaction_done = _parse_bool(raw, "first_join_reaction_done")
        modes.memory_capture_enabled = _parse_bool(raw, "memory_capture_enabled")
        capture_mode = _parse_keyvalue(raw, "memory_capture_mode")
        if capture_mode:
            modes.memory_capture_mode = capture_mode

    return modes


def _write_keyvalue(path: Path, key: str, value: str) -> None:
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_write_text(path, f"# {path.stem}\n\n")

    lines = path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    found = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"- {key}:") or stripped.startswith(f"- {key} "):
            indent = line[: len(line) - len(line.lstrip())]
            new_lines.append(f"{indent}- {key}: {value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"- {key}: {value}")
    safe_write_text(path, "\n".join(new_lines) + "\n")


def _write_keyvalues(path: Path, updates: dict[str, str]) -> None:
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_write_text(path, f"# {path.stem}\n\n")

    lines = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    new_lines = []

    for line in lines:
        stripped = line.strip()
        replaced = False

        for key, value in list(remaining.items()):
            if stripped.startswith(f"- {key}:") or stripped.startswith(f"- {key} "):
                indent = line[: len(line) - len(line.lstrip())]
                new_lines.append(f"{indent}- {key}: {value}")
                remaining.pop(key)
                replaced = True
                break

        if not replaced:
            new_lines.append(line)

    for key, value in remaining.items():
        new_lines.append(f"- {key}: {value}")

    safe_write_text(path, "\n".join(new_lines) + "\n")


def _write_bool(path: Path, key: str, value: bool) -> None:
    _write_keyvalue(path, key, "true" if value else "false")


def update_interaction_mode(mode: str) -> None:
    if mode not in ("standard", "warm", "close"):
        raise ValueError(f"Invalid relationship_mode: {mode}")
    _write_keyvalue(INTERACTION_SETTINGS, "relationship_mode", mode)


def update_wechat_join_state(
    user_has_joined: bool, first_reaction_done: bool, mode: str
) -> None:
    if mode not in ("unread_feedback", "first_user_join", "interactive_group"):
        raise ValueError(f"Invalid wechat_mode: {mode}")

    _write_keyvalues(
        WECHAT_STATE,
        {
            "user_has_joined_group": "true" if user_has_joined else "false",
            "first_join_reaction_done": "true" if first_reaction_done else "false",
            "mode": mode,
        },
    )


def update_memory_capture(enabled: bool, capture_mode: str = "manual") -> None:
    _write_keyvalues(
        WECHAT_STATE,
        {
            "memory_capture_enabled": "true" if enabled else "false",
            "memory_capture_mode": capture_mode,
        },
    )


def is_memory_write_allowed(modes: RuntimeModes) -> bool:
    if modes.safe_mode:
        return False
    return modes.memory_mode == "confirm_write"


def set_memory_mode(mode: str) -> None:
    if mode not in ("readonly", "preview", "confirm_write", "locked"):
        raise ValueError(f"Invalid memory_mode: {mode}")
    _write_keyvalue(INTERNAL_STATE, "memory_mode", mode)


def run_with_confirm_write(callback):
    old = load_runtime_modes().memory_mode
    set_memory_mode("confirm_write")
    try:
        return callback()
    finally:
        set_memory_mode(old)


def update_debug_mode(enabled: bool) -> None:
    _write_bool(INTERNAL_STATE, "debug_mode", enabled)


def update_safe_mode(enabled: bool) -> None:
    _write_bool(INTERNAL_STATE, "safe_mode", enabled)


def update_performance_mode(mode: str) -> None:
    if mode not in ("fast", "standard", "deep"):
        raise ValueError(f"Invalid performance_mode: {mode}")
    _write_keyvalue(INTERNAL_STATE, "performance_mode", mode)


def update_entry_mode(mode: str) -> None:
    if mode not in ("wechat", "single"):
        raise ValueError(f"Invalid entry_mode: {mode}")
    _write_keyvalue(INTERNAL_STATE, "entry_mode", mode)
