from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from src.rag.index import (
    DEFAULT_RAG_INDEX_PATH,
    build_rag_index,
    load_rag_index,
    save_rag_index,
    search_rag_index,
)
from src.rag.schema import RagIndex, RagSearchResult
from src.rag.vector import search_rag_index_hybrid, search_rag_index_vector


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
    if retrieval_mode == "lexical":
        return search_rag_index(index, query, top_k=top_k, min_score=min_score)
    if retrieval_mode == "vector":
        return search_rag_index_vector(index, query, top_k=top_k, min_score=min_score)
    if retrieval_mode == "hybrid":
        return search_rag_index_hybrid(index, query, top_k=top_k, min_score=min_score)
    raise ValueError(f"Unsupported RAG retrieval mode: {retrieval_mode}")


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
