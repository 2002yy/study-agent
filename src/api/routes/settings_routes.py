"""Runtime settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from src.api.models.common import RoleListResponse, RoleResponse
from src.api.models.settings import RuntimeSettingsPatch, RuntimeSettingsResponse
from src.constants import (
    ATMOS_OPTIONS,
    ENTRY_OPTIONS,
    MODEL_OPTIONS,
    MODE_OPTIONS,
    PERFORMANCE_OPTIONS,
    ROLE_LABELS,
    ROLE_OPTIONS,
)
from src.application.helpers import (
    role_payload,
    runtime_settings_payload,
    validate_choice,
)

router = APIRouter(tags=["settings"])


@router.get("/runtime/settings", response_model=RuntimeSettingsResponse)
def get_runtime_settings() -> RuntimeSettingsResponse:
    return runtime_settings_payload()


@router.patch("/runtime/settings", response_model=RuntimeSettingsResponse)
def patch_runtime_settings(request: RuntimeSettingsPatch) -> RuntimeSettingsResponse:
    from src.api import (
        load_frontend_settings,
        set_memory_mode,
        update_debug_mode,
        update_entry_mode,
        update_interaction_mode,
        update_memory_capture,
        update_performance_mode,
        update_safe_mode,
        write_frontend_settings,
    )

    frontend_settings = load_frontend_settings()
    if request.selected_role is not None:
        frontend_settings["selected_role"] = validate_choice(
            request.selected_role, ROLE_OPTIONS, "selected_role"
        )
    if request.selected_mode is not None:
        frontend_settings["selected_mode"] = validate_choice(
            request.selected_mode, MODE_OPTIONS, "selected_mode"
        )
    if request.selected_model is not None:
        frontend_settings["selected_model"] = validate_choice(
            request.selected_model, MODEL_OPTIONS, "selected_model"
        )
    if request.rag_enabled is not None:
        frontend_settings["rag_enabled"] = request.rag_enabled
    if request.rag_retrieval_mode is not None:
        frontend_settings["rag_retrieval_mode"] = validate_choice(
            request.rag_retrieval_mode,
            ("lexical", "vector", "hybrid", "backend_vector"),
            "rag_retrieval_mode",
        )
    if request.rag_top_k is not None:
        frontend_settings["rag_search_top_k"] = request.rag_top_k
        frontend_settings["rag_chat_top_k"] = request.rag_top_k
    if request.rag_search_top_k is not None:
        frontend_settings["rag_search_top_k"] = request.rag_search_top_k
    if request.rag_chat_top_k is not None:
        frontend_settings["rag_chat_top_k"] = request.rag_chat_top_k
    if request.rag_min_score is not None:
        frontend_settings["rag_min_score"] = request.rag_min_score
    write_frontend_settings(frontend_settings)

    if request.relationship_mode is not None:
        update_interaction_mode(
            validate_choice(request.relationship_mode, ATMOS_OPTIONS, "relationship_mode")
        )
    if request.entry_mode is not None:
        update_entry_mode(validate_choice(request.entry_mode, ENTRY_OPTIONS, "entry_mode"))
    if request.performance_mode is not None:
        update_performance_mode(
            validate_choice(request.performance_mode, PERFORMANCE_OPTIONS, "performance_mode")
        )
    if request.memory_mode is not None:
        set_memory_mode(
            validate_choice(
                request.memory_mode,
                ("readonly", "preview", "confirm_write", "locked"),
                "memory_mode",
            )
        )
    if request.debug_mode is not None:
        update_debug_mode(request.debug_mode)
    if request.safe_mode is not None:
        update_safe_mode(request.safe_mode)
    if request.wechat_memory_capture_enabled is not None:
        update_memory_capture(request.wechat_memory_capture_enabled)
    return runtime_settings_payload()


@router.get("/roles", response_model=RoleListResponse)
def get_roles() -> RoleListResponse:
    roles = [
        {"id": role_id, "label": ROLE_LABELS.get(role_id, role_id), "summary": role_payload(role_id).summary}
        for role_id in ROLE_OPTIONS
    ]
    return RoleListResponse(roles=roles)


@router.get("/roles/{role_id}", response_model=RoleResponse)
def get_role(role_id: str) -> RoleResponse:
    return role_payload(role_id)
