from __future__ import annotations

from fastapi.testclient import TestClient

from src.api import app


def test_health_endpoint_reports_ok():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "study-agent"
    assert isinstance(data["rag_index_exists"], bool)


def test_rag_index_and_query_endpoints(tmp_path):
    client = TestClient(app)
    document = tmp_path / "notes.md"
    index_path = tmp_path / "rag_index.json"
    document.write_text("FastAPI RAG query returns cited local chunks.", encoding="utf-8")

    index_response = client.post(
        "/rag/index",
        json={
            "paths": [str(document)],
            "index_path": str(index_path),
            "max_chars": 200,
            "overlap_chars": 0,
        },
    )
    query_response = client.post(
        "/rag/query",
        json={
            "query": "FastAPI cited chunks",
            "index_path": str(index_path),
            "retrieval_mode": "hybrid",
            "top_k": 1,
        },
    )

    assert index_response.status_code == 200
    assert index_response.json()["documents"] == 1
    assert query_response.status_code == 200
    query_data = query_response.json()
    assert query_data["result_count"] == 1
    assert "[1] notes" in query_data["context"]
    assert query_data["results"][0]["chunk"]["source_path"] == str(document)
    assert query_data["debug"]["retrieval_mode"] == "hybrid"
    assert query_data["debug"]["candidate_count"] == 1
    assert query_data["debug"]["results"][0]["score_breakdown"]["combined_score"] > 0


def test_rag_alias_queries_existing_index(tmp_path):
    client = TestClient(app)
    document = tmp_path / "notes.md"
    index_path = tmp_path / "rag_index.json"
    document.write_text("Alias route keeps the /rag endpoint usable.", encoding="utf-8")
    client.post("/rag/index", json={"paths": [str(document)], "index_path": str(index_path)})

    response = client.post(
        "/rag",
        json={"query": "alias route", "index_path": str(index_path), "retrieval_mode": "lexical"},
    )

    assert response.status_code == 200
    assert response.json()["result_count"] == 1


def test_rag_query_endpoint_rejects_unknown_mode(tmp_path):
    client = TestClient(app)
    document = tmp_path / "notes.md"
    index_path = tmp_path / "rag_index.json"
    document.write_text("Local retrieval.", encoding="utf-8")
    client.post("/rag/index", json={"paths": [str(document)], "index_path": str(index_path)})

    response = client.post(
        "/rag/query",
        json={"query": "retrieval", "index_path": str(index_path), "retrieval_mode": "semantic"},
    )

    assert response.status_code == 400
    assert "Unsupported RAG retrieval mode" in response.json()["detail"]


def test_rag_query_endpoint_returns_optional_evaluation(tmp_path):
    client = TestClient(app)
    document = tmp_path / "notes.md"
    index_path = tmp_path / "rag_index.json"
    document.write_text("Evaluation expects this cited local source.", encoding="utf-8")
    client.post("/rag/index", json={"paths": [str(document)], "index_path": str(index_path)})

    response = client.post(
        "/rag/query",
        json={
            "query": "cited local source",
            "index_path": str(index_path),
            "retrieval_mode": "hybrid",
            "expected_sources": [document.name],
            "expected_terms": ["cited", "source"],
            "top_k": 2,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["evaluation"]["hit"] is True
    assert data["evaluation"]["recall_at_k"] == 1.0
    assert data["debug"]["returned_count"] >= 1


def test_rag_index_endpoint_reports_missing_files(tmp_path):
    client = TestClient(app)

    response = client.post("/rag/index", json={"paths": [str(tmp_path / "missing.md")]})

    assert response.status_code == 404
