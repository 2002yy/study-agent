from __future__ import annotations

from pathlib import Path
from typing import Any

from src.rag.backends import VectorBackendStatus
from src.rag.embeddings import EmbeddingProvider, LocalHashEmbeddingProvider
from src.rag.schema import RagChunk, RagIndex, RagSearchResult


class ChromaVectorBackend:
    name = "chroma"

    def __init__(
        self,
        *,
        path: str | Path = "logs/chroma",
        collection_name: str = "study_agent",
        embedding_provider: EmbeddingProvider | None = None,
        client: Any | None = None,
    ) -> None:
        self.path = Path(path)
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider or LocalHashEmbeddingProvider()
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import chromadb  # type: ignore[import-not-found]
        except Exception as exc:
            raise RuntimeError("chromadb is required for the Chroma vector backend") from exc
        self._client = chromadb.PersistentClient(path=str(self.path))
        return self._client

    def _collection(self) -> Any:
        return self._get_client().get_or_create_collection(name=self.collection_name)

    def status(self) -> VectorBackendStatus:
        try:
            self._get_client()
        except RuntimeError as exc:
            return VectorBackendStatus(
                name=self.name,
                available=False,
                detail=str(exc),
                path=str(self.path),
                collection=self.collection_name,
                embedding_provider=self.embedding_provider.name,
            )
        return VectorBackendStatus(
            name=self.name,
            available=True,
            detail="Chroma persistent vector backend",
            path=str(self.path),
            collection=self.collection_name,
            embedding_provider=self.embedding_provider.name,
        )

    def upsert_index(self, index: RagIndex) -> None:
        collection = self._collection()
        ids = [chunk.chunk_id for chunk in index.chunks]
        if not ids:
            return

        collection.upsert(
            ids=ids,
            embeddings=[list(self.embedding_provider.embed(chunk.text)) for chunk in index.chunks],
            documents=[chunk.text for chunk in index.chunks],
            metadatas=[_chunk_metadata(chunk) for chunk in index.chunks],
        )

    def query(
        self,
        index: RagIndex,
        query: str,
        *,
        top_k: int = 5,
        min_score: float = 0.05,
    ) -> list[RagSearchResult]:
        _ = index
        if top_k <= 0:
            return []
        response = self._collection().query(
            query_embeddings=[list(self.embedding_provider.embed(query))],
            n_results=top_k,
        )
        ids = _first(response.get("ids", []))
        distances = _first(response.get("distances", []))
        documents = _first(response.get("documents", []))
        metadatas = _first(response.get("metadatas", []))

        results: list[RagSearchResult] = []
        for item_id, distance, text, metadata in zip(
            ids,
            distances,
            documents,
            metadatas,
            strict=False,
        ):
            score = max(0.0, 1.0 - float(distance))
            if score < min_score:
                continue
            chunk = _chunk_from_metadata(str(item_id), str(text), dict(metadata or {}))
            results.append(RagSearchResult(chunk=chunk, score=round(score, 6), matched_terms=()))
        return results


def _first(value: list) -> list:
    if not value:
        return []
    first = value[0]
    return first if isinstance(first, list) else value


def _chunk_metadata(chunk: RagChunk) -> dict[str, str | int]:
    return {
        "document_hash": chunk.document_hash,
        "source_path": chunk.source_path,
        "title": chunk.title,
        "chunk_index": chunk.chunk_index,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "file_type": str(chunk.metadata.get("file_type", "")),
        "char_count": int(chunk.metadata.get("char_count", len(chunk.text))),
    }


def _chunk_from_metadata(chunk_id: str, text: str, metadata: dict) -> RagChunk:
    return RagChunk(
        chunk_id=chunk_id,
        document_hash=str(metadata.get("document_hash", "")),
        source_path=str(metadata.get("source_path", "")),
        title=str(metadata.get("title", "")),
        text=text,
        chunk_index=int(metadata.get("chunk_index", 0)),
        start_line=int(metadata.get("start_line", 1)),
        end_line=int(metadata.get("end_line", 1)),
        metadata={
            "file_type": metadata.get("file_type", ""),
            "char_count": int(metadata.get("char_count", len(text))),
        },
    )
