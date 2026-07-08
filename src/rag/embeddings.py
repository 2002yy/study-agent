from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from src.rag.vector import VECTOR_DIMENSIONS, embed_text


@dataclass(frozen=True)
class EmbeddingProfile:
    name: str
    provider: str
    model: str
    dimensions: int | None
    semantic_capable: bool
    intended_use: str
    language_coverage: str

    def to_config(self) -> dict[str, str]:
        return {
            "profile": self.name,
            "provider": self.provider,
            "model": self.model,
            "dimensions": str(self.dimensions or ""),
            "semantic_capable": "true" if self.semantic_capable else "false",
            "intended_use": self.intended_use,
            "language_coverage": self.language_coverage,
        }


class EmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def embed(self, text: str) -> tuple[float, ...]:
        """Embed one text string for vector retrieval."""

    def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        """Embed a batch of text strings in input order."""


class LocalHashEmbeddingProvider:
    name = "local_hash"
    dimensions = VECTOR_DIMENSIONS

    def embed(self, text: str) -> tuple[float, ...]:
        return embed_text(text, dimensions=self.dimensions)

    def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [self.embed(text) for text in texts]


class OpenAIEmbeddingProvider:
    name = "openai"

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        dimensions: int | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.name = f"openai:{model}"
        self.dimensions = dimensions or 1536
        self._dimensions_override = dimensions
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        api_key = self._api_key or os.getenv("RAG_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("RAG_EMBEDDING_API_KEY or OPENAI_API_KEY is required for OpenAI embeddings")

        try:
            from openai import OpenAI
        except Exception as exc:
            raise RuntimeError("openai is required for OpenAI embeddings") from exc

        kwargs: dict[str, Any] = {"api_key": api_key}
        base_url = self._base_url or os.getenv("RAG_EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        if self._timeout is not None:
            kwargs["timeout"] = self._timeout
        self._client = OpenAI(**kwargs)
        return self._client

    def embed(self, text: str) -> tuple[float, ...]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []

        request: dict[str, Any] = {"model": self.model, "input": texts}
        if self._dimensions_override is not None:
            request["dimensions"] = self._dimensions_override

        response = self._get_client().embeddings.create(**request)
        return [tuple(float(value) for value in item.embedding) for item in response.data]


def _env_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _env_float(name: str) -> float | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def embedding_provider_config_from_env() -> dict[str, str]:
    profile = embedding_profile_from_env()
    return {
        **profile.to_config(),
        "base_url_configured": "true"
        if (os.getenv("RAG_EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL"))
        else "false",
        "api_key_configured": "true"
        if (os.getenv("RAG_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY"))
        else "false",
    }


def embedding_profile_from_env() -> EmbeddingProfile:
    profile_name = os.getenv("RAG_EMBEDDING_PROFILE", "").strip().lower()
    provider_override = os.getenv("RAG_EMBEDDING_PROVIDER", "").strip()
    model_override = os.getenv("RAG_EMBEDDING_MODEL", "").strip()
    dimensions_override = _env_int("RAG_EMBEDDING_DIMENSIONS")

    if profile_name in {"", "local", "local_hash", "dev"} and not provider_override:
        return EmbeddingProfile(
            name=profile_name or "local_hash",
            provider="local_hash",
            model="local_hash",
            dimensions=VECTOR_DIMENSIONS,
            semantic_capable=False,
            intended_use="test_fallback",
            language_coverage="token_hash",
        )

    if profile_name in {"openai_multilingual", "production_multilingual", "multilingual"}:
        return EmbeddingProfile(
            name=profile_name,
            provider=provider_override or "openai",
            model=model_override or "text-embedding-3-small",
            dimensions=dimensions_override or 1536,
            semantic_capable=True,
            intended_use="production",
            language_coverage="multilingual",
        )

    provider = provider_override or profile_name or "local_hash"
    normalized_provider = provider.lower()
    is_local_hash = normalized_provider in {"local", "local_hash", "hash"}
    return EmbeddingProfile(
        name=profile_name or normalized_provider,
        provider=provider,
        model=model_override or ("local_hash" if is_local_hash else "text-embedding-3-small"),
        dimensions=dimensions_override or (VECTOR_DIMENSIONS if is_local_hash else 1536),
        semantic_capable=not is_local_hash,
        intended_use="test_fallback" if is_local_hash else "production",
        language_coverage="token_hash" if is_local_hash else "provider_default",
    )


def get_embedding_provider(
    name: str = "local_hash",
    *,
    model: str = "text-embedding-3-small",
    dimensions: int | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    client: Any | None = None,
) -> EmbeddingProvider:
    normalized = (name or "local_hash").strip().lower()
    if normalized in {"local", "local_hash", "hash"}:
        return LocalHashEmbeddingProvider()
    if normalized in {"openai", "openai_compatible"}:
        return OpenAIEmbeddingProvider(
            model=model,
            dimensions=dimensions,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            client=client,
        )
    raise ValueError(f"Unsupported embedding provider: {name}")


def get_embedding_provider_from_env() -> EmbeddingProvider:
    profile = embedding_profile_from_env()
    return get_embedding_provider(
        profile.provider,
        model=profile.model,
        dimensions=profile.dimensions if profile.semantic_capable else None,
        base_url=os.getenv("RAG_EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
        timeout=_env_float("RAG_EMBEDDING_TIMEOUT_SECONDS"),
    )
