"""Local RAG utilities for Study Agent."""

from src.rag.index import (
    build_rag_index,
    load_rag_index,
    save_rag_index,
    search_rag_index,
)
from src.rag.backends import (
    LocalVectorBackend,
    VectorBackendStatus,
    get_vector_backend,
    get_vector_backend_from_env,
    vector_backend_config_from_env,
)
from src.rag.embeddings import (
    LocalHashEmbeddingProvider,
    OpenAIEmbeddingProvider,
    embedding_provider_config_from_env,
    get_embedding_provider,
    get_embedding_provider_from_env,
)
from src.rag.eval import (
    RagEvalCase,
    RagEvalResult,
    RagEvalSummary,
    evaluate_case,
    evaluate_rag_index,
    load_eval_cases,
)
from src.rag.service import (
    build_rag_debug,
    build_rag_context,
    format_rag_sources,
    index_documents,
    query_documents,
    search_documents,
)
from src.rag.vector import (
    cosine_similarity,
    embed_text,
    search_rag_index_hybrid,
    search_rag_index_vector,
)

__all__ = [
    "build_rag_debug",
    "build_rag_context",
    "build_rag_index",
    "cosine_similarity",
    "embed_text",
    "evaluate_case",
    "evaluate_rag_index",
    "format_rag_sources",
    "index_documents",
    "get_vector_backend",
    "get_vector_backend_from_env",
    "LocalHashEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "embedding_provider_config_from_env",
    "get_embedding_provider",
    "get_embedding_provider_from_env",
    "LocalVectorBackend",
    "load_eval_cases",
    "load_rag_index",
    "query_documents",
    "RagEvalCase",
    "RagEvalResult",
    "RagEvalSummary",
    "save_rag_index",
    "search_rag_index_hybrid",
    "search_rag_index",
    "search_rag_index_vector",
    "search_documents",
    "VectorBackendStatus",
    "vector_backend_config_from_env",
]
