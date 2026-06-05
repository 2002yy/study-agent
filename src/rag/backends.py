from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.rag.embeddings import EmbeddingProvider, LocalHashEmbeddingProvider
from src.rag.schema import RagIndex, RagSearchResult
from src.rag.vector import search_rag_index_vector


@dataclass(frozen=True)
class VectorBackendStatus:
    name: str
    available: bool
    detail: str
    path: str = ""
    collection: str = ""
    embedding_provider: str = ""

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "name": self.name,
            "available": self.available,
            "detail": self.detail,
            "path": self.path,
            "collection": self.collection,
            "embedding_provider": self.embedding_provider,
        }


class VectorBackend(Protocol):
    name: str

    def status(self) -> VectorBackendStatus:
        """Return backend availability and configuration details."""

    def upsert_index(self, index: RagIndex) -> None:
        """Persist or refresh index chunks in the backend."""

    def query(
        self,
        index: RagIndex,
        query: str,
        *,
        top_k: int = 5,
        min_score: float = 0.05,
    ) -> list[RagSearchResult]:
        """Return vector search results."""


class LocalVectorBackend:
    name = "local"

    def __init__(self, embedding_provider: EmbeddingProvider | None = None) -> None:
        self.embedding_provider = embedding_provider or LocalHashEmbeddingProvider()

    def status(self) -> VectorBackendStatus:
        return VectorBackendStatus(
            name=self.name,
            available=True,
            detail="In-memory deterministic local vector prototype",
            embedding_provider=self.embedding_provider.name,
        )

    def upsert_index(self, index: RagIndex) -> None:
        _ = index

    def query(
        self,
        index: RagIndex,
        query: str,
        *,
        top_k: int = 5,
        min_score: float = 0.05,
    ) -> list[RagSearchResult]:
        return search_rag_index_vector(index, query, top_k=top_k, min_score=min_score)


def vector_backend_config_from_env() -> dict[str, str]:
    return {
        "name": os.getenv("RAG_VECTOR_BACKEND", "local").strip() or "local",
        "path": os.getenv("RAG_CHROMA_PATH", "logs/chroma").strip() or "logs/chroma",
        "collection": os.getenv("RAG_CHROMA_COLLECTION", "study_agent").strip() or "study_agent",
    }


def get_vector_backend(
    name: str = "local",
    *,
    path: str | Path = "logs/chroma",
    collection: str = "study_agent",
    embedding_provider: EmbeddingProvider | None = None,
) -> VectorBackend:
    normalized = (name or "local").strip().lower()
    if normalized == "local":
        return LocalVectorBackend(embedding_provider=embedding_provider)
    if normalized == "chroma":
        from src.rag.chroma_backend import ChromaVectorBackend

        return ChromaVectorBackend(
            path=path,
            collection_name=collection,
            embedding_provider=embedding_provider,
        )
    raise ValueError(f"Unsupported vector backend: {name}")


def get_vector_backend_from_env(
    *,
    embedding_provider: EmbeddingProvider | None = None,
) -> VectorBackend:
    config = vector_backend_config_from_env()
    return get_vector_backend(
        config["name"],
        path=config["path"],
        collection=config["collection"],
        embedding_provider=embedding_provider,
    )
