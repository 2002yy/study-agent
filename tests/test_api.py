from __future__ import annotations

from dataclasses import replace
from pathlib import Path

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
    assert "PATCH" in preflight.headers["access-control-allow-methods"]
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
            "rag_search_top_k": 6,
            "rag_chat_top_k": 4,
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
    assert loaded.json()["settings"]["rag_search_top_k"] == 6
    assert loaded.json()["settings"]["rag_chat_top_k"] == 4
    assert loaded.json()["settings"]["rag_top_k"] == 4
    assert settings_path.exists()


def test_runtime_settings_endpoint_accepts_legacy_rag_top_k(monkeypatch, tmp_path):
    from src import api

    monkeypatch.setattr(api, "FRONTEND_SETTINGS_PATH", tmp_path / "frontend_settings.yaml")
    client = TestClient(app)

    response = client.patch("/runtime/settings", json={"rag_top_k": 7})

    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["rag_search_top_k"] == 7
    assert settings["rag_chat_top_k"] == 7
    assert settings["rag_top_k"] == 7


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


def test_memory_file_preview_prefers_latest_content(monkeypatch, tmp_path):
    from src import api

    path = tmp_path / "progress.md"
    path.write_text("x" * 1700 + "LATEST", encoding="utf-8")
    monkeypatch.setattr(api, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(api, "read_memory_file", lambda name: path.read_text(encoding="utf-8"))

    row = api._memory_file_row("progress.md")

    assert row["preview"].endswith("LATEST")
    assert len(row["preview"]) == 1600


def test_wechat_status_and_opening_endpoints(runtime_test_context):
    client = TestClient(app)

    status = client.get("/wechat")
    thread_id = status.json()["group_thread_id"]
    opening = client.post(
        "/wechat/opening",
        json={
            "group_thread_id": thread_id,
            "selected_role": "auto",
            "selected_model": "flash",
            "relationship_mode": "standard",
        },
    )

    assert status.status_code == 200
    assert status.json()["content"] == ""
    assert opening.status_code == 200
    assert opening.json()["group_thread_id"] == thread_id
    assert "opening" in opening.json()["content"]
    assert runtime_test_context.group_repository.list_messages(thread_id)[0].status == "committed"


def test_wechat_message_endpoint_generates_reply_and_updates_group(runtime_test_context):
    class FakeRagResult:
        context = "rag context"

        def to_dict(self):
            return {"status": "found", "context": self.context}

    captured_rag = {}

    def fake_retrieve_local_knowledge(*args, **kwargs):
        captured_rag.update(kwargs)
        return FakeRagResult()

    service = runtime_test_context.group_service
    service.dependencies = replace(
        service.dependencies,
        retrieve_local_knowledge=fake_retrieve_local_knowledge,
        generate_reply=lambda *args, **kwargs: "group reply",
    )
    client = TestClient(app)

    response = client.post(
        "/wechat/message",
        json={"message": "hello group", "selected_model": "flash", "rag_enabled": True, "rag_min_score": 0.37},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "group reply"
    assert "hello group" in data["content"]
    assert data["session_id"] == data["group_thread_id"]
    assert captured_rag["min_score"] == 0.37
    messages = runtime_test_context.group_repository.list_messages(data["group_thread_id"])
    assert [message.status for message in messages] == ["committed", "committed"]


def test_wechat_message_generation_failure_marks_failed_message(runtime_test_context):
    def fail_generation(*args, **kwargs):
        raise RuntimeError("model unavailable")

    service = runtime_test_context.group_service
    service.dependencies = replace(
        service.dependencies,
        generate_reply=fail_generation,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/wechat/message",
        json={"message": "hello group", "selected_model": "flash"},
    )

    assert response.status_code == 500
    thread = runtime_test_context.group_repository.list_threads()[0]
    messages = runtime_test_context.group_repository.list_messages(thread.id)
    assert [message.status for message in messages] == ["failed", "failed"]
    assert "model unavailable" in messages[-1].error


def test_wechat_message_stream_endpoint_emits_tokens_and_commits_group(runtime_test_context):
    client = TestClient(app)

    response = client.post(
        "/wechat/message/stream",
        json={"message": "hello stream group", "selected_model": "flash", "rag_enabled": True},
    )

    assert response.status_code == 200
    body = response.text
    assert "event: rag" in body
    assert "event: session" in body
    assert "group_thread_id" in body
    assert "operation_id" in body
    assert body.count("event: token") == 2
    assert "event: done" in body
    thread = runtime_test_context.group_repository.list_threads()[0]
    messages = runtime_test_context.group_repository.list_messages(thread.id)
    assert [message.status for message in messages] == ["committed", "committed"]


def test_legacy_news_round_routes_are_gone_without_running_legacy_flow(
    monkeypatch, runtime_test_context
):
    from src import api

    def fail_legacy(*args, **kwargs):
        raise AssertionError("legacy flow must not run")

    monkeypatch.setattr(
        api,
        "run_news_round",
        fail_legacy,
    )
    client = TestClient(app)
    payload = {"query": "OpenAI latest"}
    group_file = runtime_test_context.group_service.importer.group_file

    assert client.post("/news/round", json=payload).status_code == 410
    assert client.post("/wechat/news-round", json=payload).status_code == 410
    assert not group_file.exists()


def test_news_discussion_outputs_remain_isolated_by_group_thread(
    monkeypatch, runtime_test_context
):
    from src import api

    monkeypatch.setattr(
        api,
        "run_discussion_stage",
        lambda digest, **kwargs: (f"【纳西妲】\nreply for {digest}", "legacy ignored"),
    )
    first = runtime_test_context.group_service.create_thread(title="First")
    second = runtime_test_context.group_service.create_thread(title="Second")
    client = TestClient(app)

    for thread, digest in ((first, "alpha"), (second, "beta")):
        response = client.post(
            "/news/discuss",
            json={"digest": digest, "session_id": thread.id},
        )
        assert response.status_code == 200
        assert response.json()["session_id"] == thread.id

    first_content = runtime_test_context.group_service.get_state(first.id)["content"]
    second_content = runtime_test_context.group_service.get_state(second.id)["content"]
    assert "alpha" in first_content and "beta" not in first_content
    assert "beta" in second_content and "alpha" not in second_content


def test_news_stage_endpoints_run_individual_steps(monkeypatch, runtime_test_context):
    from src import api

    calls = {}
    monkeypatch.setattr(api, "run_search_stage", lambda query, max_items=10: [{"title": query, "rank": max_items}])
    monkeypatch.setattr(
        api,
        "run_enrich_stage",
        lambda news_items, max_articles, query_text="", max_chars_per_article=5000: [
            {**news_items[0], "article_text": query_text, "max_articles": max_articles}
        ],
    )

    def fake_digest(news_items, query_text, performance_mode, selected_model):
        calls["digest"] = (news_items, query_text, performance_mode, selected_model)
        return "digest", "source", {"total": len(news_items)}, ["warn"]

    def fake_discussion(
        digest,
        interaction_mode,
        performance_mode,
        selected_model,
        source_block="",
        session_id="",
        progress=None,
        persist_group=True,
    ):
        calls["discussion"] = (digest, interaction_mode, performance_mode, selected_model, source_block, session_id)
        return "discussion", "group"

    monkeypatch.setattr(api, "run_digest_stage", fake_digest)
    monkeypatch.setattr(api, "run_discussion_stage", fake_discussion)
    monkeypatch.setattr(api, "init_session", lambda: "news-stage-session")
    client = TestClient(app)

    search = client.post("/news/search", json={"query": "AI", "max_items": 4})
    enrich = client.post(
        "/news/enrich",
        json={"query_text": "AI", "news_items": search.json()["news_items"], "max_articles": 2},
    )
    digest = client.post(
        "/news/digest",
        json={"query_text": "AI", "news_items": enrich.json()["news_items"], "selected_model": "flash", "performance_mode": "fast"},
    )
    discuss = client.post(
        "/news/discuss",
        json={
            "digest": digest.json()["digest"],
            "source_block": digest.json()["source_block"],
            "selected_model": "flash",
            "relationship_mode": "warm",
            "performance_mode": "fast",
        },
    )

    assert search.status_code == 200
    assert search.json()["news_items"][0]["rank"] == 4
    assert enrich.status_code == 200
    assert enrich.json()["news_items"][0]["max_articles"] == 2
    assert digest.status_code == 200
    assert digest.json()["source_block"] == "source"
    assert digest.json()["warnings"] == ["warn"]
    assert discuss.status_code == 200
    group_thread_id = discuss.json()["session_id"]
    assert group_thread_id.startswith("group_")
    group_messages = runtime_test_context.group_repository.list_messages(
        group_thread_id
    )
    assert [message.message_type for message in group_messages] == [
        "news_source",
        "news_discussion",
    ]
    assert calls["digest"][2] == "fast"
    assert calls["discussion"][1] == "warm"


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
    upload_data = upload_response.json()
    assert upload_data["documents"] == 1
    assert upload_data["stages"][0]["name"] == "local"
    assert upload_data["stages"][0]["status"] == "completed"
    assert upload_data["stages"][1]["name"] == "vector"
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
    assert [stage["name"] for stage in response.json()["stages"]] == ["local", "vector"]
    assert (upload_dir / "same.md").read_text(encoding="utf-8") == "First uploaded duplicate basename."
    assert (upload_dir / "same-2.md").read_text(encoding="utf-8") == "Second uploaded duplicate basename."


def test_rag_upload_reports_vector_stage_failure(monkeypatch, tmp_path):
    from src.rag import service as rag_service

    class BrokenVectorBackend:
        def upsert_index(self, index):
            raise RuntimeError("vector offline")

    monkeypatch.setattr(rag_service, "get_vector_backend_from_env", lambda: BrokenVectorBackend())
    client = TestClient(app)
    index_path = tmp_path / "partial_index.json"

    response = client.post(
        "/rag/upload",
        params={"index_path": str(index_path), "max_chars": 200, "overlap_chars": 0},
        files={"files": ("partial.md", b"Local index should still be saved.", "text/markdown")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["documents"] == 1
    assert data["stages"][0]["status"] == "completed"
    assert data["stages"][1]["name"] == "vector"
    assert data["stages"][1]["status"] == "failed"
    assert "vector offline" in data["stages"][1]["detail"]
    assert index_path.exists()


def test_chat_endpoint_builds_reply_and_logs_session(runtime_test_context):
    from src.application.chat_service import ChatDependencies
    from src.context_builder import build_messages
    from src.router import route_request

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

    runtime_test_context.override_chat(
        ChatDependencies(
            load_runtime_modes=lambda: RuntimeModes(
                memory_mode="preview",
                performance_mode="fast",
            ),
            read_memory_bundle=lambda context_mode: {},
            build_role_prompt=lambda role, **kwargs: f"role prompt for {role}",
            route_request=route_request,
            retrieve_local_knowledge=fake_retrieve,
            build_messages=build_messages,
            chat=fake_chat,
            stream_chat=lambda *args, **kwargs: iter(()),
            chat_max_tokens=chat_max_tokens,
        )
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
    assert data["turn_id"].startswith("turn_")
    assert data["route"]["role"] == "march7"
    assert data["rag"]["status"] == "skipped"
    assert captured["kwargs"]["task_name"] == "single_chat"
    assert captured["kwargs"]["max_tokens"] == chat_max_tokens("deep")
    assert captured["rag_kwargs"]["min_score"] == 0.42
    assert captured["messages"][-1]["content"] == "hello api"
    assert sum(1 for message in captured["messages"] if message["content"] == "hello api") == 1
    assert any("source: web result" in message["content"] for message in captured["messages"])
    assert "当前场景是用户与所选角色的单人对话" in captured["messages"][0]["content"]
    assert "用户明确提出“直接回答”“不要追问”“不要切换角色”" in captured["messages"][0]["content"]
    assert "[Conversation instruction]\n本轮直接回答，不转交。" in captured["messages"][0]["content"]


def test_previous_assistant_role_uses_avatar_role():
    from src import api

    history = [
        api.ChatMessage(role="user", content="first"),
        api.ChatMessage(role="assistant", content="reply", avatarRole="nahida"),
        api.ChatMessage(role="user", content="follow-up"),
    ]

    assert api._previous_assistant_role(history) == "nahida"


def test_chat_stream_endpoint_emits_sse_and_logs(runtime_test_context):
    from src.application.chat_service import ChatDependencies
    from src.context_builder import build_messages
    from src.router import route_request

    class FakeRagResult:
        status = "skipped"
        context = ""

        def to_dict(self):
            return {"status": self.status, "context": self.context, "result_count": 0}

    async def async_tokens(*args, **kwargs):
        yield "Hello"
        yield " stream"

    runtime_test_context.override_chat(
        ChatDependencies(
            load_runtime_modes=lambda: RuntimeModes(
                memory_mode="preview",
                performance_mode="fast",
            ),
            read_memory_bundle=lambda context_mode: {},
            build_role_prompt=lambda role, **kwargs: f"role prompt for {role}",
            route_request=route_request,
            retrieve_local_knowledge=lambda *args, **kwargs: FakeRagResult(),
            build_messages=build_messages,
            chat=lambda *args, **kwargs: "unused",
            stream_chat=lambda *args, **kwargs: iter(["Hello", " stream"]),
            async_stream_chat=async_tokens,
            chat_max_tokens=chat_max_tokens,
        )
    )
    client = TestClient(app)

    response = client.post(
        "/chat/stream",
        json={
            "user_input": "stream please",
            "selected_role": "march7",
            "selected_mode": "普通",
            "selected_model": "flash",
            "session_id": "stream-session",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: route" in body
    assert "event: session" in body
    assert '"turn_id": "turn_' in body
    assert '"operation_id": "op_' in body
    assert "event: rag" in body
    assert body.count("event: token") == 2
    assert 'data: {"text": "Hello"}' in body
    assert "event: usage" in body
    assert "event: done" in body
    turns = runtime_test_context.repository.list_chat_turns("stream-session")
    assert len(turns) == 1
    assert turns[0].id.startswith("turn_")
    assert turns[0].assistant_message == "Hello stream"
    assert turns[0].status == "completed"


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


def test_sessions_endpoint_lists_current_and_archived_files(runtime_test_context):
    current_dir = runtime_test_context.current_dir
    archived_dir = runtime_test_context.archive_dir
    current_dir.mkdir()
    archived_dir.mkdir()
    (current_dir / "active.md").write_text("active session", encoding="utf-8")
    (archived_dir / "old.md").write_text("old session", encoding="utf-8")
    client = TestClient(app)

    response = client.get("/sessions")

    assert response.status_code == 200
    names = {item["name"] for item in response.json()["sessions"]}
    assert names == {"active.md", "old.md"}


def test_session_detail_restores_archived_messages(runtime_test_context):
    current_dir = runtime_test_context.current_dir
    archived_dir = runtime_test_context.archive_dir
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
    client = TestClient(app)

    response = client.get("/sessions/restoreme")

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "restoreme"
    assert data["kind"] == "archived"
    assert [
        {key: message[key] for key in ("role", "content", "avatarRole")}
        for message in data["messages"]
    ] == [
        {"role": "user", "content": "旧问题完整内容", "avatarRole": "user"},
        {"role": "assistant", "content": "旧回答完整内容", "avatarRole": "auto"},
    ]
    assert data["messages"][0]["turnId"] == data["messages"][1]["turnId"]
    assert data["messages"][0]["turnStatus"] == "completed"


def test_current_session_snapshot_restores_full_state_and_avatar(
    monkeypatch,
    runtime_test_context,
):
    from src import session_logger

    current_dir = runtime_test_context.current_dir
    current_dir.mkdir()
    monkeypatch.setattr(session_logger, "CURRENT_DIR", current_dir)
    session_id = session_logger.init_session()
    long_user = "user-" + ("x" * 180)
    long_agent = "agent-" + ("y" * 260)

    session_logger.log(
        session_id=session_id,
        role="nahida",
        mode="苏格拉底",
        model="pro",
        user_input=long_user,
        agent_reply=long_agent,
        route_info={"role": "nahida", "mode": "苏格拉底", "model_profile": "pro"},
        session_settings={"selectedRole": "auto", "selectedMode": "auto", "contextMode": "deep"},
        rag_info={"status": "found", "result_count": 2},
        conversation_instruction="直接回答，不转交。",
    )
    assert session_logger.flush_current_session(session_id, force=True)

    client = TestClient(app)
    response = client.get(f"/sessions/{session_id}")

    assert response.status_code == 200
    data = response.json()
    assert [
        {key: message[key] for key in ("role", "content", "avatarRole")}
        for message in data["messages"]
    ] == [
        {"role": "user", "content": long_user, "avatarRole": "user"},
        {"role": "assistant", "content": long_agent, "avatarRole": "nahida"},
    ]
    assert data["messages"][0]["turnId"] == data["messages"][1]["turnId"]
    assert data["messages"][0]["turnStatus"] == "completed"
    assert data["settings"]["contextMode"] == "deep"
    assert data["route"]["mode"] == "苏格拉底"
    assert data["rag"]["result_count"] == 2
    assert data["conversation_instruction"] == "直接回答，不转交。"


def test_create_new_session_returns_default_settings():
    client = TestClient(app)

    response = client.post("/sessions/new")

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"]
    assert "selected_role" in data["settings"]


def test_commit_turn_updates_existing_partial_reply_by_turn_id(runtime_test_context):
    from src.domain.runtime_entities import ChatThread, ChatTurn

    session_id = "chat_partial_api"
    client = TestClient(app)
    runtime_test_context.repository.create_chat_thread(ChatThread(id=session_id))
    runtime_test_context.repository.upsert_chat_turn(
        ChatTurn(
            id="turn_partial",
            thread_id=session_id,
            user_message="question",
            assistant_message="",
            status="interrupted",
            operation_id="op_partial",
            role="nahida",
            mode="normal",
            model="flash",
        )
    )
    base_payload = {
        "session_id": session_id,
        "user_input": "question",
        "role": "nahida",
        "mode": "normal",
        "model": "flash",
        "turn_id": "turn_partial",
        "operation_id": "op_partial",
    }

    first = client.post(
        f"/sessions/{session_id}/commit-turn",
        json={**base_payload, "agent_reply": "partial"},
    )
    second = client.post(
        f"/sessions/{session_id}/commit-turn",
        json={**base_payload, "agent_reply": "partial plus more"},
    )
    duplicate = client.post(
        f"/sessions/{session_id}/commit-turn",
        json={**base_payload, "agent_reply": "partial plus more"},
    )

    entries = runtime_test_context.repository.list_chat_turns(session_id)
    assert first.status_code == 200
    assert first.json()["committed"] is True
    assert second.json()["committed"] is True
    assert duplicate.json()["committed"] is False
    assert len(entries) == 1
    assert entries[0].id == "turn_partial"
    assert entries[0].assistant_message == "partial plus more"
    assert entries[0].status == "interrupted"


def test_commit_turn_rejects_client_created_thread_and_turn(runtime_test_context):
    client = TestClient(app)

    response = client.post(
        "/sessions/chat_ghost/commit-turn",
        json={
            "session_id": "chat_ghost",
            "user_input": "question",
            "agent_reply": "partial",
            "role": "nahida",
            "mode": "normal",
            "model": "flash",
            "turn_id": "turn_ghost",
            "operation_id": "op_ghost",
        },
    )

    assert response.status_code == 409
    assert runtime_test_context.repository.get_chat_thread("chat_ghost") is None
    assert runtime_test_context.repository.get_chat_turn("turn_ghost") is None


def test_stale_commit_cannot_interrupt_active_operation(runtime_test_context):
    from src.domain.runtime_entities import ChatThread, ChatTurn

    repository = runtime_test_context.repository
    repository.create_chat_thread(ChatThread(id="chat_active_owner"))
    repository.acquire_chat_operation("chat_active_owner", "op_current")
    repository.add_chat_turn(
        ChatTurn(
            id="turn_active_owner",
            thread_id="chat_active_owner",
            user_message="question",
            status="streaming",
            operation_id="op_current",
        )
    )

    response = TestClient(app).post(
        "/sessions/chat_active_owner/commit-turn",
        json={
            "session_id": "chat_active_owner",
            "user_input": "question",
            "agent_reply": "stale partial",
            "turn_id": "turn_active_owner",
            "operation_id": "op_stale",
        },
    )

    stored = repository.get_chat_turn("turn_active_owner")
    thread = repository.get_chat_thread("chat_active_owner")
    assert response.status_code == 409
    assert stored is not None and stored.status == "streaming"
    assert stored.assistant_message == ""
    assert thread is not None and thread.active_operation_id == "op_current"


def test_archive_active_session_endpoint(runtime_test_context):
    from src.domain.runtime_entities import ChatTurn

    current_dir = runtime_test_context.current_dir
    session_dir = runtime_test_context.archive_dir
    current_dir.mkdir()
    session_dir.mkdir()
    thread = runtime_test_context.session_service.create_session({})
    runtime_test_context.repository.add_chat_turn(
        ChatTurn(
            thread_id=thread.id,
            role="nahida",
            mode="普通",
            model="flash",
            user_message="archive this",
            assistant_message="archived",
            status="completed",
        )
    )
    client = TestClient(app)

    response = client.post(f"/sessions/{thread.id}/archive")

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == thread.id
    assert data["kind"] == "archived"
    assert data["archived"] is True
    assert Path(data["path"]).is_file()


def test_archive_current_session_file_after_restart(runtime_test_context):
    current_dir = runtime_test_context.current_dir
    session_dir = runtime_test_context.archive_dir
    current_dir.mkdir()
    session_dir.mkdir()
    current_file = current_dir / "restartme.md"
    current_file.write_text("User: hello\nAgent: hi\n", encoding="utf-8")
    client = TestClient(app)

    response = client.post("/sessions/restartme/archive")

    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "archived"
    assert Path(data["path"]).is_file()
    assert not current_file.exists()


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
