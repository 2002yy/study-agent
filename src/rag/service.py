from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from src.rag.backends import get_vector_backend_from_env
from src.rag.index import (
    DEFAULT_RAG_INDEX_PATH,
    _average_chunk_length,
    _document_frequency,
    _score_chunk,
    _tokenize,
    build_rag_index,
    load_rag_index,
    save_rag_index,
    search_rag_index,
)
from src.rag.rerank import apply_reranker, reranker_config_from_env
from src.rag.schema import (
    EVIDENCE_STATUS_ACTIVE,
    EVIDENCE_STATUS_SUPERSEDED,
    EVIDENCE_STATUSES,
    RagIndex,
    RagSearchResult,
)
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


@dataclass(frozen=True)
class RagSearchDiagnostics:
    results: list[RagSearchResult]
    debug: dict[str, Any]


def normalize_evidence_status(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in EVIDENCE_STATUSES:
        supported = ", ".join(sorted(EVIDENCE_STATUSES))
        raise ValueError(f"Unsupported evidence status: {value!r}; expected one of {supported}")
    return normalized


def retrievable_rag_index(index: RagIndex) -> RagIndex:
    """Return the active-only view used by every normal retrieval path."""
    active_document_ids = {
        _document_id(document)
        for document in index.documents
        if document.evidence_status == EVIDENCE_STATUS_ACTIVE
    }
    documents = tuple(
        document
        for document in index.documents
        if _document_id(document) in active_document_ids
    )
    chunks = tuple(
        chunk
        for chunk in index.chunks
        if chunk.evidence_status == EVIDENCE_STATUS_ACTIVE
        and _chunk_document_id(chunk) in active_document_ids
    )
    return RagIndex(version=index.version, documents=documents, chunks=chunks)


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
    existing_by_id = {_document_id(document): document for document in existing.documents}
    preserved_eligibility: dict[str, tuple[str, str]] = {}
    incoming_documents = {}
    for document in incoming.documents:
        document_id = _document_id(document)
        previous = existing_by_id.get(document_id)
        if previous is not None:
            preserved_eligibility[document_id] = (
                previous.evidence_status,
                previous.superseded_by_document_id,
            )
            document = replace(
                document,
                evidence_status=previous.evidence_status,
                superseded_by_document_id=previous.superseded_by_document_id,
            )
        incoming_documents[document_id] = document

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
    for chunk in incoming.chunks:
        eligibility = preserved_eligibility.get(_chunk_document_id(chunk))
        if eligibility is not None:
            chunk = replace(
                chunk,
                evidence_status=eligibility[0],
                superseded_by_document_id=eligibility[1],
            )
        chunks.append(chunk)

    return RagIndex(
        version=version,
        documents=tuple(documents),
        chunks=tuple(chunks),
    )


def _completed_local_stage(index: RagIndex, target: Path) -> dict[str, Any]:
    active = retrievable_rag_index(index)
    return {
        "name": "local",
        "status": "completed",
        "documents": len(index.documents),
        "chunks": len(index.chunks),
        "retrievable_documents": len(active.documents),
        "retrievable_chunks": len(active.chunks),
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
    active = retrievable_rag_index(index)
    try:
        backend = get_vector_backend_from_env()
        backend.upsert_index(active)
        return {
            "name": "vector",
            "status": "completed",
            "documents": len(index.documents),
            "chunks": len(index.chunks),
            "retrievable_documents": len(active.documents),
            "retrievable_chunks": len(active.chunks),
            "backend": backend.status().to_dict(),
        }
    except Exception as exc:
        return {
            "name": "vector",
            "status": "failed",
            "documents": len(index.documents),
            "chunks": len(index.chunks),
            "retrievable_documents": len(active.documents),
            "retrievable_chunks": len(active.chunks),
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
    get_vector_backend_from_env().upsert_index(retrievable_rag_index(index))
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
    """Append documents to an existing index, preserving document eligibility."""
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
    get_vector_backend_from_env().upsert_index(retrievable_rag_index(merged))
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
            "retrievable_documents": 0,
            "retrievable_chunks": 0,
        }
    index = load_rag_index(target)
    active = retrievable_rag_index(index)
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
                "evidence_status": document.evidence_status,
                "superseded_by_document_id": document.superseded_by_document_id,
                "metadata": document.metadata,
            }
            for document in index.documents
        ],
        "chunks": len(index.chunks),
        "retrievable_documents": len(active.documents),
        "retrievable_chunks": len(active.chunks),
    }


def set_knowledge_document_evidence_status(
    document_id: str,
    evidence_status: str,
    *,
    superseded_by_document_id: str = "",
    index_path: str | Path = DEFAULT_RAG_INDEX_PATH,
    target_version: int | None = None,
) -> dict[str, Any]:
    target = Path(index_path)
    index = load_rag_index(target)
    normalized_status = normalize_evidence_status(evidence_status)
    document_ids = {_document_id(document) for document in index.documents}
    if document_id not in document_ids:
        raise ValueError(f"Knowledge document not found: {document_id}")

    replacement_id = superseded_by_document_id.strip()
    if normalized_status != EVIDENCE_STATUS_SUPERSEDED:
        replacement_id = ""
    elif replacement_id:
        if replacement_id == document_id:
            raise ValueError("A document cannot supersede itself")
        if replacement_id not in document_ids:
            raise ValueError(f"Superseding document not found: {replacement_id}")
        replacement = next(
            document
            for document in index.documents
            if _document_id(document) == replacement_id
        )
        if replacement.evidence_status != EVIDENCE_STATUS_ACTIVE:
            raise ValueError("Superseding document must be active")

    documents = tuple(
        replace(
            document,
            evidence_status=normalized_status,
            superseded_by_document_id=replacement_id,
        )
        if _document_id(document) == document_id
        else document
        for document in index.documents
    )
    chunks = tuple(
        replace(
            chunk,
            evidence_status=normalized_status,
            superseded_by_document_id=replacement_id,
        )
        if _chunk_document_id(chunk) == document_id
        else chunk
        for chunk in index.chunks
    )
    updated = RagIndex(
        version=target_version or index.version + 1,
        documents=documents,
        chunks=chunks,
    )
    vector_stage = _vector_stage(updated)
    active = retrievable_rag_index(updated)
    if vector_stage["status"] != "completed":
        return {
            "document_id": document_id,
            "evidence_status": normalized_status,
            "superseded_by_document_id": replacement_id,
            "documents": len(index.documents),
            "chunks": len(index.chunks),
            "retrievable_documents": len(retrievable_rag_index(index).documents),
            "retrievable_chunks": len(retrievable_rag_index(index).chunks),
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
        "document_id": document_id,
        "evidence_status": normalized_status,
        "superseded_by_document_id": replacement_id,
        "documents": len(updated.documents),
        "chunks": len(updated.chunks),
        "retrievable_documents": len(active.documents),
        "retrievable_chunks": len(active.chunks),
        "index_path": str(target),
        "index_version": updated.version,
        "activated": True,
        "stages": [
            _completed_local_stage(updated, target),
            vector_stage,
            _activation_stage(updated, target, status="completed"),
        ],
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
    documents = tuple(
        replace(document, superseded_by_document_id="")
        if document.superseded_by_document_id == document_id
        else document
        for document in documents
    )
    chunks = tuple(
        replace(chunk, superseded_by_document_id="")
        if chunk.superseded_by_document_id == document_id
        else chunk
        for chunk in chunks
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
    """Search the active evidence view of the persisted local RAG index."""
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
    metadata_filters: dict[str, Any] | None = None,
    max_chunks_per_source: int = 0,
    suppress_duplicate_text: bool = True,
    reranker: str | None = None,
    rerank_top_n: int | None = None,
    rerank_latency_budget_ms: int | None = None,
    rerank_cost_budget: float | None = None,
) -> list[RagSearchResult]:
    """Search only active evidence in an in-memory RAG index."""
    active = retrievable_rag_index(index)
    results, _post_filter, _reranker_stage = _search_documents_with_stats(
        active,
        query,
        top_k=top_k,
        min_score=min_score,
        retrieval_mode=retrieval_mode,
        metadata_filters=metadata_filters,
        max_chunks_per_source=max_chunks_per_source,
        suppress_duplicate_text=suppress_duplicate_text,
        reranker=reranker,
        rerank_top_n=rerank_top_n,
        rerank_latency_budget_ms=rerank_latency_budget_ms,
        rerank_cost_budget=rerank_cost_budget,
    )
    return results


def search_documents_with_debug(
    index: RagIndex,
    query: str,
    *,
    top_k: int = 5,
    min_score: float = 0.01,
    retrieval_mode: str = "lexical",
    metadata_filters: dict[str, Any] | None = None,
    max_chunks_per_source: int = 0,
    suppress_duplicate_text: bool = True,
    reranker: str | None = None,
    rerank_top_n: int | None = None,
    rerank_latency_budget_ms: int | None = None,
    rerank_cost_budget: float | None = None,
) -> RagSearchDiagnostics:
    active = retrievable_rag_index(index)
    started = time.perf_counter()
    results, post_filter, reranker_stage = _search_documents_with_stats(
        active,
        query,
        top_k=top_k,
        min_score=min_score,
        retrieval_mode=retrieval_mode,
        metadata_filters=metadata_filters,
        max_chunks_per_source=max_chunks_per_source,
        suppress_duplicate_text=suppress_duplicate_text,
        reranker=reranker,
        rerank_top_n=rerank_top_n,
        rerank_latency_budget_ms=rerank_latency_budget_ms,
        rerank_cost_budget=rerank_cost_budget,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    debug = build_rag_debug(
        active,
        query,
        results,
        retrieval_mode=retrieval_mode,
        top_k=top_k,
        min_score=min_score,
        metadata_filters=metadata_filters,
        max_chunks_per_source=max_chunks_per_source,
        suppress_duplicate_text=suppress_duplicate_text,
        post_filter=post_filter,
        reranker_stage=reranker_stage,
        stage_timings={"backend_vector": elapsed_ms} if retrieval_mode == "backend_vector" else None,
    )
    debug["evidence_eligibility"] = {
        "total_documents": len(index.documents),
        "total_chunks": len(index.chunks),
        "retrievable_documents": len(active.documents),
        "retrievable_chunks": len(active.chunks),
        "excluded_documents": len(index.documents) - len(active.documents),
        "excluded_chunks": len(index.chunks) - len(active.chunks),
    }
    return RagSearchDiagnostics(results=results, debug=debug)


def _search_documents_with_stats(
    index: RagIndex,
    query: str,
    *,
    top_k: int,
    min_score: float,
    retrieval_mode: str,
    metadata_filters: dict[str, Any] | None,
    max_chunks_per_source: int,
    suppress_duplicate_text: bool,
    reranker: str | None,
    rerank_top_n: int | None,
    rerank_latency_budget_ms: int | None,
    rerank_cost_budget: float | None,
) -> tuple[list[RagSearchResult], dict[str, Any], dict[str, Any] | None]:
    reranker_config = reranker_config_from_env(
        name=reranker,
        top_n=rerank_top_n,
        latency_budget_ms=rerank_latency_budget_ms,
        cost_budget=rerank_cost_budget,
    )
    candidate_k = _candidate_limit(
        index,
        top_k,
        metadata_filters,
        max_chunks_per_source,
        suppress_duplicate_text,
        reranker_config.enabled,
    )
    if retrieval_mode == "lexical":
        raw_results = search_rag_index(index, query, top_k=candidate_k, min_score=min_score)
    elif retrieval_mode == "vector":
        raw_results = search_rag_index_vector(index, query, top_k=candidate_k, min_score=min_score)
    elif retrieval_mode == "hybrid":
        raw_results = search_rag_index_hybrid(
            index,
            query,
            top_k=candidate_k,
            min_score=min_score,
            rrf_k=HYBRID_RRF_K,
        )
    elif retrieval_mode == "backend_vector":
        raw_results = get_vector_backend_from_env().query(
            index,
            query,
            top_k=candidate_k,
            min_score=min_score,
        )
    else:
        raise ValueError(f"Unsupported RAG retrieval mode: {retrieval_mode}")
    rerank_outcome = apply_reranker(query, raw_results, config=reranker_config)
    reranker_stage = rerank_outcome.stage if reranker_config.enabled else None
    raw_results = rerank_outcome.results
    results, post_filter = _post_process_results(
        index,
        raw_results,
        top_k=top_k,
        metadata_filters=metadata_filters,
        max_chunks_per_source=max_chunks_per_source,
        suppress_duplicate_text=suppress_duplicate_text,
    )
    return results, post_filter, reranker_stage


def _candidate_limit(
    index: RagIndex,
    top_k: int,
    metadata_filters: dict[str, Any] | None,
    max_chunks_per_source: int,
    suppress_duplicate_text: bool,
    reranker_enabled: bool,
) -> int:
    if top_k <= 0:
        return 0
    needs_post_filter = (
        bool(metadata_filters)
        or max_chunks_per_source > 0
        or suppress_duplicate_text
        or reranker_enabled
    )
    if not needs_post_filter:
        return top_k
    return min(len(index.chunks), max(top_k, top_k * 4))


def _post_process_results(
    index: RagIndex,
    results: list[RagSearchResult],
    *,
    top_k: int,
    metadata_filters: dict[str, Any] | None,
    max_chunks_per_source: int,
    suppress_duplicate_text: bool,
) -> tuple[list[RagSearchResult], dict[str, Any]]:
    eligible_chunk_ids = {chunk.chunk_id for chunk in index.chunks}
    stats: dict[str, Any] = {
        "input_count": len(results),
        "output_count": 0,
        "ineligible_suppressed": 0,
        "metadata_filtered": 0,
        "duplicates_suppressed": 0,
        "source_diversity_suppressed": 0,
        "metadata_filters": metadata_filters or {},
        "max_chunks_per_source": max_chunks_per_source,
        "suppress_duplicate_text": suppress_duplicate_text,
    }
    selected: list[RagSearchResult] = []
    seen_texts: set[str] = set()
    source_counts: dict[str, int] = {}
    for result in results:
        if result.chunk.chunk_id not in eligible_chunk_ids:
            stats["ineligible_suppressed"] += 1
            continue
        if metadata_filters and not _matches_metadata_filters(index, result, metadata_filters):
            stats["metadata_filtered"] += 1
            continue
        text_key = _normalized_result_text(result)
        if suppress_duplicate_text and text_key in seen_texts:
            stats["duplicates_suppressed"] += 1
            continue
        source_key = result.chunk.document_id or result.chunk.source_path
        if max_chunks_per_source > 0 and source_counts.get(source_key, 0) >= max_chunks_per_source:
            stats["source_diversity_suppressed"] += 1
            continue
        selected.append(result)
        seen_texts.add(text_key)
        source_counts[source_key] = source_counts.get(source_key, 0) + 1
        if len(selected) >= top_k:
            break
    stats["output_count"] = len(selected)
    return selected, stats


def _normalized_result_text(result: RagSearchResult) -> str:
    return re.sub(r"\s+", " ", result.chunk.text.strip().lower())


def _matches_metadata_filters(
    index: RagIndex,
    result: RagSearchResult,
    metadata_filters: dict[str, Any],
) -> bool:
    metadata = _chunk_metadata(index, result)
    return all(_metadata_value_matches(metadata.get(key), expected) for key, expected in metadata_filters.items())


def _chunk_metadata(index: RagIndex, result: RagSearchResult) -> dict[str, Any]:
    chunk = result.chunk
    document = next(
        (
            item
            for item in index.documents
            if item.document_id == chunk.document_id or item.content_hash == chunk.document_hash
        ),
        None,
    )
    metadata: dict[str, Any] = {
        "source_path": chunk.source_path,
        "title": chunk.title,
        "document_id": chunk.document_id,
        "revision_id": chunk.revision_id,
        "document_hash": chunk.document_hash,
        "evidence_status": chunk.evidence_status,
        "superseded_by_document_id": chunk.superseded_by_document_id,
    }
    metadata.update(chunk.metadata)
    if document is not None:
        metadata.update(
            {
                "document_title": document.title,
                "file_type": document.file_type,
                "document_content_hash": document.content_hash,
                "document_evidence_status": document.evidence_status,
                "document_superseded_by_document_id": document.superseded_by_document_id,
            }
        )
        metadata.update(document.metadata)
    return metadata


def _metadata_value_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, list | tuple | set):
        return actual in expected
    return actual == expected


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
    metadata_filters: dict[str, Any] | None = None,
    max_chunks_per_source: int = 0,
    suppress_duplicate_text: bool = True,
    post_filter: dict[str, Any] | None = None,
    reranker_stage: dict[str, Any] | None = None,
    stage_timings: dict[str, float] | None = None,
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
                "elapsed_ms": round((stage_timings or {}).get("backend_vector", 0.0), 3),
            }
        )
    if reranker_stage is not None:
        stages.append(reranker_stage)

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
        "post_filter": post_filter
        or {
            "input_count": len(results),
            "output_count": len(results),
            "ineligible_suppressed": 0,
            "metadata_filtered": 0,
            "duplicates_suppressed": 0,
            "source_diversity_suppressed": 0,
            "metadata_filters": metadata_filters or {},
            "max_chunks_per_source": max_chunks_per_source,
            "suppress_duplicate_text": suppress_duplicate_text,
        },
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
