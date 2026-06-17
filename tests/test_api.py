from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.mode_manager import RuntimeModes
from src.performance_budget import chat_max_tokens
from src.api import app


def test_health_endpoint_reports_ok():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "study-agent"
    assert isinstance(data["rag_index_exists"], bool)


def test_api_token_gate_allows_health_and_blocks_other_routes(monkeypatch):
    monkeypatch.setenv("STUDY_AGENT_API_TOKEN", "local-secret")
    client = TestClient(app)

    health = client.get("/health")
    blocked = client.get("/tools")
    wrong = client.get("/tools", headers={"Authorization": "Bearer wrong"})
    bearer = client.get("/tools", headers={"Authorization": "Bearer local-secret"})
    header = client.get("/tools", headers={"X-Study-Agent-Token": "local-secret"})

    assert health.status_code == 200
    assert blocked.status_code == 401
    assert blocked.json()["detail"] == "Missing or invalid API token"
    assert wrong.status_code == 401
    assert bearer.status_code == 200
    assert header.status_code == 200


def test_cors_allowlist_handles_preflight_and_response_headers(monkeypatch):
    monkeypatch.setenv("STUDY_AGENT_CORS_ORIGINS", "http://localhost:5173,https://study.example")
    client = TestClient(app)

    preflight = client.options(
        "/tools",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    rejected = client.options(
        "/tools",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    response = client.get("/health", headers={"Origin": "https://study.example"})

    assert preflight.status_code == 204
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "Authorization" in preflight.headers["access-control-allow-headers"]
    assert rejected.status_code == 403
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://study.example"
    assert response.headers["vary"] == "Origin"


def test_runtime_settings_endpoint_reads_and_persists_frontend_defaults(monkeypatch, tmp_path):
    from src import api

    settings_path = tmp_path / "frontend_settings.yaml"
    monkeypatch.setattr(api, "FRONTEND_SETTINGS_PATH", settings_path)
    client = TestClient(app)

    initial = client.get("/runtime/settings")
    patched = client.patch(
        "/runtime/settings",
        json={
            "selected_role": "keqing",
            "selected_mode": "项目",
            "selected_model": "flash",
            "rag_retrieval_mode": "lexical",
            "rag_top_k": 4,
            "rag_min_score": 0.02,
        },
    )
    loaded = client.get("/runtime/settings")

    assert initial.status_code == 200
    assert initial.json()["settings"]["selected_role"] == "auto"
    assert patched.status_code == 200
    assert patched.json()["settings"]["selected_role"] == "keqing"
    assert patched.json()["settings"]["selected_mode"] == "项目"
    assert patched.json()["settings"]["rag_retrieval_mode"] == "lexical"
    assert loaded.json()["settings"]["rag_top_k"] == 4
    assert settings_path.exists()


def test_runtime_settings_endpoint_rejects_invalid_frontend_choice(monkeypatch, tmp_path):
    from src import api

    monkeypatch.setattr(api, "FRONTEND_SETTINGS_PATH", tmp_path / "frontend_settings.yaml")
    client = TestClient(app)

    response = client.patch("/runtime/settings", json={"selected_role": "unknown"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid selected_role: unknown"


def test_runtime_settings_endpoint_ignores_invalid_frontend_yaml(monkeypatch, tmp_path):
    from src import api

    settings_path = tmp_path / "frontend_settings.yaml"
    settings_path.write_text("selected_role: [", encoding="utf-8")
    monkeypatch.setattr(api, "FRONTEND_SETTINGS_PATH", settings_path)
    client = TestClient(app)

    response = client.get("/runtime/settings")

    assert response.status_code == 200
    assert response.json()["settings"]["selected_role"] == "auto"


def test_roles_endpoints_expose_labels_and_prompt():
    client = TestClient(app)

    roles = client.get("/roles")
    role = client.get("/roles/keqing")
    missing = client.get("/roles/not-a-role")

    assert roles.status_code == 200
    assert {"id": "keqing", "label": "刻晴", "summary": role.json()["summary"]} in roles.json()["roles"]
    assert role.status_code == 200
    assert role.json()["id"] == "keqing"
    assert role.json()["label"] == "刻晴"
    assert role.json()["prompt"]
    assert role.json()["description"]
    assert role.json()["summary"] == role.json()["description"]
    assert not role.json()["summary"].startswith("#")
    assert missing.status_code == 404


def test_memory_status_endpoint_reports_runtime_and_files():
    client = TestClient(app)

    response = client.get("/memory")

    assert response.status_code == 200
    data = response.json()
    assert data["memory_mode"] in {"readonly", "preview", "confirm_write", "locked"}
    assert data["reason"]
    assert data["context_mode"] in {"fast", "light", "deep", "archive"}
    assert "deep" in data["groups"]
    assert any(item["name"] == "current_focus.md" for item in data["files"])


def test_wechat_status_and_opening_endpoints(monkeypatch):
    from src import api

    monkeypatch.setattr(api, "read_wechat_state", lambda: {"mode": "interactive_group"})
    monkeypatch.setattr(api, "read_wechat_group", lambda: "group content")
    monkeypatch.setattr(api, "read_wechat_unread", lambda: "unread content")
    monkeypatch.setattr(api, "has_wechat_unread", lambda: True)
    monkeypatch.setattr(api, "has_wechat_group_started", lambda: True)
    monkeypatch.setattr(api, "count_wechat_messages", lambda content: 2 if content else 0)
    monkeypatch.setattr(api, "summarize_wechat", lambda: "summary")
    monkeypatch.setattr(api, "generate_wechat_opening", lambda **kwargs: "opening")
    started = []
    monkeypatch.setattr(api, "start_wechat_group_with_opening", lambda content: started.append(content))
    client = TestClient(app)

    status = client.get("/wechat")
    opening = client.post(
        "/wechat/opening",
        json={"selected_role": "auto", "selected_model": "flash", "relationship_mode": "standard"},
    )

    assert status.status_code == 200
    assert status.json()["content"] == "group content"
    assert status.json()["has_unread"] is True
    assert opening.status_code == 200
    assert started == ["opening"]


def test_wechat_message_endpoint_generates_reply_and_updates_group(monkeypatch):
    from src import api

    class FakeRagResult:
        context = "rag context"

        def to_dict(self):
            return {"status": "found", "context": self.context}

    actions = []
    monkeypatch.setattr(api, "retrieve_local_knowledge", lambda *args, **kwargs: FakeRagResult())
    monkeypatch.setattr(
        api,
        "generate_interactive_wechat_reply",
        lambda *args, **kwargs: "group reply",
    )
    monkeypatch.setattr(
        api,
        "append_user_and_interactive_group_reply",
        lambda message, reply: actions.append(("combined", message, reply)),
    )
    monkeypatch.setattr(api, "update_wechat_join_state", lambda **kwargs: actions.append(("state", kwargs)))
    monkeypatch.setattr(api, "set_wechat_interactive", lambda session_id, status: actions.append(("interactive", status)))
    monkeypatch.setattr(api, "set_wechat_status", lambda session_id, status: actions.append(("status", status)))
    monkeypatch.setattr(api, "init_session", lambda: "wechat-session")
    monkeypatch.setattr(api, "read_wechat_group", lambda: "updated group")
    monkeypatch.setattr(api, "read_wechat_state", lambda: {"mode": "interactive_group"})
    client = TestClient(app)

    response = client.post(
        "/wechat/message",
        json={"message": "hello group", "selected_model": "flash", "rag_enabled": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "group reply"
    assert data["content"] == "updated group"
    assert data["session_id"] == "wechat-session"
    assert ("combined", "hello group", "group reply") in actions


def test_wechat_message_generation_failure_does_not_write_group(monkeypatch):
    from src import api

    class FakeRagResult:
        context = ""

        def to_dict(self):
            return {"status": "skipped", "context": self.context}

    actions = []
    monkeypatch.setattr(api, "retrieve_local_knowledge", lambda *args, **kwargs: FakeRagResult())

    def fail_generation(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(api, "generate_interactive_wechat_reply", fail_generation)
    monkeypatch.setattr(
        api,
        "append_user_and_interactive_group_reply",
        lambda message, reply: actions.append(("combined", message, reply)),
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/wechat/message",
        json={"message": "hello group", "selected_model": "flash"},
    )

    assert response.status_code == 500
    assert actions == []


def test_news_search_endpoint_runs_news_round(monkeypatch):
    from src import api

    captured = {}

    def fake_run_news_round(query_text, read_articles, runtime_context):
        captured["query_text"] = query_text
        captured["read_articles"] = read_articles
        captured["runtime_context"] = runtime_context
        return SimpleNamespace(
            query_text=query_text,
            news_items=[{"title": "A"}],
            digest="digest",
            discussion="discussion",
            group_content="group",
            source_block="source",
            article_coverage={"total": 1},
            elapsed_ms=12,
            warnings=[],
            audit_markdown_path="audit.md",
            audit_json_path="audit.json",
        )

    monkeypatch.setattr(api, "run_news_round", fake_run_news_round)
    monkeypatch.setattr(api, "init_session", lambda: "news-session")
    client = TestClient(app)

    response = client.post(
        "/news/search",
        json={
            "query": "OpenAI latest",
            "read_articles": False,
            "selected_model": "flash",
            "relationship_mode": "warm",
            "performance_mode": "fast",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["digest"] == "digest"
    assert data["discussion"] == "discussion"
    assert data["session_id"] == "news-session"
    assert captured["query_text"] == "OpenAI latest"
    assert captured["read_articles"] is False
    assert captured["runtime_context"].interaction_mode == "warm"
    assert captured["runtime_context"].performance_mode == "fast"


def test_news_lookup_endpoint_returns_source_block(monkeypatch):
    from src import api

    monkeypatch.setattr(api, "fetch_news_items", lambda **kwargs: [{"title": "A", "source": "S"}])
    monkeypatch.setattr(api, "format_news_source_block", lambda query, items: f"source:{query}:{len(items)}")
    monkeypatch.setattr(api, "get_last_feed_warnings", lambda: ["warn"])
    client = TestClient(app)

    response = client.post("/news/lookup", json={"query": "OpenAI latest", "max_items": 3})

    assert response.status_code == 200
    assert response.json()["news_items"] == [{"title": "A", "source": "S"}]
    assert response.json()["source_block"] == "source:OpenAI latest:1"
    assert response.json()["warnings"] == ["warn"]


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


def test_rag_upload_appends_by_default_and_can_rebuild(tmp_path):
    client = TestClient(app)
    index_path = tmp_path / "append_index.json"

    first = client.post(
        "/rag/upload",
        params={"index_path": str(index_path), "max_chars": 200, "overlap_chars": 0},
        files={"files": ("a.md", b"Alpha document stays in the knowledge base.", "text/markdown")},
    )
    second = client.post(
        "/rag/upload",
        params={"index_path": str(index_path), "max_chars": 200, "overlap_chars": 0},
        files={"files": ("b.md", b"Beta document is appended later.", "text/markdown")},
    )
    rebuilt = client.post(
        "/rag/upload",
        params={"index_path": str(index_path), "max_chars": 200, "overlap_chars": 0, "mode": "rebuild"},
        files={"files": ("c.md", b"Gamma document replaces the previous index.", "text/markdown")},
    )

    assert first.status_code == 200
    assert first.json()["documents"] == 1
    assert second.status_code == 200
    assert second.json()["documents"] == 2
    assert rebuilt.status_code == 200
    assert rebuilt.json()["documents"] == 1


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

    class FakeRagResult:
        status = "skipped"
        context = ""

        def to_dict(self):
            return {"status": self.status, "context": self.context, "result_count": 0}

    def fake_retrieve(*args, **kwargs):
        captured["rag_kwargs"] = kwargs
        return FakeRagResult()

    monkeypatch.setattr(api, "chat", fake_chat)
    monkeypatch.setattr(api, "load_role", lambda role: f"role prompt for {role}")
    monkeypatch.setattr(api, "read_memory_bundle", lambda context_mode: {})
    monkeypatch.setattr(api, "retrieve_local_knowledge", fake_retrieve)
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
            "web_context": "source: web result",
            "conversation_instruction": "本轮直接回答，不转交。",
            "performance_mode": "deep",
            "rag_min_score": 0.42,
            "chat_history": [
                {"role": "user", "content": "old"},
                {"role": "assistant", "content": "old reply"},
                {"role": "user", "content": "hello api"},
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "API reply"
    assert data["route"]["role"] == "march7"
    assert data["rag"]["status"] == "skipped"
    assert captured["kwargs"]["task_name"] == "single_chat"
    assert captured["kwargs"]["max_tokens"] == chat_max_tokens("deep")
    assert captured["rag_kwargs"]["min_score"] == 0.42
    assert captured["messages"][-1]["content"] == "hello api"
    assert sum(1 for message in captured["messages"] if message["content"] == "hello api") == 1
    assert any("source: web result" in message["content"] for message in captured["messages"])
    assert "当前场景是单人对话" in captured["messages"][0]["content"]
    assert "[Conversation instruction]\n本轮直接回答，不转交。" in captured["messages"][0]["content"]


def test_previous_assistant_role_uses_avatar_role():
    from src import api

    history = [
        api.ChatMessage(role="user", content="first"),
        api.ChatMessage(role="assistant", content="reply", avatarRole="nahida"),
        api.ChatMessage(role="user", content="follow-up"),
    ]

    assert api._previous_assistant_role(history) == "nahida"


def test_chat_stream_endpoint_emits_sse_and_logs(monkeypatch):
    from src import api

    logged = {}

    class FakeRagResult:
        status = "skipped"
        context = ""

        def to_dict(self):
            return {"status": self.status, "context": self.context, "result_count": 0}

    monkeypatch.setattr(api, "stream_chat", lambda *args, **kwargs: iter(["Hello", " stream"]))
    monkeypatch.setattr(api, "load_role", lambda role: f"role prompt for {role}")
    monkeypatch.setattr(api, "read_memory_bundle", lambda context_mode: {})
    monkeypatch.setattr(api, "retrieve_local_knowledge", lambda *args, **kwargs: FakeRagResult())
    monkeypatch.setattr(api, "init_session", lambda: "stream-session")
    monkeypatch.setattr(api, "log", lambda **kwargs: logged.update(kwargs))
    monkeypatch.setattr(api, "flush_current_session", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        api,
        "load_runtime_modes",
        lambda: RuntimeModes(memory_mode="preview", performance_mode="fast"),
    )
    client = TestClient(app)

    response = client.post(
        "/chat/stream",
        json={
            "user_input": "stream please",
            "selected_role": "march7",
            "selected_mode": "普通",
            "selected_model": "flash",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: route" in body
    assert "event: rag" in body
    assert body.count("event: token") == 2
    assert 'data: {"text": "Hello"}' in body
    assert "event: usage" in body
    assert "event: done" in body
    assert logged["session_id"] == "stream-session"
    assert logged["agent_reply"] == "Hello stream"
    assert logged["route_info"]["streamed"] is True


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
    assert preview.json()["updates"][0]["preview"] == "## 课后更新\n\nAPI memory update\n"
    assert commit.status_code == 200
    assert commit.json()["results"][0]["target"] == "progress"
    assert "API memory update" in target.read_text(encoding="utf-8")


def test_memory_preview_matches_pending_and_replace_format(monkeypatch, tmp_path):
    from src import api, memory_writer

    focus = tmp_path / "current_focus.md"
    summary = tmp_path / "summary.md"
    monkeypatch.setitem(memory_writer.MEMORY_TARGETS, "current_focus", focus)
    monkeypatch.setitem(memory_writer.MEMORY_TARGETS, "summary", summary)
    monkeypatch.setattr(
        api,
        "load_runtime_modes",
        lambda: RuntimeModes(memory_mode="confirm_write", safe_mode=False),
    )
    client = TestClient(app)

    response = client.post(
        "/memory/preview",
        json={
            "updates": [
                {"target": "current_focus", "content": "Focus now", "append": False},
                {"target": "summary", "content": "Maybe useful", "learner_pending": True},
            ]
        },
    )

    assert response.status_code == 200
    updates = response.json()["updates"]
    assert updates[0]["action"] == "replace"
    assert updates[0]["preview"] == "Focus now\n"
    assert updates[1]["action"] == "append"
    assert updates[1]["preview"] == "### 待确认观察\n\nMaybe useful\n"


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


def test_session_detail_restores_archived_messages(monkeypatch, tmp_path):
    from src import api

    current_dir = tmp_path / "current"
    archived_dir = tmp_path / "sessions"
    current_dir.mkdir()
    archived_dir.mkdir()
    session_file = archived_dir / "2026-06-16_10-00-00_session_restoreme_keqing_pro.md"
    session_file.write_text(
        "# Session\n\n"
        "## 2026-06-16 10:00:00\n"
        "**User**\n旧问题完整内容\n\n"
        "**Agent**\n旧回答完整内容\n\n"
        "---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "CURRENT_SESSION_DIR", current_dir)
    monkeypatch.setattr(api, "SESSION_DIR", archived_dir)
    client = TestClient(app)

    response = client.get("/sessions/restoreme")

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "restoreme"
    assert data["kind"] == "archived"
    assert data["messages"] == [
        {"role": "user", "content": "旧问题完整内容"},
        {"role": "assistant", "content": "旧回答完整内容"},
    ]


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
