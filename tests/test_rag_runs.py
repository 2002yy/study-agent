from __future__ import annotations

from fastapi.testclient import TestClient

from src.api import app
from src.application.rag_run_service import RagRunService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.rag_repository import RagRepository


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
