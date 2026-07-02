"""RAG endpoints — status, index, upload, query, local-knowledge."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from src.api.models.rag import (
    LocalKnowledgeRequest,
    LocalKnowledgeResponse,
    RagIndexRequest,
    RagIndexResponse,
    RagQueryRequest,
    RagQueryResponse,
    RagStatusResponse,
    RagRunListResponse,
    RagRunResponse,
    KnowledgeDocumentDeleteResponse,
    KnowledgeDocumentListResponse,
)
from src.application.rag_run_service import RagRunService
from src.rag.upload_validation import (
    UploadCandidate,
    validate_upload_batch,
)
from src.application.runtime_repository import get_rag_run_service

router = APIRouter(tags=["rag"])
RagRunServiceDependency = Annotated[RagRunService, Depends(get_rag_run_service)]


def _run_response(run) -> RagRunResponse:
    return RagRunResponse(**asdict(run))


def _index_path(value: str | None) -> __import__("pathlib").Path:
    from pathlib import Path
    from src.rag.index import DEFAULT_RAG_INDEX_PATH

    return Path(value) if value else DEFAULT_RAG_INDEX_PATH


@router.get("/rag/status", response_model=RagStatusResponse)
def rag_status(index_path: str | None = None) -> RagStatusResponse:
    from src.api import get_vector_backend_from_env, load_rag_index

    target = _index_path(index_path)
    documents = 0
    chunks = 0
    index_version = 0
    if target.exists():
        index = load_rag_index(target)
        documents = len(index.documents)
        chunks = len(index.chunks)
        index_version = index.version
    try:
        backend_status = get_vector_backend_from_env().status().to_dict()
    except Exception as exc:
        backend_status = {
            "name": "unknown",
            "available": False,
            "detail": str(exc),
        }
    return RagStatusResponse(
        index_path=str(target),
        index_exists=target.exists(),
        documents=documents,
        chunks=chunks,
        index_version=index_version,
        vector_backend=backend_status,
    )


@router.post("/rag-runs/index", response_model=RagRunResponse)
def create_rag_index_run(
    request: RagIndexRequest,
    service: RagRunServiceDependency,
) -> RagRunResponse:
    try:
        target = _index_path(request.index_path)
        run = service.index(
            [__import__("pathlib").Path(path) for path in request.paths],
            mode="rebuild",
            index_path=target,
            max_chars=request.max_chars,
            overlap_chars=request.overlap_chars,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _run_response(run)


@router.post("/rag/index", response_model=RagIndexResponse, deprecated=True)
def build_rag_index_endpoint(
    request: RagIndexRequest,
    service: RagRunServiceDependency,
) -> RagIndexResponse:
    run = create_rag_index_run(request, service)
    return RagIndexResponse(**run.result)


async def _save_uploads(files: list[UploadFile]):
    from src.application.helpers import _api_path, unique_upload_path

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    upload_dir = _api_path("RAG_UPLOAD_DIR")
    upload_dir.mkdir(parents=True, exist_ok=True)
    candidates = [
        UploadCandidate(
            filename=uploaded.filename or "",
            content_type=uploaded.content_type or "application/octet-stream",
            data=await uploaded.read(),
        )
        for uploaded in files
    ]
    validate_upload_batch(candidates)
    saved_paths = []
    used_names: set[str] = set()
    for candidate in candidates:
        base_name = Path(candidate.filename or "document").name or "document"
        if base_name not in used_names:
            used_names.add(base_name)
            target = upload_dir / base_name
        else:
            target = unique_upload_path(
                upload_dir, candidate.filename, used_names
            )
        target.write_bytes(candidate.data)
        saved_paths.append(target)
    return saved_paths


async def _create_upload_run(
    *,
    files: list[UploadFile],
    service: RagRunService,
    mode: str,
    index_path: str | None,
    max_chars: int,
    overlap_chars: int,
) -> RagRunResponse:
    if max_chars <= 0 or max_chars > 10_000:
        raise HTTPException(status_code=400, detail="max_chars out of range")
    if overlap_chars < 0 or overlap_chars > 5_000:
        raise HTTPException(status_code=400, detail="overlap_chars out of range")
    try:
        saved_paths = await _save_uploads(files)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        run = service.index(
            saved_paths,
            mode=mode,
            index_path=_index_path(index_path),
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_response(run)


@router.post("/rag-runs/upload", response_model=RagRunResponse)
async def create_rag_upload_run(
    service: RagRunServiceDependency,
    files: list[UploadFile] = File(...),
    index_path: str | None = None,
    max_chars: int = 900,
    overlap_chars: int = 120,
) -> RagRunResponse:
    return await _create_upload_run(
        files=files, service=service, mode="upload", index_path=index_path,
        max_chars=max_chars, overlap_chars=overlap_chars,
    )


@router.post("/rag-runs/rebuild", response_model=RagRunResponse)
async def create_rag_rebuild_run(
    service: RagRunServiceDependency,
    files: list[UploadFile] = File(...),
    index_path: str | None = None,
    max_chars: int = 900,
    overlap_chars: int = 120,
) -> RagRunResponse:
    return await _create_upload_run(
        files=files, service=service, mode="rebuild", index_path=index_path,
        max_chars=max_chars, overlap_chars=overlap_chars,
    )


@router.post("/rag/upload", response_model=RagIndexResponse)
async def upload_rag_documents(
    service: RagRunServiceDependency,
    files: list[UploadFile] = File(...),
    index_path: str | None = None,
    max_chars: int = 900,
    overlap_chars: int = 120,
    mode: str = "append",
) -> RagIndexResponse:
    if mode not in {"append", "rebuild"}:
        raise HTTPException(status_code=400, detail="mode must be append or rebuild")
    run = await _create_upload_run(
        files=files, service=service,
        mode="rebuild" if mode == "rebuild" else "upload",
        index_path=index_path, max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    return RagIndexResponse(**run.result)


@router.post("/rag-runs/query", response_model=RagRunResponse)
def create_rag_query_run(
    request: RagQueryRequest,
    service: RagRunServiceDependency,
) -> RagRunResponse:
    try:
        run = service.query(
            request.model_dump(exclude={"index_path"}),
            index_path=_index_path(request.index_path),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="RAG index not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_response(run)


@router.post("/rag/query", response_model=RagQueryResponse, deprecated=True)
def query_rag_endpoint(
    request: RagQueryRequest,
    service: RagRunServiceDependency,
) -> RagQueryResponse:
    run = create_rag_query_run(request, service)
    return RagQueryResponse(**run.result)


@router.post("/rag", response_model=RagQueryResponse, deprecated=True)
def query_rag_alias(
    request: RagQueryRequest,
    service: RagRunServiceDependency,
) -> RagQueryResponse:
    return query_rag_endpoint(request, service)


@router.get("/rag-runs", response_model=RagRunListResponse)
def list_rag_runs(
    service: RagRunServiceDependency,
    kind: str | None = None,
    limit: int = 20,
) -> RagRunListResponse:
    return RagRunListResponse(
        runs=[
            _run_response(run)
            for run in service.list(kind=kind, limit=limit)
        ]
    )


@router.get("/rag-runs/{run_id}", response_model=RagRunResponse)
def get_rag_run(
    run_id: str,
    service: RagRunServiceDependency,
) -> RagRunResponse:
    try:
        return _run_response(service.get(run_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/knowledge-base/documents",
    response_model=KnowledgeDocumentListResponse,
)
def list_knowledge_base_documents(
    service: RagRunServiceDependency,
    index_path: str | None = None,
) -> KnowledgeDocumentListResponse:
    return KnowledgeDocumentListResponse(
        **service.documents(index_path=_index_path(index_path))
    )


@router.delete(
    "/knowledge-base/documents/{document_id}",
    response_model=KnowledgeDocumentDeleteResponse,
)
def delete_knowledge_base_document(
    document_id: str,
    service: RagRunServiceDependency,
    index_path: str | None = None,
) -> KnowledgeDocumentDeleteResponse:
    try:
        return KnowledgeDocumentDeleteResponse(
            **service.delete_document(
                document_id,
                index_path=_index_path(index_path),
            )
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="RAG index not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/rag/local-knowledge", response_model=LocalKnowledgeResponse)
def local_knowledge_endpoint(request: LocalKnowledgeRequest) -> LocalKnowledgeResponse:
    from src.api import retrieve_local_knowledge

    result = retrieve_local_knowledge(
        request.query,
        enabled=request.enabled,
        force=request.force,
        index_path=_index_path(request.index_path),
        top_k=request.top_k,
        min_score=request.min_score,
        retrieval_mode=request.retrieval_mode,
        context_max_chars=request.context_max_chars,
        allow_rewrite=request.allow_rewrite,
        weak_score_threshold=request.weak_score_threshold,
    )
    return LocalKnowledgeResponse(**result.to_dict())
