from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.api import app


def test_knowledge_document_evidence_status_controls_retrieval(tmp_path):
    client = TestClient(app)
    current = tmp_path / "current.md"
    old = tmp_path / "old.md"
    index_path = tmp_path / "rag-index.json"
    current.write_text("Current composer uses an on-demand task chip.", encoding="utf-8")
    old.write_text("Legacy composer requires a permanent task dropdown.", encoding="utf-8")

    indexed = client.post(
        "/rag/index",
        json={
            "paths": [str(current), str(old)],
            "index_path": str(index_path),
            "max_chars": 200,
            "overlap_chars": 0,
        },
    )
    assert indexed.status_code == 200

    listed = client.get(
        "/knowledge-base/documents",
        params={"index_path": str(index_path)},
    )
    assert listed.status_code == 200
    documents = listed.json()["documents"]
    current_document = next(item for item in documents if Path(item["source_path"]).name == "current.md")
    old_document = next(item for item in documents if Path(item["source_path"]).name == "old.md")
    assert old_document["evidence_status"] == "active"

    patched = client.patch(
        f"/knowledge-base/documents/{old_document['document_id']}/evidence-status",
        params={"index_path": str(index_path)},
        json={
            "evidence_status": "superseded",
            "superseded_by_document_id": current_document["document_id"],
        },
    )
    assert patched.status_code == 200
    assert patched.json()["evidence_status"] == "superseded"
    assert patched.json()["retrievable_documents"] == 1

    queried = client.post(
        "/rag/query",
        json={
            "query": "task dropdown composer",
            "index_path": str(index_path),
            "retrieval_mode": "hybrid",
            "top_k": 5,
        },
    )
    assert queried.status_code == 200
    assert queried.json()["results"]
    assert all(
        Path(result["chunk"]["source_path"]).name != "old.md"
        for result in queried.json()["results"]
    )
    assert queried.json()["debug"]["evidence_eligibility"]["excluded_documents"] == 1

    relisted = client.get(
        "/knowledge-base/documents",
        params={"index_path": str(index_path)},
    ).json()
    old_after = next(item for item in relisted["documents"] if item["document_id"] == old_document["document_id"])
    assert old_after["evidence_status"] == "superseded"
    assert old_after["superseded_by_document_id"] == current_document["document_id"]
    assert relisted["retrievable_documents"] == 1


def test_knowledge_document_evidence_status_rejects_invalid_replacement(tmp_path):
    client = TestClient(app)
    document = tmp_path / "notes.md"
    index_path = tmp_path / "rag-index.json"
    document.write_text("Only one current document.", encoding="utf-8")
    client.post(
        "/rag/index",
        json={"paths": [str(document)], "index_path": str(index_path)},
    )
    listed = client.get(
        "/knowledge-base/documents",
        params={"index_path": str(index_path)},
    ).json()
    document_id = listed["documents"][0]["document_id"]

    response = client.patch(
        f"/knowledge-base/documents/{document_id}/evidence-status",
        params={"index_path": str(index_path)},
        json={
            "evidence_status": "superseded",
            "superseded_by_document_id": document_id,
        },
    )

    assert response.status_code == 400
    assert "cannot supersede itself" in response.json()["detail"]
