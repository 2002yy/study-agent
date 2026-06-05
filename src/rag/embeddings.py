from __future__ import annotations

from typing import Protocol

from src.rag.vector import VECTOR_DIMENSIONS, embed_text


class EmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def embed(self, text: str) -> tuple[float, ...]:
        """Embed one text string for vector retrieval."""


class LocalHashEmbeddingProvider:
    name = "local_hash"
    dimensions = VECTOR_DIMENSIONS

    def embed(self, text: str) -> tuple[float, ...]:
        return embed_text(text, dimensions=self.dimensions)
