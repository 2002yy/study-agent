from __future__ import annotations

import pytest

from src.rag.backends import (
    LocalVectorBackend,
    get_vector_backend,
    get_vector_backend_from_env,
    vector_backend_config_from_env,
)
from src.rag.chroma_backend import ChromaVectorBackend
from src.rag.embeddings import (
    LocalHashEmbeddingProvider,
    OpenAIEmbeddingProvider,
    embedding_provider_config_from_env,
    get_embedding_provider,
    get_embedding_provider_from_env,
)
from src.rag.index import build_rag_index


class _RecordingEmbeddingProvider:
    name = "recording"
    dimensions = 3

    def __init__(self) -> None:
        self.embed_inputs = []
        self.embed_many_inputs = []

    def embed(self, text: str) -> tuple[float, ...]:
        self.embed_inputs.append(text)
        return (0.1, 0.2, 0.3)

    def embed_many(self, texts: list[str]) -> list[tuple[float, ...]]:
        self.embed_many_inputs.append(list(texts))
        return [(0.1, 0.2, 0.3) for _text in texts]


class _FakeCollection:
    def __init__(self) -> None:
        self.upserts = []
        self.ids = []
        self.deletes = []
        self.response = {
            "ids": [["chunk-1"]],
            "distances": [[0.2]],
            "documents": [["Stored chunk text"]],
            "metadatas": [
                [
                    {
                        "document_hash": "doc-hash",
                        "source_path": "notes.md",
                        "title": "notes",
                        "chunk_index": 0,
                        "start_line": 1,
                        "end_line": 2,
                        "file_type": "md",
                        "char_count": 17,
                    }
                ]
            ],
        }

    def upsert(self, **kwargs) -> None:
        self.upserts.append(kwargs)
        self.ids = list(dict.fromkeys([*self.ids, *kwargs["ids"]]))

    def get(self, **_kwargs):
        return {"ids": list(self.ids)}

    def delete(self, **kwargs) -> None:
        self.deletes.append(kwargs)
        removed = set(kwargs["ids"])
        self.ids = [item for item in self.ids if item not in removed]

    def query(self, **kwargs):
        self.last_query = kwargs
        return self.response


class _FakeClient:
    def __init__(self) -> None:
        self.collection = _FakeCollection()
        self.collection_names = []

    def get_or_create_collection(self, name: str):
        self.collection_names.append(name)
        return self.collection


class _FakeEmbeddingClient:
    def __init__(self) -> None:
        self.embeddings = self
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)

        class Item:
            embedding = [0.1, 0.2, 0.3]

        class Response:
            pass

        response = Response()
        response.data = [Item() for _text in kwargs["input"]]
        return response



def test_embedding_provider_config_reads_environment(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("RAG_EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("RAG_EMBEDDING_DIMENSIONS", "768")
    monkeypatch.setenv("RAG_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("RAG_EMBEDDING_BASE_URL", "https://example.test/v1")

    config = embedding_provider_config_from_env()

    assert config == {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimensions": "768",
        "base_url_configured": "true",
        "api_key_configured": "true",
        "semantic_capable": "true",
        "intended_use": "production",
    }


def test_get_embedding_provider_from_env_defaults_to_local(monkeypatch):
    monkeypatch.delenv("RAG_EMBEDDING_PROVIDER", raising=False)

    provider = get_embedding_provider_from_env()

    assert isinstance(provider, LocalHashEmbeddingProvider)


def test_get_embedding_provider_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        get_embedding_provider("unknown")


def test_openai_embedding_provider_batches_requests():
    fake_client = _FakeEmbeddingClient()
    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        dimensions=3,
        client=fake_client,
    )

    vectors = provider.embed_many(["first", "second"])

    assert vectors == [(0.1, 0.2, 0.3), (0.1, 0.2, 0.3)]
    assert fake_client.requests == [
        {
            "model": "text-embedding-3-small",
            "input": ["first", "second"],
            "dimensions": 3,
        }
    ]


def test_local_vector_backend_queries_index(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("Vector backend retrieves local chunks.", encoding="utf-8")
    index = build_rag_index([path], max_chars=200, overlap_chars=0)
    backend = LocalVectorBackend()

    results = backend.query(index, "local chunks", top_k=1, min_score=0.0)

    assert backend.status().available is True
    assert backend.status().embedding_provider == "local_hash"
    assert backend.status().embedding_semantic is False
    assert backend.status().embedding_intended_use == "test_fallback"
    assert results
    assert results[0].chunk.source_path == str(path)


def test_get_vector_backend_rejects_unknown_backend():
    with pytest.raises(ValueError, match="Unsupported vector backend"):
        get_vector_backend("pinecone")


def test_vector_backend_config_reads_environment(monkeypatch):
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "chroma")
    monkeypatch.setenv("RAG_CHROMA_PATH", "logs/test_chroma")
    monkeypatch.setenv("RAG_CHROMA_COLLECTION", "study_agent_test")

    config = vector_backend_config_from_env()

    assert config == {
        "name": "chroma",
        "path": "logs/test_chroma",
        "collection": "study_agent_test",
    }


def test_get_vector_backend_from_env_defaults_to_local(monkeypatch):
    monkeypatch.delenv("RAG_VECTOR_BACKEND", raising=False)

    backend = get_vector_backend_from_env()

    assert isinstance(backend, LocalVectorBackend)


def test_chroma_backend_upserts_chunks_with_embeddings(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("Chroma adapter stores local chunks.", encoding="utf-8")
    index = build_rag_index([path], max_chars=200, overlap_chars=0)
    fake_client = _FakeClient()
    embedding_provider = _RecordingEmbeddingProvider()
    backend = ChromaVectorBackend(
        path=tmp_path / "chroma",
        collection_name="study_agent_test",
        client=fake_client,
        embedding_provider=embedding_provider,
    )

    backend.upsert_index(index)

    assert fake_client.collection_names == ["study_agent_test"]
    upsert = fake_client.collection.upserts[0]
    assert upsert["ids"] == [index.chunks[0].chunk_id]
    assert upsert["embeddings"][0] == [0.1, 0.2, 0.3]
    assert upsert["documents"] == [index.chunks[0].text]
    assert upsert["metadatas"][0]["source_path"] == str(path)
    assert embedding_provider.embed_many_inputs == [[index.chunks[0].text]]


def test_chroma_backend_removes_chunks_missing_from_replacement_index(tmp_path):
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("first stale knowledge", encoding="utf-8")
    second.write_text("second active knowledge", encoding="utf-8")
    first_index = build_rag_index([first], max_chars=200, overlap_chars=0)
    second_index = build_rag_index([second], max_chars=200, overlap_chars=0)
    fake_client = _FakeClient()
    backend = ChromaVectorBackend(
        path=tmp_path / "chroma",
        collection_name="study_agent_test",
        client=fake_client,
        embedding_provider=_RecordingEmbeddingProvider(),
    )

    backend.upsert_index(first_index)
    backend.upsert_index(second_index)

    assert fake_client.collection.deletes == [
        {"ids": [first_index.chunks[0].chunk_id]}
    ]
    assert fake_client.collection.ids == [second_index.chunks[0].chunk_id]


def test_chroma_backend_query_reconstructs_search_results(tmp_path):
    fake_client = _FakeClient()
    embedding_provider = _RecordingEmbeddingProvider()
    backend = ChromaVectorBackend(
        path=tmp_path / "chroma",
        collection_name="study_agent_test",
        client=fake_client,
        embedding_provider=embedding_provider,
    )
    path = tmp_path / "notes.md"
    path.write_text("Local placeholder.", encoding="utf-8")
    index = build_rag_index([path], max_chars=200, overlap_chars=0)

    results = backend.query(index, "stored chunk", top_k=1, min_score=0.1)

    assert backend.status().available is True
    assert fake_client.collection.last_query["n_results"] == 1
    assert fake_client.collection.last_query["query_embeddings"] == [[0.1, 0.2, 0.3]]
    assert embedding_provider.embed_inputs == ["stored chunk"]
    assert results[0].score == 0.8
    assert results[0].chunk.source_path == "notes.md"
    assert results[0].chunk.start_line == 1
