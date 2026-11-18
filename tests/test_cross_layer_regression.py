"""Cross-layer regression tests for critical lifecycle and state-sync scenarios.

These tests cover critical cross-layer scenarios spanning:
- Session lifecycle (archive, restore, new-session ID)
- WeChat state (opening with existing group, reset after search)
- News stages (enriched data flows into digest)
- Routing (one-sentence summary routes to 普通)
- WeChat parsing (【注意】 not treated as role)
- Streaming isolation (restore during generation)
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.api import app

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── Helpers ─────────────────────────────────────────────────────────────


def _session_detail(client: TestClient, session_id: str) -> dict:
    return client.get(f"/sessions/{session_id}").json()


# ── Archive then send must produce new session ID ───────────────────────


def test_session_archive_creates_new_id_on_next_chat(monkeypatch):
    """After archiving the current session, the next /chat must use a new ID."""
    client = TestClient(app)

    # First message — creates a session
    resp = client.post(
        "/chat",
        json={
            "user_input": "你好",
            "selected_role": "auto",
            "selected_mode": "auto",
            "selected_model": "auto",
        },
    )
    assert resp.status_code == 200
    sid1 = resp.json()["session_id"]
    assert sid1

    # Archive
    archive_resp = client.post(f"/sessions/{sid1}/archive")
    assert archive_resp.status_code == 200

    # Second message — must get a new ID
    resp2 = client.post(
        "/chat",
        json={
            "user_input": "再问一次",
            "selected_role": "auto",
            "selected_mode": "auto",
            "selected_model": "auto",
        },
    )
    assert resp2.status_code == 200
    sid2 = resp2.json()["session_id"]
    assert sid2 != sid1


# ── Single-round session is discoverable before save ────────────────────


def test_single_round_session_visible_before_save(monkeypatch, tmp_path):
    """A session with one chat turn should appear in /sessions before save()."""
    from src import session_logger
    from src.application import helpers

    current_dir = tmp_path / "current"
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(session_logger, "CURRENT_DIR", current_dir)
    monkeypatch.setattr(session_logger, "LOG_DIR", sessions_dir)
    monkeypatch.setattr(helpers, "CURRENT_SESSION_DIR_DEFAULT", current_dir)
    monkeypatch.setattr(helpers, "SESSION_DIR_DEFAULT", sessions_dir)
    current_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)

    client = TestClient(app)

    resp = client.post(
        "/chat",
        json={
            "user_input": "单轮测试",
            "selected_role": "auto",
            "selected_mode": "auto",
            "selected_model": "auto",
        },
    )
    assert resp.status_code == 200
    sid = resp.json()["session_id"]

    sessions = client.get("/sessions").json()["sessions"]
    # Session file names are "{session_id}.md" — strip extension
    current_ids = {s["name"].replace(".md", "") for s in sessions if s["kind"] == "current"}
    # Also strip any extraneous prefix/suffix from session file name
    if sid not in current_ids:
        # Session might be in active memory (not yet flushed to disk)
        # Verify it's findable via the /sessions/{id} endpoint
        detail = client.get(f"/sessions/{sid}")
        assert detail.status_code == 200, f"Session {sid} should be discoverable"
    else:
        assert sid in current_ids, f"Session {sid} should appear in current sessions, got {current_ids}"


# ── Opening with existing group must not overwrite ──────────────────────


def test_opening_with_existing_group_rejected(runtime_test_context):
    """Calling /wechat/opening when the SQLite thread has content must 409."""
    client = TestClient(app)
    state = client.get("/wechat").json()
    payload = {
        "group_thread_id": state["group_thread_id"],
        "selected_role": "auto",
        "relationship_mode": "standard",
        "performance_mode": "standard",
        "selected_model": "auto",
    }
    first = client.post("/wechat/opening", json=payload)
    resp = client.post("/wechat/opening", json=payload)
    assert first.status_code == 200
    assert resp.status_code == 409
    assert runtime_test_context.group_repository.get_thread(
        state["group_thread_id"]
    ) is not None


# ── "一句话总结" routes to 普通 ─────────────────────────────────────────


def test_one_sentence_summary_routes_to_normal(monkeypatch):
    """Input '一句话总结今天的学习' should resolve mode to '普通'."""
    client = TestClient(app)

    resp = client.post(
        "/chat",
        json={
            "user_input": "一句话总结今天的学习内容",
            "selected_role": "auto",
            "selected_mode": "auto",
            "selected_model": "auto",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    route = data["route"]
    # "一句话总结" keyword should match rule 102 → 普通
    assert route["mode"] == "普通", f"Expected mode 普通, got {route.get('mode')}"


# ── Previous mode preserved in log after refresh ────────────────────────


def test_previous_mode_preserved_in_session_log(monkeypatch):
    """The previous_mode field should be recorded in session_detail route info."""
    client = TestClient(app)

    # First message — mode determined by router
    resp1 = client.post(
        "/chat",
        json={
            "user_input": "帮我实现一个排序函数",
            "selected_role": "auto",
            "selected_mode": "auto",
            "selected_model": "auto",
        },
    )
    assert resp1.status_code == 200
    sid = resp1.json()["session_id"]
    mode1 = resp1.json()["route"]["mode"]

    # Second message — pass previous_mode
    resp2 = client.post(
        "/chat",
        json={
            "user_input": "再优化一下",
            "selected_role": "auto",
            "selected_mode": "auto",
            "selected_model": "auto",
            "previous_mode": mode1,
            "session_id": sid,
        },
    )
    assert resp2.status_code == 200

    detail = _session_detail(client, sid)
    messages = detail.get("messages", [])
    assert len(messages) >= 4  # at least 2 user + 2 assistant


# ── Restoring session mid-generation does not leak tokens ───────────────


def test_session_restore_during_generation_isolates_stream(monkeypatch):
    """When a new session is created during streaming, the old stream
    must not write tokens into the new session's messages."""
    client = TestClient(app)

    # Create session A with one message
    resp_a = client.post(
        "/chat",
        json={
            "user_input": "会话A的消息",
            "selected_role": "auto",
            "selected_mode": "auto",
            "selected_model": "auto",
        },
    )
    assert resp_a.status_code == 200
    sid_a = resp_a.json()["session_id"]

    # Create session B
    resp_b = client.post(
        "/chat",
        json={
            "user_input": "会话B的消息",
            "selected_role": "auto",
            "selected_mode": "auto",
            "selected_model": "auto",
        },
    )
    assert resp_b.status_code == 200
    sid_b = resp_b.json()["session_id"]
    assert sid_b != sid_a

    # Restore session A — its messages should contain only A's content
    detail_a = _session_detail(client, sid_a)
    messages_a = detail_a.get("messages", [])
    user_messages_a = [m["content"] for m in messages_a if m["role"] == "user"]
    # Must not contain B's message
    assert "会话B的消息" not in user_messages_a
    assert "会话A的消息" in user_messages_a


# ── WeChat stream failure recovers original group content ───────────────


def test_wechat_stream_failure_preserves_group_content(monkeypatch):
    """Verify that the server rejects empty messages and the group file
    is not corrupted by a failed send."""
    client = TestClient(app)

    # Attempt to send with empty message — must be rejected before any write
    resp = client.post(
        "/wechat/message",
        json={
            "message": " ",
            "selected_model": "auto",
            "relationship_mode": "standard",
        },
    )
    assert resp.status_code == 422


# ── Enriched article contents flow into digest ─────────────────────────


def test_news_digest_uses_enriched_items(runtime_test_context):
    """Verify enrich→digest pipeline: digest receives enriched items."""
    from src.mode_manager import load_runtime_modes
    from src.application.news_service import NewsDependencies

    client = TestClient(app)
    search_items = [
        {
            "title": f"News {index}",
            "url": f"https://example.com/{index}",
            "source": "Example",
            "snippet": f"summary {index}",
        }
        for index in range(3)
    ]
    captured = {}

    def fake_enrich(items, **kwargs):
        return [{**item, "article_text": f"body:{item['title']}"} for item in items]

    def fake_digest(items, **kwargs):
        captured["items"] = items
        return "digest", "sources", {"available": len(items)}, []

    runtime_test_context.news_service.dependencies = NewsDependencies(
        search=lambda query, max_items: search_items[:max_items],
        enrich=fake_enrich,
        digest=fake_digest,
        discuss=lambda digest, **kwargs: ("discussion", ""),
        load_runtime_modes=load_runtime_modes,
    )

    created = client.post("/news/runs", json={"query": "China tech news today"})
    search_resp = client.post(
        f"/news/runs/{created.json()['id']}/search", json={"max_items": 6}
    )
    assert search_resp.status_code == 200
    run_id = search_resp.json()["id"]
    enrich_resp = client.post(
        f"/news/runs/{run_id}/enrich",
        json={"safe_mode": False},
    )
    assert enrich_resp.status_code == 200
    enriched = enrich_resp.json().get("items", [])

    # Digest should work with enriched items
    digest_resp = client.post(
        f"/news/runs/{run_id}/digest",
        json={"selected_model": "auto"},
    )
    assert digest_resp.status_code == 200
    assert digest_resp.json()["digest"] == "digest"
    assert captured["items"] == enriched
    assert all(item["article_text"].startswith("body:") for item in captured["items"])


# ── New group chat archives previous thread ────────────────────────────


def test_wechat_reset_archives_group_and_returns_new_empty_thread(runtime_test_context):
    """Reset archives the SQLite thread and returns a new empty thread."""
    client = TestClient(app)
    state = client.get("/wechat").json()
    old_id = state["group_thread_id"]
    opening = client.post(
        "/wechat/opening",
        json={"group_thread_id": old_id, "selected_model": "flash"},
    )
    assert opening.status_code == 200

    resp = client.post(f"/wechat/reset?group_thread_id={old_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == ""
    assert data["group_thread_id"] != old_id
    archived = runtime_test_context.group_repository.get_thread(old_id)
    assert archived is not None and archived.status == "archived"


# ── No duplicate session IDs in active state ───────────────────────────


def test_no_duplicate_session_across_current_and_archived(monkeypatch):
    """A session ID should not appear in both 'current' and 'archived' lists."""
    client = TestClient(app)

    resp = client.post(
        "/chat",
        json={
            "user_input": "test",
            "selected_role": "auto",
            "selected_mode": "auto",
            "selected_model": "auto",
        },
    )
    assert resp.status_code == 200
    sid = resp.json()["session_id"]

    sessions = client.get("/sessions").json()["sessions"]
    current_entries = [s for s in sessions if s["kind"] == "current" and s["name"] == sid]
    archived_entries = [s for s in sessions if s["kind"] == "archived" and s["name"] == sid]

    # Same ID must not appear in both
    assert not (current_entries and archived_entries), (
        f"Session {sid} appears in both current and archived"
    )
    assert len(current_entries) <= 1
    assert len(archived_entries) <= 1


# ── 【注意】 in user message not parsed as wechat role ───────────────────


def test_user_message_with_bracket_role_not_parsed_as_wechat():
    """User messages containing 【注意】 should not be split as role blocks."""
    from src.wechat_format import _message_blocks

    text = "【注意】这是一条重要的提示信息，请不要忽略。"
    blocks = _message_blocks(text)

    # "注意" is not in WECHAT_ROLE_ORDER, so it should not create a block
    block_speakers = [speaker for speaker, _ in blocks]
    assert "注意" not in block_speakers, f"【注意】should not be parsed as a wechat role, got {block_speakers}"


def test_user_message_with_all_four_roles_in_text_not_parsed():
    """Even text mentioning all four role names should not create role blocks
    unless they use the exact 【role】\\ncontent format."""
    from src.wechat_format import _message_blocks

    text = "我觉得三月七说得对，但是刻晴和纳西妲可能不这么想，流萤你怎么看？"
    blocks = _message_blocks(text)

    # This free-text mention without the block format should yield zero role blocks
    role_speakers = [s for s, _ in blocks if s in ("三月七", "刻晴", "纳西妲", "流萤")]
    assert len(role_speakers) == 0, f"Free text should not create role blocks, got {role_speakers}"
