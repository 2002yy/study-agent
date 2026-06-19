"""Application service helpers extracted from the original api.py monolith.

These are pure helper functions used by route handlers. They do NOT contain
any endpoint definitions — routes are in src/api/routes/.

IMPORTANT — Monkeypatch bridge
    Tests monkeypatch attributes on ``src.api``.  All patchable symbols
    (path constants, imported functions) must be resolved through *api*
    at call time via the ``_api()`` helper — never kept as module-level
    bindings.  This guarantees monkeypatches take effect regardless of
    which module the symbol was originally defined in.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import Field as _DataclassField_dummy
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from src import memory_writer
from src.constants import (
    ATMOS_LABELS,
    ATMOS_OPTIONS,
    ENTRY_LABELS,
    ENTRY_OPTIONS,
    MODE_LABELS,
    MODE_OPTIONS,
    MODEL_LABELS,
    MODEL_OPTIONS,
    PERFORMANCE_OPTIONS,
    PERF_LABELS,
    ROLE_LABELS,
    ROLE_OPTIONS,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
# Path constants kept as module-level *defaults* for internal use;
# functions that need monkeypatch-compatible values resolve them
# through _api() at call time.
FRONTEND_SETTINGS_PATH_DEFAULT = CONFIG_DIR / "frontend_settings.yaml"
RAG_UPLOAD_DIR_DEFAULT = ROOT / "logs" / "rag_uploads"
SESSION_DIR_DEFAULT = ROOT / "logs" / "sessions"
CURRENT_SESSION_DIR_DEFAULT = ROOT / "logs" / "current"
WORKFLOW_DIR_DEFAULT = ROOT / "logs" / "workflows"
MEMORY_DIR_DEFAULT = ROOT / "memory"

DEFAULT_FRONTEND_SETTINGS = {
    "selected_role": "auto",
    "selected_mode": "auto",
    "selected_model": "auto",
    "rag_enabled": True,
    "rag_retrieval_mode": "hybrid",
    "rag_search_top_k": 5,
    "rag_chat_top_k": 3,
    "rag_top_k": 3,
    "rag_min_score": 0.01,
}

ROLE_DESCRIPTIONS = {
    "auto": "自动模式会根据输入内容选择角色，不绑定固定人设；开启保持当前角色后，会优先延续上一轮角色。",
    "march7": "轻快、鼓励式的学习伙伴，适合入门启动、卡住时破冰和用问题带你往前走。",
    "keqing": "偏执行、判断和推进，适合代码、项目计划、风险拆解、验收标准和下一步行动。",
    "nahida": "偏概念解释和知识连接，适合机制、原理、概念边界、知识结构和深入理解。",
    "firefly": "偏陪伴、复盘和收束，适合整理感受、回顾学习过程、缓和压力并形成温和结论。",
}


# ═══════════════════════════════════════════════════════════════════════════
# Monkeypatch bridge
# ═══════════════════════════════════════════════════════════════════════════
#
# Tests do  monkeypatch.setattr(api, "NAME", ...)  so functions that need
# patchable symbols MUST resolve them through _api() at call time rather
# than keeping a module-level binding.
# ═══════════════════════════════════════════════════════════════════════════

def _api():
    """Lazy reference to ``src.api`` for monkeypatch-compatible access."""
    from src import api
    return api


def _api_path(name: str) -> Path:
    """Return the current value of a *path* constant from api at call time.

    Tests do ``monkeypatch.setattr(api, "FRONTEND_SETTINGS_PATH", ...)``
    so we must NOT use a module-level ``FRONTEND_SETTINGS_PATH`` constant.
    """
    return getattr(_api(), name, _api_path_default(name))


def _api_path_default(name: str) -> Path:
    defaults: dict[str, Path] = {
        "FRONTEND_SETTINGS_PATH": FRONTEND_SETTINGS_PATH_DEFAULT,
        "RAG_UPLOAD_DIR": RAG_UPLOAD_DIR_DEFAULT,
        "SESSION_DIR": SESSION_DIR_DEFAULT,
        "CURRENT_SESSION_DIR": CURRENT_SESSION_DIR_DEFAULT,
        "WORKFLOW_DIR": WORKFLOW_DIR_DEFAULT,
        "MEMORY_DIR": ROOT / "data" / "memory",
    }
    return defaults[name]


# ── Index path helper ──────────────────────────────────────────────────

def _index_path(value: str | None, default: Path) -> Path:
    return Path(value) if value else default


# ── Frontend settings helpers ──────────────────────────────────────────

def _frontend_settings_defaults() -> dict[str, Any]:
    return dict(DEFAULT_FRONTEND_SETTINGS)


def _normalize_frontend_settings(settings: dict[str, Any]) -> dict[str, Any]:
    normalized = _frontend_settings_defaults()
    selected_role = settings.get("selected_role")
    if selected_role in ROLE_OPTIONS:
        normalized["selected_role"] = selected_role
    selected_mode = settings.get("selected_mode")
    if selected_mode in MODE_OPTIONS:
        normalized["selected_mode"] = selected_mode
    selected_model = settings.get("selected_model")
    if selected_model in MODEL_OPTIONS:
        normalized["selected_model"] = selected_model
    normalized["rag_enabled"] = bool(settings.get("rag_enabled", normalized["rag_enabled"]))
    retrieval_mode = settings.get("rag_retrieval_mode")
    if retrieval_mode in {"lexical", "vector", "hybrid", "backend_vector"}:
        normalized["rag_retrieval_mode"] = retrieval_mode
    legacy_top_k = settings.get("rag_top_k")
    try:
        normalized["rag_search_top_k"] = max(
            1,
            min(20, int(settings.get("rag_search_top_k", legacy_top_k or normalized["rag_search_top_k"]))),
        )
    except (TypeError, ValueError):
        pass
    try:
        normalized["rag_chat_top_k"] = max(
            1,
            min(20, int(settings.get("rag_chat_top_k", legacy_top_k or normalized["rag_chat_top_k"]))),
        )
    except (TypeError, ValueError):
        pass
    normalized["rag_top_k"] = normalized["rag_chat_top_k"]
    try:
        normalized["rag_min_score"] = max(0.0, float(settings.get("rag_min_score", normalized["rag_min_score"])))
    except (TypeError, ValueError):
        pass
    return normalized


def load_frontend_settings() -> dict[str, Any]:
    data: dict[str, Any] = {}
    frontend_path = _api_path("FRONTEND_SETTINGS_PATH")
    if frontend_path.is_file():
        try:
            raw = yaml.safe_load(frontend_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except yaml.YAMLError:
            data = {}
    settings = _frontend_settings_defaults()
    settings.update({key: value for key, value in data.items() if key in settings})
    return _normalize_frontend_settings(settings)


def write_frontend_settings(settings: dict[str, Any]) -> None:
    from src.safe_writer import safe_write_text

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    safe_write_text(
        _api_path("FRONTEND_SETTINGS_PATH"),
        yaml.safe_dump(
            _normalize_frontend_settings(settings),
            allow_unicode=True,
            sort_keys=False,
        ),
    )


# ── Validation helpers ─────────────────────────────────────────────────

def validate_choice(value: str, choices: list[str] | tuple[str, ...], label: str) -> str:
    from fastapi import HTTPException

    if value not in choices:
        raise HTTPException(status_code=400, detail=f"Invalid {label}: {value}")
    return value


# ── Performance / model helpers ────────────────────────────────────────

def request_performance_mode(requested: str | None) -> str:
    load_runtime_modes = _api().load_runtime_modes

    modes = load_runtime_modes()
    if requested:
        return validate_choice(requested, PERFORMANCE_OPTIONS, "performance_mode")
    return modes.performance_mode


def request_model_profile(selected_model: str, performance_mode: str) -> str:
    if selected_model == "pro":
        return "pro"
    if selected_model == "flash":
        return "flash"
    if performance_mode == "deep":
        return "pro"
    if performance_mode == "fast":
        return "flash"
    return "flash"


def runtime_modes_for_request(requested_performance_mode: str | None):
    load_runtime_modes = _api().load_runtime_modes

    runtime_modes = load_runtime_modes()
    if not requested_performance_mode:
        return runtime_modes
    performance_mode = validate_choice(
        requested_performance_mode,
        PERFORMANCE_OPTIONS,
        "performance_mode",
    )
    return replace(runtime_modes, performance_mode=performance_mode)


# ── Session helpers ────────────────────────────────────────────────────

def session_file_rows(directory: Path, kind: str, limit: int) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in directory.glob("*.md"):
        stat = path.stat()
        rows.append(
            {
                "kind": kind,
                "name": path.name,
                "path": str(path),
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    rows.sort(key=lambda row: int(row["mtime_ns"]), reverse=True)
    return rows[:limit]


def messages_from_session_entries(entries: list[dict[str, Any]]) -> list[Any]:
    from src.api.models.chat import ChatMessage

    messages: list[ChatMessage] = []
    for entry in entries:
        entry_messages = entry.get("messages")
        if isinstance(entry_messages, list):
            for message in entry_messages:
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role", "")).strip()
                content = str(message.get("content", "")).strip()
                if role and content:
                    messages.append(
                        ChatMessage(
                            role=role,
                            content=content,
                            avatarRole=message.get("avatarRole"),
                        )
                    )
            continue
        user = str(entry.get("user", "")).strip()
        agent = str(entry.get("agent", "")).strip()
        if user:
            messages.append(ChatMessage(role="user", content=user, avatarRole="user"))
        if agent:
            messages.append(ChatMessage(role="assistant", content=agent, avatarRole=entry.get("role")))
    return messages


def session_snapshot_from_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    if not entries:
        return {"settings": {}, "route": {}, "rag": {}, "conversation_instruction": ""}
    latest = entries[-1]
    return {
        "settings": latest.get("settings") or {},
        "route": latest.get("route") or {},
        "rag": latest.get("rag") or {},
        "conversation_instruction": latest.get("conversation_instruction") or "",
    }


def parse_session_turn_snapshots(raw: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    marker = "```json session_turn"
    for block in raw.split(marker)[1:]:
        json_part = block.split("```", 1)[0].strip()
        if not json_part:
            continue
        try:
            parsed = json.loads(json_part)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries


def parse_archived_session_messages(raw: str) -> list[Any]:
    from src.api.models.chat import ChatMessage

    snapshots = parse_session_turn_snapshots(raw)
    if snapshots:
        return messages_from_session_entries(snapshots)
    messages: list[ChatMessage] = []
    for block in raw.split("---"):
        if "**User**" not in block or "**Agent**" not in block:
            continue
        user_part = block.split("**User**", 1)[1].split("**Agent**", 1)[0].strip()
        agent_part = block.split("**Agent**", 1)[1].strip()
        if "```json session_turn" in agent_part:
            agent_part = agent_part.split("```json session_turn", 1)[0].strip()
        if user_part:
            messages.append(ChatMessage(role="user", content=user_part))
        if agent_part:
            messages.append(ChatMessage(role="assistant", content=agent_part))
    return messages


def parse_current_session_messages(raw: str) -> list[Any]:
    from src.api.models.chat import ChatMessage

    snapshots = parse_session_turn_snapshots(raw)
    if snapshots:
        return messages_from_session_entries(snapshots)
    messages: list[ChatMessage] = []
    for line in raw.splitlines():
        if line.startswith("User: "):
            messages.append(ChatMessage(role="user", content=line.removeprefix("User: ").strip()))
        elif line.startswith("Agent: "):
            messages.append(ChatMessage(role="assistant", content=line.removeprefix("Agent: ").strip()))
    return messages


def session_snapshot_from_raw(raw: str) -> dict[str, Any]:
    return session_snapshot_from_entries(parse_session_turn_snapshots(raw))


def find_session_file(session_id: str) -> tuple[str, Path | None]:
    current_dir = _api_path("CURRENT_SESSION_DIR")
    session_dir = _api_path("SESSION_DIR")
    current = current_dir / f"{session_id}.md"
    if current.is_file():
        return "current", current
    if session_dir.is_dir():
        matches = sorted(
            session_dir.glob(f"*_session_{session_id}_*.md"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        if matches:
            return "archived", matches[0]
    return "active", None


# ── Memory helpers ─────────────────────────────────────────────────────

def memory_target_path(target: str) -> Path:
    from fastapi import HTTPException
    path = memory_writer.MEMORY_TARGETS.get(target)
    if path is None:
        raise HTTPException(status_code=400, detail=f"Unknown memory target: {target}")
    return path


def memory_update_action(update: Any) -> str:
    from fastapi import HTTPException
    if update.append:
        return "append"
    if update.target == "current_focus":
        return "replace"
    raise HTTPException(
        status_code=400,
        detail="append=false is only supported for target current_focus",
    )


def memory_update_preview_text(update: Any, action: str) -> str:
    content = update.content.strip()
    if action == "replace":
        return f"{content}\n"
    prefix = "### 待确认观察\n\n" if update.learner_pending else "## 课后更新\n\n"
    return f"{prefix}{content}\n"


def memory_file_row(name: str) -> dict[str, Any]:
    path = _api_path("MEMORY_DIR") / name
    exists = path.is_file()
    content = _api().read_memory_file(name) if exists else ""
    stat = path.stat() if exists else None
    return {
        "name": name,
        "path": str(path),
        "exists": exists,
        "size_bytes": stat.st_size if stat else 0,
        "mtime_ns": stat.st_mtime_ns if stat else 0,
        "preview": content[-1600:],
        "latest_section": extract_latest_section(content),
        "latest_updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat() if stat and exists else "",
    }


def extract_latest_section(text: str) -> str:
    """Return the last heading-delimited section from a markdown text."""
    if not text.strip():
        return ""
    sections = [s.strip() for s in re.split(r"\n(?=#{1,6}\s+)", text) if s.strip()]
    if not sections:
        return text.strip()[-400:]
    return sections[-1]


# ── Role helpers ───────────────────────────────────────────────────────

def role_payload(role_id: str) -> Any:
    from fastapi import HTTPException
    from src.api.models.common import RoleResponse
    load_role = _api().load_role
    list_roles = _api().list_roles

    if role_id == "auto":
        return RoleResponse(
            id="auto",
            label=ROLE_LABELS["auto"],
            prompt="",
            summary=ROLE_DESCRIPTIONS["auto"],
            description=ROLE_DESCRIPTIONS["auto"],
        )
    if role_id not in list_roles():
        raise HTTPException(status_code=404, detail=f"Unknown role: {role_id}")
    prompt = load_role(role_id)
    description = ROLE_DESCRIPTIONS.get(role_id, ROLE_LABELS.get(role_id, role_id))
    return RoleResponse(
        id=role_id,
        label=ROLE_LABELS.get(role_id, role_id),
        prompt=prompt,
        summary=description,
        description=description,
    )


# ── Runtime settings helpers ───────────────────────────────────────────

def runtime_settings_options() -> dict[str, Any]:
    return {
        "roles": [{"id": role_id, "label": ROLE_LABELS.get(role_id, role_id)} for role_id in ROLE_OPTIONS],
        "modes": [{"id": mode, "label": MODE_LABELS.get(mode, mode)} for mode in MODE_OPTIONS],
        "models": [{"id": model, "label": MODEL_LABELS.get(model, model)} for model in MODEL_OPTIONS],
        "performance_modes": [
            {"id": mode, "label": PERF_LABELS.get(mode, mode)} for mode in PERFORMANCE_OPTIONS
        ],
        "relationship_modes": [
            {"id": mode, "label": ATMOS_LABELS.get(mode, mode)} for mode in ATMOS_OPTIONS
        ],
        "entry_modes": [{"id": mode, "label": ENTRY_LABELS.get(mode, mode)} for mode in ENTRY_OPTIONS],
        "memory_modes": ["readonly", "preview", "confirm_write", "locked"],
        "retrieval_modes": ["lexical", "vector", "hybrid", "backend_vector"],
    }


def runtime_settings_payload() -> Any:
    from src.api.models.settings import RuntimeSettingsResponse
    from src.mode_manager import get_runtime_config_warnings
    load_runtime_modes = _api().load_runtime_modes

    modes = load_runtime_modes()
    profile = modes.profile
    settings = {
        **load_frontend_settings(),
        "relationship_mode": modes.relationship_mode,
        "entry_mode": modes.entry_mode,
        "performance_mode": modes.performance_mode,
        "memory_mode": modes.memory_mode,
        "debug_mode": modes.debug_mode,
        "safe_mode": modes.safe_mode,
        "route_mode": modes.route_mode,
        "context_mode": modes.context_mode,
        "current_version": modes.current_version,
        "active_task": modes.active_task,
        "next_version": modes.next_version,
        "wechat_memory_capture_enabled": modes.memory_capture_enabled,
        "wechat_memory_capture_mode": modes.memory_capture_mode,
    }
    return RuntimeSettingsResponse(
        settings=settings,
        options=runtime_settings_options(),
        runtime_profile=dict(profile.__dict__),
        warnings=list(get_runtime_config_warnings()),
    )


# ── Wechat helpers ─────────────────────────────────────────────────────

def wechat_state_payload() -> Any:
    from src.api.models.wechat import WechatStateResponse
    api = _api()
    read_wechat_state = api.read_wechat_state
    read_wechat_group = api.read_wechat_group
    read_wechat_unread = api.read_wechat_unread
    has_wechat_unread = api.has_wechat_unread
    has_wechat_group_started = api.has_wechat_group_started
    count_wechat_messages = api.count_wechat_messages
    summarize_wechat = api.summarize_wechat

    state = read_wechat_state()
    content = read_wechat_group()
    unread = read_wechat_unread()
    return WechatStateResponse(
        state=state,
        content=content,
        unread=unread,
        has_unread=has_wechat_unread(),
        started=has_wechat_group_started(),
        message_count=count_wechat_messages(content),
        unread_count=count_wechat_messages(unread),
        summary=summarize_wechat(),
    )


# ── News helpers ───────────────────────────────────────────────────────

def news_result_payload(result: Any, session_id: str) -> Any:
    from src.api.models.news import NewsSearchResponse

    return NewsSearchResponse(
        query_text=result.query_text,
        news_items=result.news_items,
        digest=result.digest,
        discussion=result.discussion,
        group_content=result.group_content,
        source_block=result.source_block,
        article_coverage=result.article_coverage,
        elapsed_ms=result.elapsed_ms,
        warnings=result.warnings,
        audit_markdown_path=result.audit_markdown_path,
        audit_json_path=result.audit_json_path,
        session_id=session_id,
    )


# ── Chat context helpers ───────────────────────────────────────────────

def previous_assistant_role(chat_history: list[Any]) -> str | None:
    valid_roles = {"march7", "keqing", "nahida", "firefly"}
    for message in reversed(chat_history):
        if message.role != "assistant":
            continue
        if message.avatarRole in valid_roles:
            return message.avatarRole
    return None


def session_settings_from_request(request: Any, context_mode: str) -> dict[str, Any]:
    chat_top_k = request.rag_chat_top_k or request.rag_top_k
    search_top_k = request.rag_search_top_k or chat_top_k
    return {
        "selectedRole": request.selected_role,
        "selectedMode": request.selected_mode,
        "selectedModel": request.selected_model,
        "relationshipMode": request.relationship_mode,
        "contextMode": context_mode,
        "ragEnabled": request.rag_enabled,
        "ragSettings": {
            "chatTopK": chat_top_k,
            "topK": search_top_k,
            "retrievalMode": request.rag_retrieval_mode,
            "minScore": request.rag_min_score,
        },
        "keepCurrentRole": request.keep_current_role,
    }


def prepare_chat_context(request: Any) -> dict[str, Any]:
    api = _api()
    read_memory_bundle = api.read_memory_bundle
    build_role_prompt = api.build_role_prompt
    route_request = api.route_request
    retrieve_local_knowledge = api.retrieve_local_knowledge
    from src.context_builder import build_messages as _build_messages

    runtime_modes = runtime_modes_for_request(request.performance_mode)
    context_mode = request.context_mode or runtime_modes.context_mode

    # If this is a continuation request, build a system instruction instead of
    # a user-visible message
    continuation_instruction = ""
    if request.continuation_of_turn_id and request.partial_reply.strip():
        continuation_instruction = (
            "[继续生成指令]\n"
            "请从下面已经输出的内容之后继续回答，不要重复已输出的部分。\n"
            f"已输出内容：\n{request.partial_reply.strip()[:800]}"
        )

    effective_user_input = request.user_input
    if continuation_instruction:
        effective_user_input = f"{request.user_input}\n\n{continuation_instruction}"

    route = route_request(
        user_input=request.user_input,
        selected_role=request.selected_role,
        selected_mode=request.selected_mode,
        selected_model=request.selected_model,
        runtime_modes=runtime_modes,
        previous_role=previous_assistant_role(request.chat_history),
        previous_mode=request.previous_mode,
        keep_current_role=request.keep_current_role,
    )
    role_prompt = build_role_prompt(
        route["role"],
        scene=request.scene,
        relationship_mode=request.relationship_mode,
    )
    memory_bundle = read_memory_bundle(context_mode)
    rag_result = retrieve_local_knowledge(
        request.user_input,
        enabled=request.rag_enabled,
        top_k=request.rag_chat_top_k or request.rag_top_k,
        retrieval_mode=request.rag_retrieval_mode,
        min_score=request.rag_min_score,
    )
    web_context = request.web_context.strip()
    context_blocks = [f"【本地资料检索结果】\n{rag_result.context}"] if rag_result.context.strip() else []
    if web_context:
        context_blocks.append(f"【联网检索结果】\n{web_context}")
    if continuation_instruction:
        context_blocks.append(continuation_instruction)
    messages = _build_messages(
        user_input=request.user_input,
        role_prompt=role_prompt,
        mode=route["mode"],
        memory_bundle=memory_bundle,
        chat_history=[message.model_dump() for message in request.chat_history],
        relationship_mode=request.relationship_mode,
        runtime_modes=runtime_modes,
        context_mode=context_mode,
        rag_context="\n\n".join(context_blocks),
        scene=request.scene,
        conversation_instruction=request.conversation_instruction,
    )
    return {
        "runtime_modes": runtime_modes,
        "context_mode": context_mode,
        "route": route,
        "memory_bundle": memory_bundle,
        "rag_result": rag_result,
        "messages": messages,
        "web_context_used": bool(web_context),
        "session_settings": session_settings_from_request(request, context_mode),
        "is_continuation": bool(continuation_instruction),
    }


# ── SSE helpers ────────────────────────────────────────────────────────

def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_usage_payload(reply: str) -> dict[str, Any]:
    return {
        "estimated": True,
        "output_chars": len(reply),
        "output_tokens_estimate": max(1, len(reply) // 4) if reply else 0,
    }


# ── Upload helpers ─────────────────────────────────────────────────────

def unique_upload_path(upload_dir: Path, filename: str | None, used_names: set[str]) -> Path:
    raw_name = Path(filename or "document").name or "document"
    raw_path = Path(raw_name)
    stem = raw_path.stem or "document"
    suffix = raw_path.suffix
    candidate = raw_name
    counter = 2
    while candidate in used_names or (upload_dir / candidate).exists():
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
    used_names.add(candidate)
    return upload_dir / candidate
