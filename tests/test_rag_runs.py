from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.application.rag_run_service import RagRunService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.rag_repository import RagRepository
from src.rag.backends import VectorBackendStatus
from src.rag.index import load_rag_index


class _FailingVectorBackend:
    name = "failing"

    def status(self):
        return VectorBackendStatus(
            name=self.name,
            available=False,
            detail="simulated dense index failure",
        )

    def upsert_index(self, _index):
        raise RuntimeError("simulated dense index failure")


def test_query_upload_and_rebuild_have_independent_durable_runs(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    service = RagRunService(RagRepository(database))
    index_path = tmp_path / "rag.json"
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("# First\nDurable retrieval alpha.", encoding="utf-8")
    second.write_text("# Second\nDurable retrieval beta.", encoding="utf-8")

    upload = service.index(
        [first], mode="upload", index_path=index_path,
        max_chars=200, overlap_chars=0,
    )
    query = service.query(
        {
            "query": "retrieval alpha",
            "top_k": 3,
            "min_score": 0.01,
            "retrieval_mode": "hybrid",
            "context_max_chars": 1000,
            "expected_sources": [],
            "expected_terms": [],
        },
        index_path=index_path,
    )
    rebuild = service.index(
        [second], mode="rebuild", index_path=index_path,
        max_chars=200, overlap_chars=0,
    )

    restored = RagRepository(database)
    assert restored.get(upload.id).kind == "upload"  # type: ignore[union-attr]
    assert restored.get(query.id).result["result_count"] == 1  # type: ignore[union-attr]
    assert restored.get(rebuild.id).kind == "rebuild"  # type: ignore[union-attr]
    assert upload.index_version < rebuild.index_version


def test_knowledge_base_document_list_delete_and_index_version(tmp_path):
    service = RagRunService(
        RagRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    )
    index_path = tmp_path / "rag.json"
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("first knowledge", encoding="utf-8")
    second.write_text("second knowledge", encoding="utf-8")
    service.index(
        [first, second], mode="rebuild", index_path=index_path,
        max_chars=200, overlap_chars=0,
    )

    before = service.documents(index_path=index_path)
    document_id = before["documents"][0]["document_id"]
    deleted = service.delete_document(document_id, index_path=index_path)
    after = service.documents(index_path=index_path)

    assert len(before["documents"]) == 2
    assert deleted["index_version"] == before["index_version"] + 1
    assert len(after["documents"]) == 1
    assert all(doc["document_id"] != document_id for doc in after["documents"])


def test_reupload_same_source_replaces_revision_without_duplicate_document(
    tmp_path,
):
    service = RagRunService(
        RagRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    )
    index_path = tmp_path / "rag.json"
    document = tmp_path / "notes.md"
    document.write_text("revision one", encoding="utf-8")
    service.index(
        [document],
        mode="upload",
        index_path=index_path,
        max_chars=200,
        overlap_chars=0,
    )
    before = service.documents(index_path=index_path)["documents"][0]

    document.write_text("revision two with corrected content", encoding="utf-8")
    service.index(
        [document],
        mode="upload",
        index_path=index_path,
        max_chars=200,
        overlap_chars=0,
    )
    documents = service.documents(index_path=index_path)["documents"]

    assert len(documents) == 1
    assert documents[0]["document_id"] == before["document_id"]
    assert documents[0]["revision_id"] != before["revision_id"]
    assert documents[0]["content_hash"] != before["content_hash"]


def test_required_vector_failure_does_not_activate_candidate(
    tmp_path, monkeypatch
):
    repository = RagRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    service = RagRunService(repository)
    index_path = tmp_path / "rag.json"
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("stable active knowledge", encoding="utf-8")
    second.write_text("candidate must not activate", encoding="utf-8")
    initial = service.index(
        [first],
        mode="rebuild",
        index_path=index_path,
        max_chars=200,
        overlap_chars=0,
    )
    monkeypatch.setattr(
        "src.rag.service.get_vector_backend_from_env",
        lambda: _FailingVectorBackend(),
    )

    candidate = service.index(
        [second],
        mode="rebuild",
        index_path=index_path,
        max_chars=200,
        overlap_chars=0,
    )

    active = load_rag_index(index_path)
    state = repository.get_index_state(str(index_path.resolve()))
    assert candidate.status == "partial_success"
    assert candidate.index_version == initial.index_version
    assert candidate.result["activated"] is False
    assert active.version == initial.index_version
    assert active.documents[0].source_path == str(first)
    assert state is not None
    assert state["active_version"] == initial.index_version
    assert state["staging_version"] is None
    assert state["status"] == "failed"


def test_vector_failure_does_not_claim_document_deletion(tmp_path, monkeypatch):
    repository = RagRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    service = RagRunService(repository)
    index_path = tmp_path / "rag.json"
    document = tmp_path / "document.md"
    document.write_text("knowledge must remain active", encoding="utf-8")
    service.index(
        [document],
        mode="rebuild",
        index_path=index_path,
        max_chars=200,
        overlap_chars=0,
    )
    document_id = service.documents(index_path=index_path)["documents"][0][
        "document_id"
    ]
    monkeypatch.setattr(
        "src.rag.service.get_vector_backend_from_env",
        lambda: _FailingVectorBackend(),
    )

    with pytest.raises(RuntimeError, match="deletion was not activated"):
        service.delete_document(document_id, index_path=index_path)

    active = service.documents(index_path=index_path)
    assert active["documents"][0]["document_id"] == document_id


def test_index_write_lease_uses_expected_version_cas(tmp_path):
    repository = RagRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    index_path = str((tmp_path / "rag.json").resolve())
    barrier = Barrier(2)

    def begin():
        barrier.wait(timeout=5)
        try:
            state = repository.begin_index_write(index_path, expected_version=0)
            return int(state["staging_version"])
        except ValueError:
            return 0

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _item: begin(), range(2)))

    assert sorted(results) == [0, 1]


def test_rag_run_api_restores_run_and_exposes_documents(
    runtime_test_context, tmp_path
):
    index_path = tmp_path / "rag.json"
    document = tmp_path / "doc.md"
    document.write_text("API durable knowledge", encoding="utf-8")
    runtime_test_context.rag_run_service.index(
        [document], mode="rebuild", index_path=index_path,
        max_chars=200, overlap_chars=0,
    )
    client = TestClient(app)

    created = client.post(
        "/rag-runs/query",
        json={
            "query": "durable knowledge",
            "index_path": str(index_path),
            "top_k": 2,
            "retrieval_mode": "hybrid",
        },
    )
    assert created.status_code == 200
    run_id = created.json()["id"]

    restored = client.get(f"/rag-runs/{run_id}")
    documents = client.get(
        "/knowledge-base/documents",
        params={"index_path": str(index_path)},
    )

    assert restored.status_code == 200
    assert restored.json()["kind"] == "query"
    assert documents.status_code == 200
    assert documents.json()["index_version"] >= 1
    assert documents.json()["documents"][0]["title"]
