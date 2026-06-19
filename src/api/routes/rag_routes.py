"""RAG endpoints — status, index, upload, query, local-knowledge."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.api.models.rag import (
    LocalKnowledgeRequest,
    LocalKnowledgeResponse,
    RagIndexRequest,
    RagIndexResponse,
    RagQueryRequest,
    RagQueryResponse,
    RagStatusResponse,
)

router = APIRouter(tags=["rag"])


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
    if target.exists():
        index = load_rag_index(target)
        documents = len(index.documents)
        chunks = len(index.chunks)
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
        vector_backend=backend_status,
    )


@router.post("/rag/index", response_model=RagIndexResponse)
def build_rag_index_endpoint(request: RagIndexRequest) -> RagIndexResponse:
    from src.api import index_documents_with_stages

    try:
        target = _index_path(request.index_path)
        result = index_documents_with_stages(
            request.paths,
            index_path=target,
            max_chars=request.max_chars,
            overlap_chars=request.overlap_chars,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RagIndexResponse(
        documents=len(result.index.documents),
        chunks=len(result.index.chunks),
        index_path=str(target),
        stages=result.stages,
    )


@router.post("/rag/upload", response_model=RagIndexResponse)
async def upload_rag_documents(
    files: list[UploadFile] = File(...),
    index_path: str | None = None,
    max_chars: int = 900,
    overlap_chars: int = 120,
    mode: str = "append",
) -> RagIndexResponse:
    from src.api import append_documents_to_index_with_stages, index_documents_with_stages

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if max_chars <= 0 or max_chars > 10_000:
        raise HTTPException(status_code=400, detail="max_chars out of range")
    if overlap_chars < 0 or overlap_chars > 5_000:
        raise HTTPException(status_code=400, detail="overlap_chars out of range")
    if mode not in {"append", "rebuild"}:
        raise HTTPException(status_code=400, detail="mode must be append or rebuild")

    from src.application.helpers import _api_path, unique_upload_path

    upload_dir = _api_path("RAG_UPLOAD_DIR")
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    used_names: set[str] = set()
    for uploaded in files:
        target = unique_upload_path(upload_dir, uploaded.filename, used_names)
        target.write_bytes(await uploaded.read())
        saved_paths.append(target)

    target_index = _index_path(index_path)
    try:
        if mode == "rebuild":
            result = index_documents_with_stages(
                saved_paths,
                index_path=target_index,
                max_chars=max_chars,
                overlap_chars=overlap_chars,
            )
        else:
            result = append_documents_to_index_with_stages(
                saved_paths,
                index_path=target_index,
                max_chars=max_chars,
                overlap_chars=overlap_chars,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RagIndexResponse(
        documents=len(result.index.documents),
        chunks=len(result.index.chunks),
        index_path=str(target_index),
        stages=result.stages,
    )


@router.post("/rag/query", response_model=RagQueryResponse)
def query_rag_endpoint(request: RagQueryRequest) -> RagQueryResponse:
    from src.api import (
        build_rag_context,
        build_rag_debug,
        format_rag_sources,
        load_rag_index,
        search_documents,
    )
    from src.rag.eval import RagEvalCase, evaluate_case

    try:
        index = load_rag_index(_index_path(request.index_path))
        results = search_documents(
            index,
            request.query,
            top_k=request.top_k,
            min_score=request.min_score,
            retrieval_mode=request.retrieval_mode,
        )
        debug = build_rag_debug(
            index,
            request.query,
            results,
            retrieval_mode=request.retrieval_mode,
            top_k=request.top_k,
            min_score=request.min_score,
        )
        evaluation = None
        if request.expected_sources:
            evaluation = evaluate_case(
                index,
                RagEvalCase(
                    query=request.query,
                    expected_sources=tuple(request.expected_sources),
                    expected_terms=tuple(request.expected_terms),
                    top_k=request.top_k,
                    retrieval_mode=request.retrieval_mode,
                ),
                min_score=request.min_score,
            ).to_dict()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="RAG index not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RagQueryResponse(
        query=request.query,
        retrieval_mode=request.retrieval_mode,
        result_count=len(results),
        context=build_rag_context(results, max_chars=request.context_max_chars),
        sources=format_rag_sources(results),
        results=[result.to_dict() for result in results],
        debug=debug,
        evaluation=evaluation,
    )


@router.post("/rag", response_model=RagQueryResponse)
def query_rag_alias(request: RagQueryRequest) -> RagQueryResponse:
    return query_rag_endpoint(request)


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
