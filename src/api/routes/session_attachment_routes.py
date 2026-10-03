"""G14 temporary session attachment adapters.

Upload/list/delete/retry/promote over the per-thread lifecycle service.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from src.application.runtime_repository import (
    get_session_attachment_service,
)
from src.application.session_attachment_service import AttachmentLimitError
from src.application.document_reading import (
    DocumentReadingResponse,
    ReadingUnavailable,
    read_session_document,
)
from src.domain.runtime_entities import SessionAttachment

router = APIRouter(tags=["attachments"])
SessionAttachmentServiceDependency = Annotated[
    Any, Depends(get_session_attachment_service)
]


class AttachmentStageEntry(BaseModel):
    stage: str
    status: str
    at: str = ""
    detail: str = Field(default="")
    model_config = {"extra": "allow"}


class SessionAttachmentResponse(BaseModel):
    id: str
    thread_id: str
    filename: str
    content_hash: str
    mime_type: str
    size_bytes: int
    status: str
    stage_error: str
    stage_history: list[dict[str, Any]]
    retry_count: int
    promoted_rag_run_id: str
    external_calls: list[dict[str, Any]]
    created_at: str
    updated_at: str


class SessionAttachmentListResponse(BaseModel):
    attachments: list[SessionAttachmentResponse]
    max_files_per_thread: int
    total_bytes: int


class AttachmentDeleteResponse(BaseModel):
    deleted: bool
    attachment_id: str


class AttachmentPromoteResponse(BaseModel):
    status: str
    attachment_id: str
    promoted_rag_run_id: str = ""
    long_term_document_id: str = ""


def _response(attachment: SessionAttachment) -> SessionAttachmentResponse:
    return SessionAttachmentResponse(
        id=attachment.id,
        thread_id=attachment.thread_id,
        filename=attachment.filename,
        content_hash=attachment.content_hash,
        mime_type=attachment.mime_type,
        size_bytes=attachment.size_bytes,
        status=attachment.status,
        stage_error=attachment.stage_error,
        stage_history=list(attachment.stage_history),
        retry_count=attachment.retry_count,
        promoted_rag_run_id=attachment.promoted_rag_run_id,
        external_calls=list(attachment.external_calls),
        created_at=attachment.created_at,
        updated_at=attachment.updated_at,
    )


@router.post(
    "/sessions/{thread_id}/attachments",
    response_model=SessionAttachmentResponse,
)
async def upload_session_attachment(
    thread_id: str,
    file: UploadFile,
    service: SessionAttachmentServiceDependency,
) -> SessionAttachmentResponse:
    data = await file.read()
    try:
        attachment = service.upload(
            thread_id,
            file.filename or "",
            data,
            content_type=file.content_type or "",
        )
    except AttachmentLimitError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _response(attachment)


@router.get(
    "/sessions/{thread_id}/attachments",
    response_model=SessionAttachmentListResponse,
)
def list_session_attachments(
    thread_id: str,
    service: SessionAttachmentServiceDependency,
) -> SessionAttachmentListResponse:
    from src.application.session_attachment_service import (
        MAX_FILES_PER_THREAD,
    )

    attachments = service.repository.list_by_thread(thread_id)
    return SessionAttachmentListResponse(
        attachments=[_response(attachment) for attachment in attachments],
        max_files_per_thread=MAX_FILES_PER_THREAD,
        total_bytes=sum(attachment.size_bytes for attachment in attachments),
    )


@router.get(
    "/sessions/{thread_id}/attachments/{attachment_id}/reading",
    response_model=DocumentReadingResponse,
)
def read_session_attachment(
    thread_id: str,
    attachment_id: str,
    service: SessionAttachmentServiceDependency,
    start_line: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=200),
    expected_revision: str = "",
) -> DocumentReadingResponse:
    try:
        return read_session_document(
            service, thread_id, attachment_id, start_line=start_line,
            limit=limit, expected_revision=expected_revision,
        )
    except ReadingUnavailable as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.delete(
    "/attachments/{attachment_id}",
    response_model=AttachmentDeleteResponse,
)
def delete_session_attachment(
    attachment_id: str,
    service: SessionAttachmentServiceDependency,
) -> AttachmentDeleteResponse:
    if service.repository.get(attachment_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session attachment not found: {attachment_id}",
        )
    service.delete_attachment(attachment_id)
    return AttachmentDeleteResponse(deleted=True, attachment_id=attachment_id)


@router.post(
    "/attachments/{attachment_id}/retry",
    response_model=SessionAttachmentResponse,
)
def retry_session_attachment(
    attachment_id: str,
    service: SessionAttachmentServiceDependency,
) -> SessionAttachmentResponse:
    if service.repository.get(attachment_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session attachment not found: {attachment_id}",
        )
    try:
        attachment = service.retry(attachment_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _response(attachment)


@router.post(
    "/attachments/{attachment_id}/promote",
    response_model=AttachmentPromoteResponse,
)
def promote_session_attachment(
    attachment_id: str,
    service: SessionAttachmentServiceDependency,
) -> AttachmentPromoteResponse:
    if service.repository.get(attachment_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session attachment not found: {attachment_id}",
        )
    try:
        result = service.promote(attachment_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AttachmentPromoteResponse(
        status=str(result.get("status", "")),
        attachment_id=str(result.get("attachment_id", attachment_id)),
        promoted_rag_run_id=str(result.get("promoted_rag_run_id", "")),
        long_term_document_id=str(result.get("long_term_document_id", "")),
    )
