from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.rag import build_rag_context, format_rag_sources, index_documents
from src.rag.eval import RagEvalCase, evaluate_case
from src.rag.index import DEFAULT_RAG_INDEX_PATH, load_rag_index
from src.rag.service import build_rag_debug, search_documents


class HealthResponse(BaseModel):
    status: str
    service: str
    rag_index_exists: bool


class RagIndexRequest(BaseModel):
    paths: list[str] = Field(min_length=1)
    index_path: str | None = None
    max_chars: int = Field(default=900, gt=0, le=10_000)
    overlap_chars: int = Field(default=120, ge=0, le=5_000)


class RagIndexResponse(BaseModel):
    documents: int
    chunks: int
    index_path: str


class RagQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    index_path: str | None = None
    top_k: int = Field(default=5, gt=0, le=20)
    min_score: float = Field(default=0.01, ge=0)
    retrieval_mode: str = Field(default="hybrid")
    context_max_chars: int = Field(default=3000, gt=0, le=20_000)
    expected_sources: list[str] = Field(default_factory=list)
    expected_terms: list[str] = Field(default_factory=list)


class RagQueryResponse(BaseModel):
    query: str
    retrieval_mode: str
    result_count: int
    context: str
    sources: str
    results: list[dict[str, Any]]
    debug: dict[str, Any]
    evaluation: dict[str, Any] | None = None


app = FastAPI(title="Study Agent API", version="0.1.0")


def _index_path(value: str | None) -> Path:
    return Path(value) if value else DEFAULT_RAG_INDEX_PATH


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="study-agent",
        rag_index_exists=DEFAULT_RAG_INDEX_PATH.exists(),
    )


@app.post("/rag/index", response_model=RagIndexResponse)
def build_rag_index_endpoint(request: RagIndexRequest) -> RagIndexResponse:
    try:
        target = _index_path(request.index_path)
        index = index_documents(
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
        documents=len(index.documents),
        chunks=len(index.chunks),
        index_path=str(target),
    )


@app.post("/rag/query", response_model=RagQueryResponse)
def query_rag_endpoint(request: RagQueryRequest) -> RagQueryResponse:
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


@app.post("/rag", response_model=RagQueryResponse)
def query_rag_alias(request: RagQueryRequest) -> RagQueryResponse:
    return query_rag_endpoint(request)
