"""Memory preview and commit endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.models.memory import (
    MemoryCommitResponse,
    MemoryPreviewItem,
    MemoryPreviewRequest,
    MemoryPreviewResponse,
    MemoryStatusResponse,
)
from src.application.helpers import (
    extract_latest_section,
    memory_file_row,
    memory_target_path,
    memory_update_action,
    memory_update_preview_text,
)

router = APIRouter(tags=["memory"])


@router.get("/memory", response_model=MemoryStatusResponse)
def get_memory_status(context_mode: str | None = None) -> MemoryStatusResponse:
    from src import api as _api  # imported via api proxy for monkeypatch

    from src.memory import CONTEXT_FILE_GROUPS

    modes = _api.load_runtime_modes()
    resolved_context_mode = context_mode or modes.context_mode
    if resolved_context_mode not in CONTEXT_FILE_GROUPS:
        raise HTTPException(status_code=400, detail=f"Invalid context_mode: {resolved_context_mode}")
    writable = _api.is_memory_write_allowed(modes)
    file_names = list(dict.fromkeys(CONTEXT_FILE_GROUPS["archive"]))
    files = [memory_file_row(name) for name in file_names]
    return MemoryStatusResponse(
        writable=writable,
        memory_mode=modes.memory_mode,
        safe_mode=modes.safe_mode,
        reason=modes.profile.memory_write_reason,
        context_mode=resolved_context_mode,
        groups=CONTEXT_FILE_GROUPS,
        files=files,
        latest_section=extract_latest_section(_api.read_memory_file("current_focus.md")),
        latest_updated_at="",
    )


@router.post("/memory/preview", response_model=MemoryPreviewResponse)
def preview_memory_updates(request: MemoryPreviewRequest) -> MemoryPreviewResponse:
    from src.api import is_memory_write_allowed, load_runtime_modes

    runtime_modes = load_runtime_modes()
    writable = is_memory_write_allowed(runtime_modes)
    items = []
    for update in request.updates:
        target = memory_target_path(update.target)
        action = memory_update_action(update)
        items.append(
            MemoryPreviewItem(
                target=update.target,
                path=str(target),
                action=action,
                allowed=writable,
                preview=memory_update_preview_text(update, action),
            )
        )
    return MemoryPreviewResponse(
        writable=writable,
        memory_mode=runtime_modes.memory_mode,
        safe_mode=runtime_modes.safe_mode,
        updates=items,
    )


@router.post("/memory/commit", response_model=MemoryCommitResponse)
def commit_memory_updates(request: MemoryPreviewRequest) -> MemoryCommitResponse:
    from src.api import is_memory_write_allowed, load_runtime_modes

    import src.memory_writer as mw

    runtime_modes = load_runtime_modes()
    writable = is_memory_write_allowed(runtime_modes)
    if not writable:
        raise HTTPException(
            status_code=403,
            detail={
                "memory_mode": runtime_modes.memory_mode,
                "safe_mode": runtime_modes.safe_mode,
                "reason": runtime_modes.profile.memory_write_reason,
            },
        )

    # Pre-validate: at most one current_focus replace
    focus_replaces = [
        u for u in request.updates
        if memory_update_action(u) == "replace" and u.target == "current_focus"
    ]
    if len(focus_replaces) > 1:
        raise HTTPException(
            status_code=400,
            detail="最多允许一次 current_focus replace 操作",
        )

    # Pre-validate all targets before writing any
    for update in request.updates:
        memory_target_path(update.target)

    results = []
    errors: list[dict] = []
    for update in request.updates:
        action = memory_update_action(update)
        try:
            if action == "replace":
                path = mw.write_current_focus(update.content.strip())
            else:
                path = mw.append_memory(
                    update.target,
                    update.content.strip(),
                    learner_pending=update.learner_pending,
                )
            results.append({"target": update.target, "action": action, "path": path})
        except Exception as exc:
            errors.append({"target": update.target, "action": action, "error": str(exc)})

    if errors and not results:
        raise HTTPException(
            status_code=500,
            detail={"message": "所有写入均失败", "errors": errors},
        )

    return MemoryCommitResponse(writable=writable, results=results, errors=errors or None)
