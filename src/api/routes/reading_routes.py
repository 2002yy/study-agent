"""Read-only original/retained-source views, with the existing API auth."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from src.application.document_reading import DocumentReadingResponse, ReadingUnavailable
from src.application.original_reading import (
    knowledge_original,
    session_original,
    read_saved_web,
)
from src.application.runtime_repository import (
    get_session_attachment_service,
    get_web_lookup_service,
)
from src.rag import index as rag_index

router = APIRouter(tags=["reading"])
AttachmentService = Annotated[Any, Depends(get_session_attachment_service)]
WebService = Annotated[Any, Depends(get_web_lookup_service)]


def pdf_response(data):
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/knowledge-base/documents/{document_id}/original")
def knowledge_pdf(document_id: str, expected_revision: str = ""):
    try:
        return pdf_response(
            knowledge_original(
                rag_index.DEFAULT_RAG_INDEX_PATH, document_id, expected_revision
            )
        )
    except ReadingUnavailable as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("/sessions/{thread_id}/attachments/{attachment_id}/original")
def attachment_pdf(
    thread_id: str,
    attachment_id: str,
    service: AttachmentService,
    expected_revision: str = "",
):
    try:
        return pdf_response(
            session_original(service, thread_id, attachment_id, expected_revision)
        )
    except ReadingUnavailable as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get(
    "/sessions/{thread_id}/research-runs/{run_id}/sources/reading",
    response_model=DocumentReadingResponse,
)
def web_source(
    thread_id: str,
    run_id: str,
    service: WebService,
    url: str,
    start_line: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=200),
    expected_revision: str = "",
):
    try:
        return read_saved_web(
            service,
            thread_id,
            run_id,
            url,
            start_line=start_line,
            limit=limit,
            expected_revision=expected_revision,
        )
    except ReadingUnavailable as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
