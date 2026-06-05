from src.wechat_service import RuntimeContext, run_news_round
from src.news.audit import NewsAuditArtifact


def test_run_news_round_returns_result_and_updates_session(monkeypatch):
    from src import wechat_service

    progress_calls = []
    writes = []
    session_marks = []
    audit_calls = []

    monkeypatch.setattr(
        wechat_service,
        "fetch_news_items",
        lambda **kwargs: [
            {"title": "A", "source": "S1"},
            {"title": "B", "source": "S2"},
            {"title": "C", "source": "S3"},
        ],
    )
    monkeypatch.setattr(
        wechat_service,
        "enrich_news_items_with_article_text",
        lambda items, **kwargs: [{**item, "article_status": "正文已读"} for item in items],
    )
    monkeypatch.setattr(wechat_service, "generate_news_digest", lambda *args, **kwargs: "digest")
    monkeypatch.setattr(
        wechat_service,
        "generate_wechat_news_discussion",
        lambda *args, **kwargs: "discussion",
    )
    monkeypatch.setattr(
        wechat_service,
        "format_news_source_block",
        lambda query_text, news_items: f"source:{query_text}:{len(news_items)}",
    )
    monkeypatch.setattr(
        wechat_service,
        "append_system_group_note",
        lambda content: writes.append(("note", content)),
    )
    monkeypatch.setattr(
        wechat_service,
        "append_interactive_group_reply",
        lambda content: writes.append(("reply", content)),
    )
    monkeypatch.setattr(wechat_service, "read_wechat_group", lambda: "group content")
    monkeypatch.setattr(
        wechat_service,
        "set_wechat_interactive",
        lambda session_id, status: session_marks.append((session_id, status)),
    )
    monkeypatch.setattr(
        wechat_service,
        "save_news_audit",
        lambda **kwargs: audit_calls.append(kwargs)
        or NewsAuditArtifact("run1", "logs/news_audit/run1.md", "logs/news_audit/run1.json"),
    )
    monkeypatch.setattr(wechat_service, "get_last_feed_warnings", lambda: [])

    result = run_news_round(
        query_text="OpenAI latest",
        read_articles=True,
        runtime_context=RuntimeContext(
            performance_mode="standard",
            selected_model="flash",
            interaction_mode="warm",
            session_id="sess123",
            progress=progress_calls.append,
        ),
    )

    assert result.query_text == "OpenAI latest"
    assert result.digest == "digest"
    assert result.discussion == "discussion"
    assert result.group_content == "group content"
    assert result.source_block == "source:OpenAI latest:3"
    assert result.article_coverage == {
        "total": 3,
        "with_text": 3,
        "without_text": 0,
        "title_only": 0,
        "unresolved_transit": 0,
        "not_selected": 0,
        "failed_fetch": 0,
    }
    assert result.warnings == []
    assert result.audit_markdown_path == "logs/news_audit/run1.md"
    assert result.audit_json_path == "logs/news_audit/run1.json"
    assert audit_calls[0]["query_text"] == "OpenAI latest"
    assert audit_calls[0]["article_coverage"]["with_text"] == 3
    assert result.elapsed_ms >= 0
    assert writes == [
        ("note", "source:OpenAI latest:3"),
        ("reply", "discussion"),
    ]
    assert session_marks == [("sess123", "news_round")]
    assert progress_calls == [
        "正在搜索：OpenAI latest",
        "正在尝试读取新闻正文...",
        "正在整理搜索摘要...",
        "正在生成群聊讨论...",
        "正在写入群聊...",
    ]


def test_run_news_round_skips_article_read_when_disabled(monkeypatch):
    from src import wechat_service

    monkeypatch.setattr(
        wechat_service,
        "fetch_news_items",
        lambda **kwargs: [
            {"title": "A"},
            {"title": "B"},
            {"title": "C"},
        ],
    )
    monkeypatch.setattr(wechat_service, "generate_news_digest", lambda *args, **kwargs: "digest")
    monkeypatch.setattr(
        wechat_service,
        "generate_wechat_news_discussion",
        lambda *args, **kwargs: "discussion",
    )
    monkeypatch.setattr(wechat_service, "format_news_source_block", lambda *args, **kwargs: "note")
    monkeypatch.setattr(wechat_service, "append_system_group_note", lambda content: None)
    monkeypatch.setattr(wechat_service, "append_interactive_group_reply", lambda content: None)
    monkeypatch.setattr(wechat_service, "read_wechat_group", lambda: "group")
    monkeypatch.setattr(
        wechat_service,
        "save_news_audit",
        lambda **kwargs: NewsAuditArtifact("run2", "audit.md", "audit.json"),
    )
    monkeypatch.setattr(wechat_service, "get_last_feed_warnings", lambda: [])

    def _should_not_run(*args, **kwargs):
        raise AssertionError("article enrichment should be skipped")

    monkeypatch.setattr(wechat_service, "enrich_news_items_with_article_text", _should_not_run)

    result = run_news_round(
        query_text="Godot 4.6",
        read_articles=False,
        runtime_context=RuntimeContext(
            performance_mode="fast",
            selected_model="auto",
            interaction_mode="standard",
        ),
    )

    assert result.news_items == [
        {"title": "A"},
        {"title": "B"},
        {"title": "C"},
    ]
    assert result.source_block == "note"
    assert result.article_coverage["total"] == 3
    assert result.article_coverage["with_text"] == 0
    assert result.elapsed_ms >= 0
    assert any("0/3" in w for w in result.warnings)


def test_run_news_round_emits_task_events(monkeypatch):
    from src import wechat_service

    events = []

    monkeypatch.setattr(
        wechat_service,
        "fetch_news_items",
        lambda **kwargs: [
            {"title": "A"},
            {"title": "B"},
            {"title": "C"},
        ],
    )
    monkeypatch.setattr(wechat_service, "generate_news_digest", lambda *args, **kwargs: "digest")
    monkeypatch.setattr(
        wechat_service,
        "generate_wechat_news_discussion",
        lambda *args, **kwargs: "discussion",
    )
    monkeypatch.setattr(wechat_service, "format_news_source_block", lambda *args, **kwargs: "")
    monkeypatch.setattr(wechat_service, "append_interactive_group_reply", lambda content: None)
    monkeypatch.setattr(wechat_service, "read_wechat_group", lambda: "group")
    monkeypatch.setattr(wechat_service, "update_wechat_join_state", lambda **kwargs: None)
    monkeypatch.setattr(
        wechat_service,
        "save_news_audit",
        lambda **kwargs: NewsAuditArtifact("run3", "audit.md", "audit.json"),
    )
    monkeypatch.setattr(wechat_service, "get_last_feed_warnings", lambda: [])

    run_news_round(
        query_text="events",
        read_articles=False,
        runtime_context=RuntimeContext(
            performance_mode="standard",
            selected_model="flash",
            interaction_mode="standard",
            event_callback=events.append,
        ),
    )

    event_types = [event.event_type for event in events]
    assert event_types[0] == "started"
    assert "progress" in event_types
    assert ("item_completed", "search") in [
        (event.event_type, event.message) for event in events
    ]
    assert ("item_completed", "audit") in [
        (event.event_type, event.message) for event in events
    ]
    assert event_types[-1] == "completed"


def test_run_news_round_safe_mode_skips_article_network_read(monkeypatch):
    from src import wechat_service

    events = []

    monkeypatch.setattr(
        wechat_service,
        "fetch_news_items",
        lambda **kwargs: [
            {"title": "A"},
            {"title": "B"},
            {"title": "C"},
        ],
    )
    monkeypatch.setattr(wechat_service, "generate_news_digest", lambda *args, **kwargs: "digest")
    monkeypatch.setattr(
        wechat_service,
        "generate_wechat_news_discussion",
        lambda *args, **kwargs: "discussion",
    )
    monkeypatch.setattr(wechat_service, "format_news_source_block", lambda *args, **kwargs: "")
    monkeypatch.setattr(wechat_service, "append_interactive_group_reply", lambda content: None)
    monkeypatch.setattr(wechat_service, "read_wechat_group", lambda: "group")
    monkeypatch.setattr(wechat_service, "update_wechat_join_state", lambda **kwargs: None)
    monkeypatch.setattr(
        wechat_service,
        "save_news_audit",
        lambda **kwargs: NewsAuditArtifact("run4", "audit.md", "audit.json"),
    )
    monkeypatch.setattr(wechat_service, "get_last_feed_warnings", lambda: [])

    def _should_not_run(*args, **kwargs):
        raise AssertionError("safe_mode should skip article network reads")

    monkeypatch.setattr(wechat_service, "enrich_news_items_with_article_text", _should_not_run)

    result = run_news_round(
        query_text="safe",
        read_articles=True,
        runtime_context=RuntimeContext(
            performance_mode="standard",
            selected_model="flash",
            interaction_mode="standard",
            safe_mode=True,
            event_callback=events.append,
        ),
    )

    assert any("safe_mode" in warning for warning in result.warnings)
    assert ("item_completed", "enrich_skipped") in [
        (event.event_type, event.message) for event in events
    ]
