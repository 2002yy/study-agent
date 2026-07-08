from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable

from src.rag.index import _tokenize, search_rag_index
from src.rag.schema import RagIndex, RagSearchResult

VECTOR_DIMENSIONS = 256
RRF_K = 60


def embed_text(text: str, *, dimensions: int = VECTOR_DIMENSIONS) -> tuple[float, ...]:
    """Embed text with deterministic local hashing for retrieval prototyping."""
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")

    values = [0.0] * dimensions
    for token in _tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:2], "big") % dimensions
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        values[bucket] += sign

    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return tuple(values)
    return tuple(value / norm for value in values)


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have the same dimensions")
    return sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True))


def search_rag_index_vector(
    index: RagIndex,
    query: str,
    *,
    top_k: int = 5,
    min_score: float = 0.05,
) -> list[RagSearchResult]:
    if top_k <= 0 or not index.chunks:
        return []

    query_vector = embed_text(query)
    if not any(query_vector):
        return []

    query_terms = set(_tokenize(query))
    scored: list[RagSearchResult] = []
    for chunk in index.chunks:
        chunk_vector = embed_text(chunk.text)
        score = cosine_similarity(query_vector, chunk_vector)
        if score >= min_score:
            chunk_terms = set(_tokenize(chunk.text))
            scored.append(
                RagSearchResult(
                    chunk=chunk,
                    score=round(score, 6),
                    matched_terms=tuple(sorted(query_terms & chunk_terms)),
                )
            )

    scored.sort(key=lambda result: (-result.score, result.chunk.chunk_index, result.chunk.title))
    return scored[:top_k]


def search_rag_index_hybrid(
    index: RagIndex,
    query: str,
    *,
    top_k: int = 5,
    min_score: float = 0.01,
    rrf_k: int = RRF_K,
) -> list[RagSearchResult]:
    if top_k <= 0 or not index.chunks:
        return []
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    if not _tokenize(query):
        return []

    lexical_results = [
        result
        for result in search_rag_index(index, query, top_k=len(index.chunks), min_score=0.0)
        if result.score > 0
    ]
    vector_results = [
        result
        for result in search_rag_index_vector(
            index,
            query,
            top_k=len(index.chunks),
            min_score=0.0,
        )
        if result.score > 0
    ]

    by_chunk_id = {chunk.chunk_id: chunk for chunk in index.chunks}
    fused_scores: dict[str, float] = {}
    matched_terms: dict[str, set[str]] = {}

    for result_set in (lexical_results, vector_results):
        _apply_rrf(result_set, fused_scores, matched_terms, rrf_k=rrf_k)

    scored: list[RagSearchResult] = []
    for chunk_id, chunk in by_chunk_id.items():
        combined = fused_scores.get(chunk_id, 0.0)
        if combined >= min_score:
            scored.append(
                RagSearchResult(
                    chunk=chunk,
                    score=round(combined, 6),
                    matched_terms=tuple(sorted(matched_terms.get(chunk_id, set()))),
                )
            )

    scored.sort(key=lambda result: (-result.score, result.chunk.chunk_index, result.chunk.title))
    return scored[:top_k]


def _apply_rrf(
    results: Iterable[RagSearchResult],
    fused_scores: dict[str, float],
    matched_terms: dict[str, set[str]],
    *,
    rrf_k: int,
) -> None:
    for rank, result in enumerate(results, start=1):
        chunk_id = result.chunk.chunk_id
        fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + (1.0 / (rrf_k + rank))
        matched_terms.setdefault(chunk_id, set()).update(result.matched_terms)
