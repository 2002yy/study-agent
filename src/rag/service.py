from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.rag.index import (
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
    cosine_similarity,
    embed_text,
    search_rag_index_hybrid,
    search_rag_index_vector,
)

RETRIEVAL_MODES = {"lexical", "vector", "hybrid", "backend_vector"}
HYBRID_LEXICAL_WEIGHT = 0.7


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
    save_rag_index(index, index_path)
    get_vector_backend_from_env().upsert_index(index)
    return index


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
            lexical_weight=HYBRID_LEXICAL_WEIGHT,
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
    return {
        chunk.chunk_id: round(_score_chunk(query, chunk, df, len(index.chunks))[0], 6)
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
    max_lexical_score: float,
) -> dict[str, float]:
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
        return {
            "lexical_weight": HYBRID_LEXICAL_WEIGHT,
            "lexical_score": round(lexical_score, 6),
            "lexical_normalized": round(lexical_normalized, 6),
            "vector_score": round(vector_score, 6),
            "combined_score": round(result.score, 6),
        }
    raise ValueError(f"Unsupported RAG retrieval mode: {retrieval_mode}")


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

    lexical_scores = _lexical_scores(index, query)
    vector_scores = _vector_scores(index, query)
    max_lexical_score = max(lexical_scores.values(), default=0.0)
    query_terms = tuple(sorted(set(_tokenize(query))))

    return {
        "retrieval_mode": retrieval_mode,
        "top_k": top_k,
        "min_score": min_score,
        "candidate_count": len(index.chunks),
        "returned_count": len(results),
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
