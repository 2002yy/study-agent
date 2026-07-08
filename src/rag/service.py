from __future__ import annotations

import secrets
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.rag.index import (
    _average_chunk_length,
    DEFAULT_RAG_INDEX_PATH,
    _document_frequency,
    _score_chunk,
    _tokenize,
    build_rag_index,
    load_rag_index,
    save_rag_index,
    search_rag_index,
)
from src.rag.backends import get_vector_backend_from_env
from src.rag.schema import RagIndex, RagSearchResult
from src.rag.vector import (
    RRF_K,
    cosine_similarity,
    embed_text,
    search_rag_index_hybrid,
    search_rag_index_vector,
)

RETRIEVAL_MODES = {"lexical", "vector", "hybrid", "backend_vector"}
HYBRID_RRF_K = RRF_K


@dataclass(frozen=True)
class RagIndexWriteResult:
    index: RagIndex
    stages: list[dict[str, Any]]
    activated: bool = True
    active_version: int = 0


def _transactional_save_index(index: RagIndex, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
    try:
        save_rag_index(index, temp_path)
        temp_path.replace(target)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _next_index_version(target: Path) -> int:
    if not target.is_file():
        return 1
    try:
        return load_rag_index(target).version + 1
    except (OSError, ValueError, KeyError):
        return 1


def _with_version(index: RagIndex, version: int) -> RagIndex:
    return RagIndex(
        version=version,
        documents=index.documents,
        chunks=index.chunks,
    )


def _document_id(document) -> str:
    return document.document_id or document.content_hash


def _chunk_document_id(chunk) -> str:
    return chunk.document_id or chunk.document_hash


def _merge_document_revisions(
    existing: RagIndex,
    incoming: RagIndex,
    *,
    version: int,
) -> RagIndex:
    incoming_documents = {
        _document_id(document): document for document in incoming.documents
    }
    incoming_ids = set(incoming_documents)
    documents = [
        incoming_documents.pop(_document_id(document), document)
        for document in existing.documents
    ]
    documents.extend(incoming_documents.values())
    chunks = [
        chunk
        for chunk in existing.chunks
        if _chunk_document_id(chunk) not in incoming_ids
    ]
    chunks.extend(incoming.chunks)
    return RagIndex(
        version=version,
        documents=tuple(documents),
        chunks=tuple(chunks),
    )


def _completed_local_stage(index: RagIndex, target: Path) -> dict[str, Any]:
    return {
        "name": "local",
        "status": "completed",
        "documents": len(index.documents),
        "chunks": len(index.chunks),
        "index_path": str(target),
    }


def _staged_local_stage(index: RagIndex, target: Path) -> dict[str, Any]:
    return {
        **_completed_local_stage(index, target),
        "status": "staged",
    }


def _activation_stage(
    index: RagIndex,
    target: Path,
    *,
    status: str,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "name": "activation",
        "status": status,
        "index_version": index.version,
        "index_path": str(target),
        "detail": detail,
    }


def _vector_stage(index: RagIndex) -> dict[str, Any]:
    try:
        backend = get_vector_backend_from_env()
        backend.upsert_index(index)
        return {
            "name": "vector",
            "status": "completed",
            "documents": len(index.documents),
            "chunks": len(index.chunks),
            "backend": backend.status().to_dict(),
        }
    except Exception as exc:
        return {
            "name": "vector",
            "status": "failed",
            "documents": len(index.documents),
            "chunks": len(index.chunks),
            "detail": str(exc),
        }


def index_documents(
    paths: Sequence[str | Path],
    *,
    index_path: str | Path = DEFAULT_RAG_INDEX_PATH,
    max_chars: int = 900,
    overlap_chars: int = 120,
) -> RagIndex:
    """Build and persist a local RAG index for user-provided documents."""
    index = build_rag_index(
        paths,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    index = _with_version(index, _next_index_version(Path(index_path)))
    _transactional_save_index(index, Path(index_path))
    get_vector_backend_from_env().upsert_index(index)
    return index


def index_documents_with_stages(
    paths: Sequence[str | Path],
    *,
    index_path: str | Path = DEFAULT_RAG_INDEX_PATH,
    max_chars: int = 900,
    overlap_chars: int = 120,
    target_version: int | None = None,
) -> RagIndexWriteResult:
    target = Path(index_path)
    index = build_rag_index(
        paths,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    active_version = _next_index_version(target) - 1
    index = _with_version(index, target_version or active_version + 1)
    vector_stage = _vector_stage(index)
    if vector_stage["status"] != "completed":
        return RagIndexWriteResult(
            index=index,
            stages=[
                _staged_local_stage(index, target),
                vector_stage,
                _activation_stage(
                    index,
                    target,
                    status="skipped",
                    detail="required vector stage failed",
                ),
            ],
            activated=False,
            active_version=active_version,
        )
    _transactional_save_index(index, target)
    return RagIndexWriteResult(
        index=index,
        stages=[
            _completed_local_stage(index, target),
            vector_stage,
            _activation_stage(index, target, status="completed"),
        ],
        active_version=index.version,
    )


def append_documents_to_index(
    paths: Sequence[str | Path],
    *,
    index_path: str | Path = DEFAULT_RAG_INDEX_PATH,
    max_chars: int = 900,
    overlap_chars: int = 120,
) -> RagIndex:
    """Append documents to an existing index, de-duplicating by content hash."""
    new_index = build_rag_index(
        paths,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    target = Path(index_path)
    if target.is_file():
        existing = load_rag_index(target)
    else:
        existing = RagIndex(version=new_index.version, documents=(), chunks=())

    merged = _merge_document_revisions(
        existing,
        new_index,
        version=existing.version + 1 if target.is_file() else 1,
    )
    _transactional_save_index(merged, target)
    get_vector_backend_from_env().upsert_index(merged)
    return merged


def append_documents_to_index_with_stages(
    paths: Sequence[str | Path],
    *,
    index_path: str | Path = DEFAULT_RAG_INDEX_PATH,
    max_chars: int = 900,
    overlap_chars: int = 120,
    target_version: int | None = None,
) -> RagIndexWriteResult:
    new_index = build_rag_index(
        paths,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    target = Path(index_path)
    if target.is_file():
        existing = load_rag_index(target)
    else:
        existing = RagIndex(version=new_index.version, documents=(), chunks=())

    merged = _merge_document_revisions(
        existing,
        new_index,
        version=target_version or (
            existing.version + 1 if target.is_file() else 1
        ),
    )
    vector_stage = _vector_stage(merged)
    if vector_stage["status"] != "completed":
        return RagIndexWriteResult(
            index=merged,
            stages=[
                _staged_local_stage(merged, target),
                vector_stage,
                _activation_stage(
                    merged,
                    target,
                    status="skipped",
                    detail="required vector stage failed",
                ),
            ],
            activated=False,
            active_version=existing.version if target.is_file() else 0,
        )
    _transactional_save_index(merged, target)
    return RagIndexWriteResult(
        index=merged,
        stages=[
            _completed_local_stage(merged, target),
            vector_stage,
            _activation_stage(merged, target, status="completed"),
        ],
        active_version=merged.version,
    )


def list_knowledge_documents(
    index_path: str | Path = DEFAULT_RAG_INDEX_PATH,
) -> dict[str, Any]:
    target = Path(index_path)
    if not target.is_file():
        return {
            "index_path": str(target),
            "index_exists": False,
            "index_version": 0,
            "documents": [],
            "chunks": 0,
        }
    index = load_rag_index(target)
    chunk_counts: dict[str, int] = {}
    for chunk in index.chunks:
        document_id = _chunk_document_id(chunk)
        chunk_counts[document_id] = chunk_counts.get(document_id, 0) + 1
    return {
        "index_path": str(target),
        "index_exists": True,
        "index_version": index.version,
        "documents": [
            {
                "document_id": _document_id(document),
                "revision_id": document.revision_id or document.content_hash,
                "title": document.title,
                "source_path": document.source_path,
                "file_type": document.file_type,
                "content_hash": document.content_hash,
                "chunks": chunk_counts.get(_document_id(document), 0),
                "metadata": document.metadata,
            }
            for document in index.documents
        ],
        "chunks": len(index.chunks),
    }


def delete_knowledge_document(
    document_id: str,
    *,
    index_path: str | Path = DEFAULT_RAG_INDEX_PATH,
    target_version: int | None = None,
) -> dict[str, Any]:
    target = Path(index_path)
    index = load_rag_index(target)
    documents = tuple(
        document for document in index.documents
        if _document_id(document) != document_id
    )
    if len(documents) == len(index.documents):
        raise ValueError(f"Knowledge document not found: {document_id}")
    chunks = tuple(
        chunk for chunk in index.chunks
        if _chunk_document_id(chunk) != document_id
    )
    updated = RagIndex(
        version=target_version or index.version + 1,
        documents=documents,
        chunks=chunks,
    )
    vector_stage = _vector_stage(updated)
    if vector_stage["status"] != "completed":
        return {
            "deleted_document_id": document_id,
            "documents": len(index.documents),
            "chunks": len(index.chunks),
            "index_path": str(target),
            "index_version": index.version,
            "staging_version": updated.version,
            "activated": False,
            "stages": [
                _staged_local_stage(updated, target),
                vector_stage,
                _activation_stage(
                    updated,
                    target,
                    status="skipped",
                    detail="required vector stage failed",
                ),
            ],
        }
    _transactional_save_index(updated, target)
    return {
        "deleted_document_id": document_id,
        "documents": len(updated.documents),
        "chunks": len(updated.chunks),
        "index_path": str(target),
        "index_version": updated.version,
        "activated": True,
        "stages": [
            _completed_local_stage(updated, target),
            vector_stage,
            _activation_stage(updated, target, status="completed"),
        ],
    }


def query_documents(
    query: str,
    *,
    index_path: str | Path = DEFAULT_RAG_INDEX_PATH,
    top_k: int = 5,
    min_score: float = 0.01,
    retrieval_mode: str = "lexical",
) -> list[RagSearchResult]:
    """Search the persisted local RAG index."""
    index = load_rag_index(index_path)
    return search_documents(
        index,
        query,
        top_k=top_k,
        min_score=min_score,
        retrieval_mode=retrieval_mode,
    )


def search_documents(
    index: RagIndex,
    query: str,
    *,
    top_k: int = 5,
    min_score: float = 0.01,
    retrieval_mode: str = "lexical",
) -> list[RagSearchResult]:
    """Search an in-memory RAG index."""
    if retrieval_mode == "lexical":
        return search_rag_index(index, query, top_k=top_k, min_score=min_score)
    if retrieval_mode == "vector":
        return search_rag_index_vector(index, query, top_k=top_k, min_score=min_score)
    if retrieval_mode == "hybrid":
        return search_rag_index_hybrid(
            index,
            query,
            top_k=top_k,
            min_score=min_score,
            rrf_k=HYBRID_RRF_K,
        )
    if retrieval_mode == "backend_vector":
        return get_vector_backend_from_env().query(
            index,
            query,
            top_k=top_k,
            min_score=min_score,
        )
    raise ValueError(f"Unsupported RAG retrieval mode: {retrieval_mode}")


def _lexical_scores(index: RagIndex, query: str) -> dict[str, float]:
    if not index.chunks:
        return {}
    df = _document_frequency(index.chunks)
    avg_chunk_length = _average_chunk_length(index.chunks)
    return {
        chunk.chunk_id: round(
            _score_chunk(query, chunk, df, len(index.chunks), avg_chunk_length)[0],
            6,
        )
        for chunk in index.chunks
    }


def _vector_scores(index: RagIndex, query: str) -> dict[str, float]:
    query_vector = embed_text(query)
    if not any(query_vector):
        return {chunk.chunk_id: 0.0 for chunk in index.chunks}
    return {
        chunk.chunk_id: round(cosine_similarity(query_vector, embed_text(chunk.text)), 6)
        for chunk in index.chunks
    }


def _score_breakdown(
    result: RagSearchResult,
    *,
    retrieval_mode: str,
    lexical_scores: dict[str, float],
    vector_scores: dict[str, float],
    lexical_ranks: dict[str, int],
    vector_ranks: dict[str, int],
    max_lexical_score: float,
) -> dict[str, Any]:
    chunk_id = result.chunk.chunk_id
    lexical_score = lexical_scores.get(chunk_id, 0.0)
    lexical_normalized = lexical_score / max_lexical_score if max_lexical_score > 0 else 0.0
    vector_score = vector_scores.get(chunk_id, 0.0)

    if retrieval_mode == "lexical":
        return {"lexical_score": round(lexical_score, 6)}
    if retrieval_mode == "vector":
        return {"vector_score": round(vector_score, 6)}
    if retrieval_mode == "backend_vector":
        return {"backend_score": round(result.score, 6)}
    if retrieval_mode == "hybrid":
        lexical_rank = lexical_ranks.get(chunk_id)
        vector_rank = vector_ranks.get(chunk_id)
        lexical_rrf = 1.0 / (HYBRID_RRF_K + lexical_rank) if lexical_rank else 0.0
        vector_rrf = 1.0 / (HYBRID_RRF_K + vector_rank) if vector_rank else 0.0
        return {
            "fusion": "rrf",
            "rrf_k": HYBRID_RRF_K,
            "lexical_rank": lexical_rank,
            "lexical_score": round(lexical_score, 6),
            "lexical_normalized": round(lexical_normalized, 6),
            "lexical_rrf": round(lexical_rrf, 6),
            "vector_rank": vector_rank,
            "vector_score": round(vector_score, 6),
            "vector_rrf": round(vector_rrf, 6),
            "combined_score": round(result.score, 6),
        }
    raise ValueError(f"Unsupported RAG retrieval mode: {retrieval_mode}")


def _rank_map(index: RagIndex, scores: dict[str, float]) -> dict[str, int]:
    chunks = {chunk.chunk_id: chunk for chunk in index.chunks}
    ranked = sorted(
        (
            (chunk_id, score)
            for chunk_id, score in scores.items()
            if score > 0 and chunk_id in chunks
        ),
        key=lambda item: (-item[1], chunks[item[0]].chunk_index, chunks[item[0]].title),
    )
    return {chunk_id: rank for rank, (chunk_id, _score) in enumerate(ranked, start=1)}


def _timed_stage(name: str, candidate_count: int, work: Callable[[], Any]) -> tuple[dict[str, Any], Any]:
    started = time.perf_counter()
    value = work()
    elapsed_ms = (time.perf_counter() - started) * 1000
    scored_count = (
        sum(1 for score in value.values() if score > 0)
        if isinstance(value, dict)
        else candidate_count
    )
    return (
        {
            "name": name,
            "candidate_count": candidate_count,
            "scored_count": scored_count,
            "elapsed_ms": round(elapsed_ms, 3),
        },
        value,
    )


def build_rag_debug(
    index: RagIndex,
    query: str,
    results: list[RagSearchResult],
    *,
    retrieval_mode: str,
    top_k: int,
    min_score: float,
) -> dict[str, Any]:
    """Build explainable retrieval diagnostics for API and evaluation views."""
    if retrieval_mode not in RETRIEVAL_MODES:
        raise ValueError(f"Unsupported RAG retrieval mode: {retrieval_mode}")

    stages: list[dict[str, Any]] = []
    lexical_scores: dict[str, float] = {}
    vector_scores: dict[str, float] = {}

    if retrieval_mode in {"lexical", "hybrid"}:
        stage, lexical_scores = _timed_stage(
            "lexical_bm25",
            len(index.chunks),
            lambda: _lexical_scores(index, query),
        )
        stages.append(stage)
    if retrieval_mode in {"vector", "hybrid"}:
        stage, vector_scores = _timed_stage(
            "local_vector",
            len(index.chunks),
            lambda: _vector_scores(index, query),
        )
        stages.append(stage)
    if retrieval_mode == "backend_vector":
        stages.append(
            {
                "name": "backend_vector",
                "candidate_count": len(index.chunks),
                "scored_count": len(results),
                "elapsed_ms": 0.0,
            }
        )

    max_lexical_score = max(lexical_scores.values(), default=0.0)
    lexical_ranks = _rank_map(index, lexical_scores)
    vector_ranks = _rank_map(index, vector_scores)
    query_terms = tuple(sorted(set(_tokenize(query))))

    return {
        "retrieval_mode": retrieval_mode,
        "top_k": top_k,
        "min_score": min_score,
        "candidate_count": len(index.chunks),
        "returned_count": len(results),
        "stages": stages,
        "query_terms": list(query_terms),
        "empty_query": not query_terms,
        "results": [
            {
                "rank": rank,
                "chunk_id": result.chunk.chunk_id,
                "source_path": result.chunk.source_path,
                "title": result.chunk.title,
                "score": result.score,
                "matched_terms": list(result.matched_terms),
                "score_breakdown": _score_breakdown(
                    result,
                    retrieval_mode=retrieval_mode,
                    lexical_scores=lexical_scores,
                    vector_scores=vector_scores,
                    lexical_ranks=lexical_ranks,
                    vector_ranks=vector_ranks,
                    max_lexical_score=max_lexical_score,
                ),
            }
            for rank, result in enumerate(results, start=1)
        ],
    }


def build_rag_context(
    results: list[RagSearchResult],
    *,
    max_chars: int = 3000,
) -> str:
    """Format retrieval results as a citation-first context block for an LLM call."""
    if max_chars <= 0:
        return ""
    if not results:
        return "No relevant local documents retrieved."

    sections: list[str] = []
    used_chars = 0
    for index, result in enumerate(results, start=1):
        chunk = result.chunk
        header = (
            f"[{index}] {chunk.title} "
            f"({chunk.source_path}:L{chunk.start_line}-L{chunk.end_line}, "
            f"score={result.score:.3f})"
        )
        body = chunk.text.strip()
        remaining = max_chars - used_chars - len(header) - 2
        if remaining <= 0:
            available = max_chars - used_chars
            if available > 0:
                sections.append(header[:available].rstrip())
            break
        if len(body) > remaining:
            body = body[: max(0, remaining - 3)].rstrip() + "..."
        section = f"{header}\n{body}"
        sections.append(section)
        used_chars += len(section) + 2
        if used_chars >= max_chars:
            break

    return "\n\n".join(sections) if sections else ""


def format_rag_sources(results: list[RagSearchResult]) -> str:
    """Format retrieval sources for UI display."""
    lines: list[str] = []
    for index, result in enumerate(results, start=1):
        chunk = result.chunk
        terms = ", ".join(result.matched_terms) if result.matched_terms else "-"
        lines.append(
            f"[{index}] {chunk.title} "
            f"({chunk.source_path}:L{chunk.start_line}-L{chunk.end_line}) "
            f"score={result.score:.3f}; matched={terms}"
        )
    return "\n".join(lines)
