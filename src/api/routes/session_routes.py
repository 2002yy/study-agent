"""Thin session adapters backed by SQLite ChatThread/ChatTurn."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.models.common import (
    SessionArchiveResponse,
    SessionDetailResponse,
    SessionListResponse,
    SessionNewResponse,
    SessionTitleUpdateRequest,
    SessionTitleUpdateResponse,
)
from src.api.models.memory import MemoryRunResponse
from src.api.models.learner_model import LearnerModelSnapshotResponse
from src.api.models.learning_review import (
    LearningReviewPageResponse,
    ReviewPromptPreviewResponse,
    StartReviewPromptRequest,
    StartReviewPromptResponse,
)
from src.application.helpers import runtime_settings_payload
from src.application.learner_model import LearnerModelService
from src.application.learning_closure_service import LearningClosureNotEligible
from src.application.learning_revalidation import LearningRevalidationService
from src.application.learning_review import LearningReviewService, ReviewUnavailable
from src.application.runtime_repository import (
    get_learning_closure_service,
    get_learner_model_service,
    get_learning_revalidation_service,
    get_learning_resume_service,
    get_learning_review_service,
    get_session_service,
)
from src.application.session_service import SessionService
from src.application.chat_service import ChatService, TurnCancelled
from src.application.runtime_repository import get_chat_service

router = APIRouter(tags=["sessions"])
SessionServiceDependency = Annotated[SessionService, Depends(get_session_service)]
LearnerModelServiceDependency = Annotated[
    LearnerModelService, Depends(get_learner_model_service)
]
LearningReviewServiceDependency = Annotated[
    LearningReviewService, Depends(get_learning_review_service)
]
ReviewChatServiceDependency = Annotated[ChatService, Depends(get_chat_service)]


@router.post(
    "/sessions/{session_id}/reviews/{revision_id}/start",
    response_model=StartReviewPromptResponse,
)
def start_review_prompt(
    session_id: str,
    revision_id: str,
    request: StartReviewPromptRequest,
    service: ReviewChatServiceDependency,
    session_service: SessionServiceDependency,
) -> StartReviewPromptResponse:
    if session_service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        turn = service.start_review_prompt(
            session_id, revision_id, turn_id=request.turn_id, operation_id=request.operation_id
        )
    except ReviewUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TurnCancelled as exc:
        raise HTTPException(status_code=409, detail="Review prompt cancelled") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return StartReviewPromptResponse(
        thread_id=session_id, prompt_turn_id=turn.id, question=turn.assistant_message,
        status="completed",
    )


@router.get("/sessions/{session_id}/reviews", response_model=LearningReviewPageResponse)
def get_learning_reviews(
    session_id: str,
    service: LearningReviewServiceDependency,
    session_service: SessionServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    due_only: bool = False,
) -> LearningReviewPageResponse:
    if session_service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return LearningReviewPageResponse(
        **service.build(session_id, limit=limit, offset=offset, due_only=due_only).to_dict()
    )


@router.get(
    "/sessions/{session_id}/reviews/{revision_id}/prompt",
    response_model=ReviewPromptPreviewResponse,
)
def preview_review_prompt(
    session_id: str,
    revision_id: str,
    service: LearningReviewServiceDependency,
    session_service: SessionServiceDependency,
) -> ReviewPromptPreviewResponse:
    if session_service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return ReviewPromptPreviewResponse(
            **service.preview_prompt(session_id, revision_id).to_dict()
        )
    except ReviewUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/sessions", response_model=SessionListResponse)
def list_sessions(
    service: SessionServiceDependency,
    limit: int = 20,
    offset: int = 0,
    q: str = "",
) -> SessionListResponse:
    """G4: paged, server-side searchable session listing."""
    rows, total = service.list_sessions_page(
        limit=max(1, min(limit, 100)),
        offset=max(0, offset),
        query=q,
    )
    return SessionListResponse(sessions=rows, total=total)


@router.get(
    "/sessions/{session_id}",
    response_model=SessionDetailResponse,
    response_model_exclude_none=True,
)
def get_session_detail(
    session_id: str,
    service: SessionServiceDependency,
) -> SessionDetailResponse:
    detail = service.get_session(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionDetailResponse(**detail)


@router.get("/sessions/{session_id}/learning-resume")
def get_learning_resume(
    session_id: str,
    service: SessionServiceDependency,
) -> dict[str, Any]:
    """Return semantic learning resume state without replaying chat when durable truth exists."""

    resume_service = get_learning_resume_service()
    resume = resume_service.build(session_id)
    if resume.get("source") != "legacy_fallback":
        return resume

    # Compatibility only: use the existing SessionService navigation projection
    # when this thread has never acquired durable Goal context. Durable threads
    # never fall back to legacy learning_state, even if all Goals are terminal.
    detail = service.get_session(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    navigation = detail.get("navigation")
    return resume_service.build(
        session_id,
        legacy_navigation=navigation if isinstance(navigation, dict) else {},
    )


@router.get(
    "/sessions/{session_id}/learner-model",
    response_model=LearnerModelSnapshotResponse,
)
def get_learner_model_snapshot(
    session_id: str,
    session_service: SessionServiceDependency,
    learner_model_service: LearnerModelServiceDependency,
) -> LearnerModelSnapshotResponse:
    """Expose the bounded learner-model projection without adding a write owner."""

    if session_service.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return LearnerModelSnapshotResponse(
        **learner_model_service.build(session_id).to_dict()
    )


@router.post("/sessions/{session_id}/claims/{claim_id}/revalidate")
def revalidate_claim(
    session_id: str,
    claim_id: str,
    service: LearningRevalidationService = Depends(get_learning_revalidation_service),
) -> dict[str, Any]:
    """Re-converge one durable Claim and commit a Revision on the same lineage."""

    try:
        result = service.revalidate(session_id, claim_id)
    except ValueError as exc:
        reason = str(exc)
        status = 404 if reason == "claim_not_found" else 409
        raise HTTPException(status_code=status, detail=reason) from exc
    return {
        "claim_id": result.claim_id,
        "outcome": result.outcome,
        "revision_id": result.revision_id,
        "unresolved_reason": result.unresolved_reason,
        "head_commit": result.head_commit,
        "freshness_status": result.freshness_status,
    }


@router.post("/sessions/new", response_model=SessionNewResponse)
def create_new_session(service: SessionServiceDependency) -> SessionNewResponse:
    settings = runtime_settings_payload().settings
    thread = service.create_session(dict(settings))
    return SessionNewResponse(session_id=thread.id, settings=settings)


@router.patch(
    "/sessions/{session_id}/title",
    response_model=SessionTitleUpdateResponse,
)
def update_session_title(
    session_id: str,
    request: SessionTitleUpdateRequest,
    service: SessionServiceDependency,
) -> SessionTitleUpdateResponse:
    try:
        session = service.rename_session(session_id, request.title)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SessionTitleUpdateResponse(session=session)


@router.post(
    "/sessions/{session_id}/archive",
    response_model=SessionArchiveResponse,
)
def archive_session(
    session_id: str,
    service: SessionServiceDependency,
) -> SessionArchiveResponse:
    try:
        outcome = service.request_archive(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if outcome.get("status") == "queued":
        # G12 decision 15: persisted server-side; executes when the cancelled
        # operation settles (or on restart via the startup sweep).
        return SessionArchiveResponse(
            session_id=session_id,
            kind="archived",
            path="",
            archived=False,
            queued=True,
        )
    thread = service.repository.get_chat_thread(session_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if thread.status != "archived":
        raise HTTPException(status_code=404, detail="Session has no messages to archive")
    return SessionArchiveResponse(
        session_id=thread.id,
        kind="archived",
        path=thread.export_path,
        archived=True,
    )


@router.delete("/sessions/{session_id}/archive-queue")
def cancel_queued_archive(
    session_id: str,
    service: SessionServiceDependency,
) -> dict[str, Any]:
    """User-visible "cancel the pending archive" (G12 decision 15)."""
    changed = service.cancel_pending_archive(session_id)
    return {"session_id": session_id, "cancelled": changed}


@router.post("/sessions/{session_id}/memory-consent/revoke")
def revoke_memory_consent(
    session_id: str,
    service: SessionServiceDependency,
) -> dict[str, Any]:
    """Revoke the per-session memory grant (G16 decision 11)."""
    try:
        return service.revoke_memory_consent(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/flush")
def flush_session(
    session_id: str,
    service: SessionServiceDependency,
) -> dict[str, Any]:
    path = service.flush_session(session_id)
    return {
        "session_id": session_id,
        "flushed": path is not None,
        "path": str(path) if path else "",
    }


@router.post(
    "/sessions/{session_id}/after-session/preview",
    response_model=MemoryRunResponse,
    deprecated=True,
)
def after_session_preview(
    session_id: str,
) -> MemoryRunResponse:
    """Compatibility adapter; LearningClosureService owns the workflow."""

    closure_service = get_learning_closure_service()
    try:
        closure = closure_service.create_and_execute(session_id)
    except LearningClosureNotEligible as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    memory_run = closure_service.linked_memory_run(closure)
    if memory_run is None:
        detail = closure.error or closure.reason or "Closure preview is not ready"
        raise HTTPException(status_code=409, detail=detail)
    return MemoryRunResponse(**asdict(memory_run))
