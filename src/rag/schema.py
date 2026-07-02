from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RagDocument:
    source_path: str
    title: str
    text: str
    content_hash: str
    file_type: str
    document_id: str = ""
    revision_id: str = ""
    parser_version: str = "loader_v1"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RagChunk:
    chunk_id: str
    document_hash: str
    source_path: str
    title: str
    text: str
    chunk_index: int
    start_line: int
    end_line: int
    document_id: str = ""
    revision_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RagSearchResult:
    chunk: RagChunk
    score: float
    matched_terms: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk": self.chunk.to_dict(),
            "score": self.score,
            "matched_terms": list(self.matched_terms),
        }


@dataclass(frozen=True)
class RagIndex:
    version: int
    documents: tuple[RagDocument, ...]
    chunks: tuple[RagChunk, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "documents": [doc.to_dict() for doc in self.documents],
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }
