from __future__ import annotations

import pytest

from src.rag.backends import (
    LocalVectorBackend,
    get_vector_backend,
    get_vector_backend_from_env,
    vector_backend_config_from_env,
)
from src.rag.chroma_backend import ChromaVectorBackend
from src.rag.index import build_rag_index


class _FakeCollection:
    def __init__(self) -> None:
        self.upserts = []
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


def test_local_vector_backend_queries_index(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("Vector backend retrieves local chunks.", encoding="utf-8")
    index = build_rag_index([path], max_chars=200, overlap_chars=0)
    backend = LocalVectorBackend()

    results = backend.query(index, "local chunks", top_k=1, min_score=0.0)

    assert backend.status().available is True
    assert backend.status().embedding_provider == "local_hash"
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
    backend = ChromaVectorBackend(
        path=tmp_path / "chroma",
        collection_name="study_agent_test",
        client=fake_client,
    )

    backend.upsert_index(index)

    assert fake_client.collection_names == ["study_agent_test"]
    upsert = fake_client.collection.upserts[0]
    assert upsert["ids"] == [index.chunks[0].chunk_id]
    assert len(upsert["embeddings"][0]) == 256
    assert upsert["documents"] == [index.chunks[0].text]
    assert upsert["metadatas"][0]["source_path"] == str(path)


def test_chroma_backend_query_reconstructs_search_results(tmp_path):
    fake_client = _FakeClient()
    backend = ChromaVectorBackend(
        path=tmp_path / "chroma",
        collection_name="study_agent_test",
        client=fake_client,
    )
    path = tmp_path / "notes.md"
    path.write_text("Local placeholder.", encoding="utf-8")
    index = build_rag_index([path], max_chars=200, overlap_chars=0)

    results = backend.query(index, "stored chunk", top_k=1, min_score=0.1)

    assert backend.status().available is True
    assert fake_client.collection.last_query["n_results"] == 1
    assert results[0].score == 0.8
    assert results[0].chunk.source_path == "notes.md"
    assert results[0].chunk.start_line == 1
