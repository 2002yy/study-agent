from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st
import yaml

from src.safe_writer import safe_write_text
from src.log_utils import get_logger

logger = get_logger()

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
RUNTIME_STATE = CONFIG_DIR / "runtime_state.yaml"
INTERNAL_STATE = ROOT / "memory" / "internal_state.md"
INTERACTION_SETTINGS = ROOT / "memory" / "interaction_settings.md"
WECHAT_STATE = ROOT / "chat" / "wechat_state.md"


@dataclass
class RuntimeModes:
    memory_mode: str = "preview"
    route_mode: str = "auto_rule"
    debug_mode: bool = False
    safe_mode: bool = False
    current_version: str = "v0.8.0"
    active_task: str = "文档同步 + UI 中文标签 + 性能预算 + 状态模型 + 工程收口"
    next_version: str = "v0.8.1"
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
        return build_runtime_profile(self).context_mode

    @property
    def allow_llm_router(self) -> bool:
        return build_runtime_profile(self).allow_llm_router

    @property
    def preferred_model(self) -> str | None:
        return build_runtime_profile(self).preferred_model

    @property
    def profile(self) -> "RuntimeProfile":
        return build_runtime_profile(self)


@dataclass(frozen=True)
class RuntimeProfile:
    """Effective runtime permissions derived from user-facing modes."""

    memory_write_allowed: bool
    memory_write_reason: str
    allow_llm_router: bool
    llm_router_reason: str
    allow_article_network_read: bool
    article_network_read_reason: str
    preferred_model: str | None
    context_mode: str
    performance_mode: str
    route_mode: str
    memory_mode: str
    safe_mode: bool


def build_runtime_profile(modes: RuntimeModes) -> RuntimeProfile:
    if modes.safe_mode:
        memory_write_allowed = False
        memory_write_reason = "safe_mode"
    elif modes.memory_mode == "confirm_write":
        memory_write_allowed = True
        memory_write_reason = "confirm_write"
    else:
        memory_write_allowed = False
        memory_write_reason = modes.memory_mode

    if modes.performance_mode == "fast":
        allow_llm_router = False
        llm_router_reason = "fast_mode"
        preferred_model = "flash"
        context_mode = "fast"
    elif modes.route_mode == "hybrid":
        allow_llm_router = True
        llm_router_reason = "hybrid"
        preferred_model = "pro" if modes.performance_mode == "deep" else None
        context_mode = "deep" if modes.performance_mode == "deep" else "light"
    else:
        allow_llm_router = False
        llm_router_reason = modes.route_mode
        preferred_model = "pro" if modes.performance_mode == "deep" else None
        context_mode = "deep" if modes.performance_mode == "deep" else "light"

    if modes.safe_mode:
        allow_article_network_read = False
        article_network_read_reason = "safe_mode"
    else:
        allow_article_network_read = True
        article_network_read_reason = "allowed"

    return RuntimeProfile(
        memory_write_allowed=memory_write_allowed,
        memory_write_reason=memory_write_reason,
        allow_llm_router=allow_llm_router,
        llm_router_reason=llm_router_reason,
        allow_article_network_read=allow_article_network_read,
        article_network_read_reason=article_network_read_reason,
        preferred_model=preferred_model,
        context_mode=context_mode,
        performance_mode=modes.performance_mode,
        route_mode=modes.route_mode,
        memory_mode=modes.memory_mode,
        safe_mode=modes.safe_mode,
    )


@dataclass(frozen=True)
class RuntimeConfigLoadResult:
    """Validated runtime config plus non-fatal schema warnings."""

    state: dict[str, Any]
    source: str
    warnings: tuple[str, ...] = ()


_RUNTIME_STATE_SCHEMA: dict[str, dict[str, dict[str, Any]]] = {
    "version": {
        "current": {"type": str},
        "next": {"type": str},
        "active_task": {"type": str},
    },
    "runtime": {
        "entry_mode": {"type": str, "choices": {"wechat", "single"}},
        "performance_mode": {"type": str, "choices": {"fast", "standard", "deep"}},
        "route_mode": {"type": str, "choices": {"auto_rule", "hybrid"}},
        "memory_mode": {
            "type": str,
            "choices": {"readonly", "preview", "confirm_write", "locked"},
        },
        "debug_mode": {"type": bool},
        "safe_mode": {"type": bool},
    },
    "interaction": {
        "relationship_mode": {"type": str, "choices": {"standard", "warm", "close"}},
    },
    "wechat": {
        "mode": {
            "type": str,
            "choices": {
                "unread_feedback",
                "first_user_join",
                "interactive_group",
            },
        },
        "user_has_joined_group": {"type": bool},
        "first_join_reaction_done": {"type": bool},
        "memory_capture_enabled": {"type": bool},
        "memory_capture_mode": {"type": str, "choices": {"manual", "auto"}},
    },
}


def _parse_keyvalue(text: str, key: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"- {key}:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def _parse_bool(text: str, key: str) -> bool:
    return _parse_keyvalue(text, key).lower() == "true"


def _default_runtime_state_dict() -> dict[str, Any]:
    defaults = RuntimeModes()
    return {
        "version": {
            "current": defaults.current_version,
            "next": defaults.next_version,
            "active_task": defaults.active_task,
        },
        "runtime": {
            "entry_mode": defaults.entry_mode,
            "performance_mode": defaults.performance_mode,
            "route_mode": defaults.route_mode,
            "memory_mode": defaults.memory_mode,
            "debug_mode": defaults.debug_mode,
            "safe_mode": defaults.safe_mode,
        },
        "interaction": {
            "relationship_mode": defaults.relationship_mode,
        },
        "wechat": {
            "mode": defaults.wechat_mode,
            "user_has_joined_group": defaults.user_has_joined,
            "first_join_reaction_done": defaults.first_reaction_done,
            "memory_capture_enabled": defaults.memory_capture_enabled,
            "memory_capture_mode": defaults.memory_capture_mode,
        },
    }


def _read_md_state_migration() -> dict[str, Any]:
    data = _default_runtime_state_dict()

    if INTERNAL_STATE.is_file():
        raw = INTERNAL_STATE.read_text(encoding="utf-8")
        mem = _parse_keyvalue(raw, "memory_mode")
        if mem in ("readonly", "preview", "confirm_write", "locked"):
            data["runtime"]["memory_mode"] = mem
        route_mode = _parse_keyvalue(raw, "route_mode")
        if route_mode in ("auto_rule", "hybrid"):
            data["runtime"]["route_mode"] = route_mode
        data["runtime"]["debug_mode"] = _parse_bool(raw, "debug_mode")
        data["runtime"]["safe_mode"] = _parse_bool(raw, "safe_mode")
        perf_mode = _parse_keyvalue(raw, "performance_mode")
        if perf_mode in ("fast", "standard", "deep"):
            data["runtime"]["performance_mode"] = perf_mode
        entry_mode = _parse_keyvalue(raw, "entry_mode")
        if entry_mode in ("wechat", "single"):
            data["runtime"]["entry_mode"] = entry_mode
        current_version = _parse_keyvalue(raw, "current_version")
        if current_version:
            data["version"]["current"] = current_version
        next_version = _parse_keyvalue(raw, "next_version")
        if next_version:
            data["version"]["next"] = next_version
        active_task = _parse_keyvalue(raw, "active_task")
        if active_task:
            data["version"]["active_task"] = active_task

    if INTERACTION_SETTINGS.is_file():
        raw = INTERACTION_SETTINGS.read_text(encoding="utf-8")
        relationship_mode = _parse_keyvalue(raw, "relationship_mode")
        if relationship_mode in ("standard", "warm", "close"):
            data["interaction"]["relationship_mode"] = relationship_mode

    if WECHAT_STATE.is_file():
        raw = WECHAT_STATE.read_text(encoding="utf-8")
        wechat_mode = _parse_keyvalue(raw, "mode")
        if wechat_mode in ("unread_feedback", "first_user_join", "interactive_group"):
            data["wechat"]["mode"] = wechat_mode
        data["wechat"]["user_has_joined_group"] = _parse_bool(
            raw, "user_has_joined_group"
        )
        data["wechat"]["first_join_reaction_done"] = _parse_bool(
            raw, "first_join_reaction_done"
        )
        data["wechat"]["memory_capture_enabled"] = _parse_bool(
            raw, "memory_capture_enabled"
        )
        capture_mode = _parse_keyvalue(raw, "memory_capture_mode")
        if capture_mode:
            data["wechat"]["memory_capture_mode"] = capture_mode

    return data


def _coerce_runtime_value(
    path: str,
    value: Any,
    default: Any,
    rule: dict[str, Any],
    warnings: list[str],
) -> Any:
    expected_type = rule["type"]
    choices = rule.get("choices")

    if expected_type is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            warnings.append(f"{path}: coerced string boolean to bool")
            return value.strip().lower() == "true"
        warnings.append(f"{path}: expected bool; using default {default!r}")
        return default

    if expected_type is str:
        if not isinstance(value, str):
            warnings.append(f"{path}: expected string; using default {default!r}")
            return default
        value = value.strip()
        if choices and value not in choices:
            allowed = ", ".join(sorted(choices))
            warnings.append(
                f"{path}: invalid value {value!r}; expected one of {allowed}; "
                f"using default {default!r}"
            )
            return default
        return value

    return value


def validate_runtime_state(
    data: dict[str, Any] | None,
    *,
    source: str = "runtime_state.yaml",
) -> RuntimeConfigLoadResult:
    """Validate and normalize runtime state without failing the UI rerun."""
    normalized = _default_runtime_state_dict()
    warnings: list[str] = []
    if not isinstance(data, dict):
        warnings.append(f"{source}: expected mapping at root; using defaults")
        return RuntimeConfigLoadResult(normalized, source, tuple(warnings))

    for section in sorted(set(data) - set(_RUNTIME_STATE_SCHEMA)):
        warnings.append(f"{section}: unknown section ignored")

    for section, section_schema in _RUNTIME_STATE_SCHEMA.items():
        incoming = data.get(section, {})
        if not isinstance(incoming, dict):
            warnings.append(f"{section}: expected mapping; using defaults")
            continue

        for key in sorted(set(incoming) - set(section_schema)):
            warnings.append(f"{section}.{key}: unknown key ignored")

        for key, rule in section_schema.items():
            if key not in incoming:
                warnings.append(f"{section}.{key}: missing; using default")
                continue
            normalized[section][key] = _coerce_runtime_value(
                f"{section}.{key}",
                incoming[key],
                normalized[section][key],
                rule,
                warnings,
            )

    return RuntimeConfigLoadResult(normalized, source, tuple(warnings))


def _normalize_runtime_state(data: dict[str, Any] | None) -> dict[str, Any]:
    return validate_runtime_state(data).state


def _render_runtime_state_markdown_views(data: dict[str, Any]) -> tuple[str, str, str]:
    version = data["version"]
    runtime = data["runtime"]
    interaction = data["interaction"]
    wechat = data["wechat"]

    internal_md = (
        "# Runtime State\n\n"
        "## Runtime\n"
        f"- memory_mode: {runtime['memory_mode']}\n"
        f"- route_mode: {runtime['route_mode']}\n"
        f"- debug_mode: {'true' if runtime['debug_mode'] else 'false'}\n"
        f"- safe_mode: {'true' if runtime['safe_mode'] else 'false'}\n"
        f"- performance_mode: {runtime['performance_mode']}\n"
        f"- entry_mode: {runtime['entry_mode']}\n\n"
        "## Version\n"
        f"- current_version: {version['current']}\n"
        f"- active_task: {version['active_task']}\n"
        f"- next_version: {version['next']}\n"
    )
    interaction_md = (
        "# Interaction Settings\n\n"
        "## Relationship\n"
        f"- relationship_mode: {interaction['relationship_mode']}\n"
    )
    wechat_md = (
        "# Wechat State\n\n"
        "## Visibility\n"
        f"- user_has_joined_group: {'true' if wechat['user_has_joined_group'] else 'false'}\n"
        f"- first_join_reaction_done: {'true' if wechat['first_join_reaction_done'] else 'false'}\n"
        f"- mode: {wechat['mode']}\n\n"
        "## Memory Capture\n"
        f"- memory_capture_enabled: {'true' if wechat['memory_capture_enabled'] else 'false'}\n"
        f"- memory_capture_mode: {wechat['memory_capture_mode']}\n"
    )
    return internal_md, interaction_md, wechat_md


_yaml_mtime_cached: float = 0.0


def _runtime_config_from_yaml() -> RuntimeConfigLoadResult:
    global _yaml_mtime_cached

    if not RUNTIME_STATE.is_file():
        state = _read_md_state_migration()
        _write_runtime_state(state)
        return validate_runtime_state(state, source="markdown_migration")

    current_mtime = RUNTIME_STATE.stat().st_mtime
    try:
        raw = yaml.safe_load(RUNTIME_STATE.read_text(encoding="utf-8"))
        result = validate_runtime_state(raw, source=str(RUNTIME_STATE))
    except Exception as exc:
        result = RuntimeConfigLoadResult(
            _default_runtime_state_dict(),
            str(RUNTIME_STATE),
            (f"{RUNTIME_STATE}: failed to parse YAML; using defaults: {exc}",),
        )
    normalized = result.state
    if current_mtime != _yaml_mtime_cached:
        for warning in result.warnings:
            logger.warning("Runtime config warning: %s", warning)
        if _should_sync_markdown_views(normalized):
            _sync_runtime_state_markdown_views(normalized)
        _yaml_mtime_cached = current_mtime
    return result


def _runtime_state_from_yaml() -> dict[str, Any]:
    return _runtime_config_from_yaml().state


def _should_sync_markdown_views(data: dict[str, Any]) -> bool:
    if not RUNTIME_STATE.is_file():
        return False

    internal_md, interaction_md, wechat_md = _render_runtime_state_markdown_views(data)
    expected_views = {
        INTERNAL_STATE: internal_md,
        INTERACTION_SETTINGS: interaction_md,
        WECHAT_STATE: wechat_md,
    }
    for path, expected_text in expected_views.items():
        if not path.is_file():
            return True
        if path.read_text(encoding="utf-8") != expected_text:
            return True
    return False


def _write_runtime_state(data: dict[str, Any]) -> None:
    global _yaml_mtime_cached

    normalized = _normalize_runtime_state(data)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    safe_write_text(
        RUNTIME_STATE,
        yaml.safe_dump(
            normalized,
            allow_unicode=True,
            sort_keys=False,
        ),
    )
    _yaml_mtime_cached = 0.0  # force re-sync on next read
    _sync_runtime_state_markdown_views(normalized)
    try:
        load_runtime_config.clear()
        load_runtime_modes.clear()
    except Exception:
        logger.warning("Failed to clear runtime mode caches", exc_info=True)


def _sync_runtime_state_markdown_views(data: dict[str, Any]) -> None:
    internal_md, interaction_md, wechat_md = _render_runtime_state_markdown_views(data)
    safe_write_text(INTERNAL_STATE, internal_md)
    safe_write_text(INTERACTION_SETTINGS, interaction_md)
    safe_write_text(WECHAT_STATE, wechat_md)


def _modes_from_runtime_state(data: dict[str, Any]) -> RuntimeModes:
    version = data["version"]
    runtime = data["runtime"]
    interaction = data["interaction"]
    wechat = data["wechat"]
    return RuntimeModes(
        memory_mode=runtime["memory_mode"],
        route_mode=runtime["route_mode"],
        debug_mode=bool(runtime["debug_mode"]),
        safe_mode=bool(runtime["safe_mode"]),
        current_version=version["current"],
        active_task=version["active_task"],
        next_version=version["next"],
        relationship_mode=interaction["relationship_mode"],
        wechat_mode=wechat["mode"],
        user_has_joined=bool(wechat["user_has_joined_group"]),
        first_reaction_done=bool(wechat["first_join_reaction_done"]),
        memory_capture_enabled=bool(wechat["memory_capture_enabled"]),
        memory_capture_mode=wechat["memory_capture_mode"],
        performance_mode=runtime["performance_mode"],
        entry_mode=runtime["entry_mode"],
    )


def _state_path_to_section(path: Path) -> str:
    resolved = path.resolve()
    if resolved == INTERNAL_STATE.resolve():
        return "runtime_version"
    if resolved == INTERACTION_SETTINGS.resolve():
        return "interaction"
    if resolved == WECHAT_STATE.resolve():
        return "wechat"
    raise ValueError(f"Unsupported state path: {path}")


def _apply_runtime_update(data: dict[str, Any], key: str, value: str) -> None:
    if key == "memory_mode":
        data["runtime"]["memory_mode"] = value
    elif key == "route_mode":
        data["runtime"]["route_mode"] = value
    elif key == "debug_mode":
        data["runtime"]["debug_mode"] = value.lower() == "true"
    elif key == "safe_mode":
        data["runtime"]["safe_mode"] = value.lower() == "true"
    elif key == "performance_mode":
        data["runtime"]["performance_mode"] = value
    elif key == "entry_mode":
        data["runtime"]["entry_mode"] = value
    elif key == "current_version":
        data["version"]["current"] = value
    elif key == "active_task":
        data["version"]["active_task"] = value
    elif key == "next_version":
        data["version"]["next"] = value
    else:
        raise ValueError(f"Unsupported runtime key: {key}")


def _apply_state_updates(path: Path, updates: dict[str, str]) -> None:
    data = _runtime_state_from_yaml()
    section = _state_path_to_section(path)

    for key, value in updates.items():
        if section == "runtime_version":
            _apply_runtime_update(data, key, value)
        elif section == "interaction":
            if key != "relationship_mode":
                raise ValueError(f"Unsupported interaction key: {key}")
            data["interaction"]["relationship_mode"] = value
        elif section == "wechat":
            if key == "user_has_joined_group":
                data["wechat"]["user_has_joined_group"] = value.lower() == "true"
            elif key == "first_join_reaction_done":
                data["wechat"]["first_join_reaction_done"] = value.lower() == "true"
            elif key == "mode":
                data["wechat"]["mode"] = value
            elif key == "memory_capture_enabled":
                data["wechat"]["memory_capture_enabled"] = value.lower() == "true"
            elif key == "memory_capture_mode":
                data["wechat"]["memory_capture_mode"] = value
            else:
                raise ValueError(f"Unsupported wechat key: {key}")

    _write_runtime_state(data)


@st.cache_data(ttl=30)
def load_runtime_config() -> RuntimeConfigLoadResult:
    return _runtime_config_from_yaml()


@st.cache_data(ttl=30)
def load_runtime_modes() -> RuntimeModes:
    return _modes_from_runtime_state(load_runtime_config().state)


def get_runtime_config_warnings() -> tuple[str, ...]:
    return load_runtime_config().warnings


def _write_keyvalue(path: Path, key: str, value: str) -> None:
    _apply_state_updates(path, {key: value})


def _write_keyvalues(path: Path, updates: dict[str, str]) -> None:
    _apply_state_updates(path, updates)


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
    return build_runtime_profile(modes).memory_write_allowed


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
