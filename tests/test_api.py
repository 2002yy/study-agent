from __future__ import annotations

from fastapi.testclient import TestClient

from src.mode_manager import RuntimeModes
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


def test_local_knowledge_endpoint_applies_agentic_retrieval(tmp_path):
    client = TestClient(app)
    document = tmp_path / "agentic.md"
    index_path = tmp_path / "rag_index.json"
    document.write_text("Agentic RAG retrieves local evidence only when useful.", encoding="utf-8")
    client.post("/rag/index", json={"paths": [str(document)], "index_path": str(index_path)})

    skipped = client.post(
        "/rag/local-knowledge",
        json={"query": "你好", "index_path": str(index_path)},
    )
    found = client.post(
        "/rag/local-knowledge",
        json={
            "query": "请根据本地资料解释 Agentic RAG evidence",
            "index_path": str(index_path),
            "top_k": 1,
        },
    )

    assert skipped.status_code == 200
    assert skipped.json()["status"] == "skipped"
    assert found.status_code == 200
    data = found.json()
    assert data["status"] == "found"
    assert data["result_count"] == 1
    assert "agentic.md" in data["sources"]


def test_rag_status_and_upload_endpoints(tmp_path):
    client = TestClient(app)
    index_path = tmp_path / "uploaded_index.json"

    upload_response = client.post(
        "/rag/upload",
        params={"index_path": str(index_path), "max_chars": 200, "overlap_chars": 0},
        files={"files": ("upload.md", b"Uploaded RAG files become indexed chunks.", "text/markdown")},
    )
    status_response = client.get("/rag/status", params={"index_path": str(index_path)})

    assert upload_response.status_code == 200
    assert upload_response.json()["documents"] == 1
    assert status_response.status_code == 200
    data = status_response.json()
    assert data["index_exists"] is True
    assert data["documents"] == 1
    assert data["chunks"] == 1
    assert data["vector_backend"]["name"] == "local"


def test_rag_upload_keeps_duplicate_basenames_unique(monkeypatch, tmp_path):
    from src import api

    upload_dir = tmp_path / "uploads"
    index_path = tmp_path / "duplicate_index.json"
    monkeypatch.setattr(api, "RAG_UPLOAD_DIR", upload_dir)
    client = TestClient(app)

    response = client.post(
        "/rag/upload",
        params={"index_path": str(index_path), "max_chars": 200, "overlap_chars": 0},
        files=[
            ("files", ("same.md", b"First uploaded duplicate basename.", "text/markdown")),
            ("files", ("same.md", b"Second uploaded duplicate basename.", "text/markdown")),
        ],
    )

    assert response.status_code == 200
    assert response.json()["documents"] == 2
    assert response.json()["chunks"] == 2
    assert (upload_dir / "same.md").read_text(encoding="utf-8") == "First uploaded duplicate basename."
    assert (upload_dir / "same-2.md").read_text(encoding="utf-8") == "Second uploaded duplicate basename."


def test_chat_endpoint_builds_reply_and_logs_session(monkeypatch):
    from src import api

    captured = {}

    def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return "API reply"

    monkeypatch.setattr(api, "chat", fake_chat)
    monkeypatch.setattr(api, "load_role", lambda role: f"role prompt for {role}")
    monkeypatch.setattr(api, "read_memory_bundle", lambda context_mode: {})
    monkeypatch.setattr(
        api,
        "load_runtime_modes",
        lambda: RuntimeModes(memory_mode="preview", performance_mode="fast"),
    )
    client = TestClient(app)

    response = client.post(
        "/chat",
        json={
            "user_input": "hello api",
            "selected_role": "march7",
            "selected_mode": "普通",
            "selected_model": "flash",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "API reply"
    assert data["route"]["role"] == "march7"
    assert data["rag"]["status"] == "skipped"
    assert captured["kwargs"]["task_name"] == "single_chat"
    assert captured["messages"][-1]["content"] == "hello api"


def test_memory_preview_and_commit_endpoints(monkeypatch, tmp_path):
    from src import api, memory_writer

    target = tmp_path / "progress.md"
    monkeypatch.setitem(memory_writer.MEMORY_TARGETS, "progress", target)
    monkeypatch.setattr(
        api,
        "load_runtime_modes",
        lambda: RuntimeModes(memory_mode="confirm_write", safe_mode=False),
    )
    monkeypatch.setattr(memory_writer, "load_runtime_modes", api.load_runtime_modes)
    client = TestClient(app)
    payload = {"updates": [{"target": "progress", "content": "API memory update"}]}

    preview = client.post("/memory/preview", json=payload)
    commit = client.post("/memory/commit", json=payload)

    assert preview.status_code == 200
    assert preview.json()["writable"] is True
    assert preview.json()["updates"][0]["path"] == str(target)
    assert commit.status_code == 200
    assert commit.json()["results"][0]["target"] == "progress"
    assert "API memory update" in target.read_text(encoding="utf-8")


def test_memory_append_false_rejected_for_non_replaceable_target(monkeypatch, tmp_path):
    from src import api, memory_writer

    target = tmp_path / "progress.md"
    monkeypatch.setitem(memory_writer.MEMORY_TARGETS, "progress", target)
    monkeypatch.setattr(
        api,
        "load_runtime_modes",
        lambda: RuntimeModes(memory_mode="confirm_write", safe_mode=False),
    )
    client = TestClient(app)
    payload = {"updates": [{"target": "progress", "content": "replace me", "append": False}]}

    preview = client.post("/memory/preview", json=payload)
    commit = client.post("/memory/commit", json=payload)

    assert preview.status_code == 400
    assert commit.status_code == 400
    assert preview.json()["detail"] == "append=false is only supported for target current_focus"
    assert commit.json()["detail"] == "append=false is only supported for target current_focus"
    assert not target.exists()


def test_memory_commit_rejects_when_runtime_is_not_writable(monkeypatch, tmp_path):
    from src import api, memory_writer

    target = tmp_path / "progress.md"
    monkeypatch.setitem(memory_writer.MEMORY_TARGETS, "progress", target)
    monkeypatch.setattr(
        api,
        "load_runtime_modes",
        lambda: RuntimeModes(memory_mode="preview", safe_mode=False),
    )
    client = TestClient(app)

    response = client.post(
        "/memory/commit",
        json={"updates": [{"target": "progress", "content": "should not write"}]},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "preview"
    assert not target.exists()


def test_sessions_endpoint_lists_current_and_archived_files(monkeypatch, tmp_path):
    from src import api

    current_dir = tmp_path / "current"
    archived_dir = tmp_path / "sessions"
    current_dir.mkdir()
    archived_dir.mkdir()
    (current_dir / "active.md").write_text("active session", encoding="utf-8")
    (archived_dir / "old.md").write_text("old session", encoding="utf-8")
    monkeypatch.setattr(api, "CURRENT_SESSION_DIR", current_dir)
    monkeypatch.setattr(api, "SESSION_DIR", archived_dir)
    client = TestClient(app)

    response = client.get("/sessions")

    assert response.status_code == 200
    names = {item["name"] for item in response.json()["sessions"]}
    assert names == {"active.md", "old.md"}


def test_tools_and_workflow_endpoints_record_local_knowledge_call(monkeypatch, tmp_path):
    from src import api

    workflow_dir = tmp_path / "workflows"
    monkeypatch.setattr(api, "WORKFLOW_DIR", workflow_dir)
    document = tmp_path / "tool_notes.md"
    index_path = tmp_path / "rag_index.json"
    document.write_text("Tool registry calls can retrieve cited workflow evidence.", encoding="utf-8")
    client = TestClient(app)
    client.post("/rag/index", json={"paths": [str(document)], "index_path": str(index_path)})

    tools_response = client.get("/tools")
    preview_response = client.post(
        "/tools/retrieve_local_knowledge/preview",
        json={"args": {"query": "local knowledge workflow evidence", "index_path": str(index_path)}},
    )
    call_response = client.post(
        "/tools/retrieve_local_knowledge/call",
        json={
            "run_id": "api-tool-run",
            "args": {
                "query": "local knowledge workflow evidence",
                "index_path": str(index_path),
                "top_k": 1,
            },
        },
    )
    runs_response = client.get("/workflows/runs")
    run_response = client.get("/workflows/runs/api-tool-run")

    assert tools_response.status_code == 200
    assert tools_response.json()["tools"][0]["name"] == "retrieve_local_knowledge"
    assert preview_response.status_code == 200
    assert preview_response.json()["status"] == "preview"
    assert call_response.status_code == 200
    assert call_response.json()["status"] == "succeeded"
    assert call_response.json()["output"]["status"] == "found"
    assert runs_response.status_code == 200
    assert runs_response.json()["runs"][0]["run_id"] == "api-tool-run"
    assert run_response.status_code == 200
    assert [event["event_type"] for event in run_response.json()["run"]["events"]] == [
        "started",
        "succeeded",
    ]
