"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from src.api.models.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    from src.rag.index import DEFAULT_RAG_INDEX_PATH

    return HealthResponse(
        status="ok",
        service="study-agent",
        rag_index_exists=DEFAULT_RAG_INDEX_PATH.exists(),
    )
