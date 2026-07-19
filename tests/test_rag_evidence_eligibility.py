from __future__ import annotations

import json
from pathlib import Path

from src.rag.index import build_rag_index, load_rag_index, save_rag_index
from src.rag.schema import RagChunk, RagDocument, RagIndex, RagSearchResult
from src.rag.service import (
    append_documents_to_index,
    index_documents,
    search_documents,
    search_documents_with_debug,
    set_knowledge_document_evidence_status,
)


class _BackendStatus:
    def to_dict(self):
        return {"name": "capture", "available": True, "detail": "test"}


class _CapturingBackend:
    def __init__(self) -> None:
        self.synced_indexes: list[RagIndex] = []

    def upsert_index(self, index: RagIndex) -> None:
        self.synced_indexes.append(index)

    def status(self):
        return _BackendStatus()

    def query(self, index: RagIndex, query: str, *, top_k: int = 5, min_score: float = 0.01):
        _ = query, top_k, min_score
        return [
            RagSearchResult(chunk=chunk, score=0.9, matched_terms=())
            for chunk in index.chunks
        ]


def test_old_indexes_default_evidence_status_to_active(tmp_path):
    path = tmp_path / "legacy-index.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "documents": [
                    {
                        "source_path": "notes.md",
                        "title": "notes",
                        "text": "active by compatibility",
                        "content_hash": "hash",
                        "file_type": "md",
                    }
                ],
                "chunks": [
                    {
                        "chunk_id": "chunk",
                        "document_hash": "hash",
                        "source_path": "notes.md",
                        "title": "notes",
                        "text": "active by compatibility",
                        "chunk_index": 0,
                        "start_line": 1,
                        "end_line": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    index = load_rag_index(path)

    assert index.documents[0].evidence_status == "active"
    assert index.chunks[0].evidence_status == "active"
    assert search_documents(index, "compatibility", top_k=1)[0].chunk.chunk_id == "chunk"


def test_search_filters_non_active_evidence_before_all_local_retrieval_modes(tmp_path):
    current = tmp_path / "current.md"
    old = tmp_path / "old.md"
    current.write_text("current task chip is automatic by default", encoding="utf-8")
    old.write_text("old permanent task dropdown before every message", encoding="utf-8")
    index = build_rag_index([current, old], max_chars=200, overlap_chars=0)
    old_id = next(document.document_id for document in index.documents if Path(document.source_path).name == "old.md")
    path = tmp_path / "index.json"
    save_rag_index(index, path)
    set_knowledge_document_evidence_status(old_id, "superseded", index_path=path)
    filtered = load_rag_index(path)

    for retrieval_mode in ("lexical", "vector", "hybrid"):
        results = search_documents(
            filtered,
            "task dropdown automatic",
            retrieval_mode=retrieval_mode,
            top_k=5,
        )
        assert results
        assert all(Path(result.chunk.source_path).name != "old.md" for result in results)


def test_backend_results_are_defensively_filtered_when_backend_returns_stale_chunk(monkeypatch):
    active_document = RagDocument(
        source_path="current.md",
        title="current",
        text="current truth",
        content_hash="active-hash",
        file_type="md",
        document_id="active-doc",
    )
    stale_document = RagDocument(
        source_path="old.md",
        title="old",
        text="stale truth",
        content_hash="stale-hash",
        file_type="md",
        document_id="stale-doc",
        evidence_status="superseded",
        superseded_by_document_id="active-doc",
    )
    active_chunk = RagChunk(
        chunk_id="active-chunk",
        document_hash="active-hash",
        source_path="current.md",
        title="current",
        text="current truth",
        chunk_index=0,
        start_line=1,
        end_line=1,
        document_id="active-doc",
    )
    stale_chunk = RagChunk(
        chunk_id="stale-chunk",
        document_hash="stale-hash",
        source_path="old.md",
        title="old",
        text="stale truth",
        chunk_index=0,
        start_line=1,
        end_line=1,
        document_id="stale-doc",
        evidence_status="superseded",
        superseded_by_document_id="active-doc",
    )
    index = RagIndex(
        version=1,
        documents=(active_document, stale_document),
        chunks=(active_chunk, stale_chunk),
    )

    class StaleBackend:
        def query(self, _index, _query, *, top_k=5, min_score=0.01):
            _ = top_k, min_score
            return [
                RagSearchResult(chunk=stale_chunk, score=0.99),
                RagSearchResult(chunk=active_chunk, score=0.8),
            ]

    from src.rag import service

    monkeypatch.setattr(service, "get_vector_backend_from_env", lambda: StaleBackend())
    diagnostics = search_documents_with_debug(
        index,
        "truth",
        retrieval_mode="backend_vector",
        top_k=2,
    )

    assert [result.chunk.chunk_id for result in diagnostics.results] == ["active-chunk"]
    assert diagnostics.debug["post_filter"]["ineligible_suppressed"] == 1
    assert diagnostics.debug["evidence_eligibility"]["excluded_documents"] == 1


def test_status_mutation_persists_and_vector_sync_receives_active_view(monkeypatch, tmp_path):
    from src.rag import service

    backend = _CapturingBackend()
    monkeypatch.setattr(service, "get_vector_backend_from_env", lambda: backend)
    current = tmp_path / "current.md"
    old = tmp_path / "old.md"
    current.write_text("current learning truth", encoding="utf-8")
    old.write_text("old learning truth", encoding="utf-8")
    index_path = tmp_path / "rag-index.json"
    index_documents([current, old], index_path=index_path, max_chars=200, overlap_chars=0)
    initial = load_rag_index(index_path)
    current_id = next(document.document_id for document in initial.documents if Path(document.source_path).name == "current.md")
    old_id = next(document.document_id for document in initial.documents if Path(document.source_path).name == "old.md")

    result = set_knowledge_document_evidence_status(
        old_id,
        "superseded",
        superseded_by_document_id=current_id,
        index_path=index_path,
    )
    persisted = load_rag_index(index_path)
    old_document = next(document for document in persisted.documents if document.document_id == old_id)

    assert result["activated"] is True
    assert result["retrievable_documents"] == 1
    assert old_document.evidence_status == "superseded"
    assert old_document.superseded_by_document_id == current_id
    assert all(
        chunk.evidence_status == "superseded"
        for chunk in persisted.chunks
        if chunk.document_id == old_id
    )
    assert backend.synced_indexes[-1].documents[0].document_id == current_id
    assert all(document.document_id != old_id for document in backend.synced_indexes[-1].documents)


def test_reupload_same_source_preserves_evidence_eligibility(monkeypatch, tmp_path):
    from src.rag import service

    backend = _CapturingBackend()
    monkeypatch.setattr(service, "get_vector_backend_from_env", lambda: backend)
    document = tmp_path / "notes.md"
    document.write_text("first revision", encoding="utf-8")
    index_path = tmp_path / "rag-index.json"
    index_documents([document], index_path=index_path, max_chars=200, overlap_chars=0)
    document_id = load_rag_index(index_path).documents[0].document_id
    set_knowledge_document_evidence_status(document_id, "excluded", index_path=index_path)

    document.write_text("second revision", encoding="utf-8")
    append_documents_to_index([document], index_path=index_path, max_chars=200, overlap_chars=0)
    persisted = load_rag_index(index_path)

    assert persisted.documents[0].evidence_status == "excluded"
    assert persisted.documents[0].revision_id != ""
    assert search_documents(persisted, "second revision", top_k=3) == []
    assert backend.synced_indexes[-1].documents == ()
