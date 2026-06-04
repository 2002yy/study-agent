"""Local RAG utilities for Study Agent."""

from src.rag.index import (
    build_rag_index,
    load_rag_index,
    save_rag_index,
    search_rag_index,
)
from src.rag.service import (
    build_rag_context,
    format_rag_sources,
    index_documents,
    query_documents,
)
from src.rag.vector import (
    cosine_similarity,
    embed_text,
    search_rag_index_hybrid,
    search_rag_index_vector,
)

__all__ = [
    "build_rag_context",
    "build_rag_index",
    "cosine_similarity",
    "embed_text",
    "format_rag_sources",
    "index_documents",
    "load_rag_index",
    "query_documents",
    "save_rag_index",
    "search_rag_index_hybrid",
    "search_rag_index",
    "search_rag_index_vector",
]
