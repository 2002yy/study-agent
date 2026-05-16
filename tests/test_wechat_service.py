from src.wechat_service import RuntimeContext, run_news_round


def test_run_news_round_returns_result_and_updates_session(monkeypatch):
    from src import wechat_service

    progress_calls = []
    writes = []
    session_marks = []

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
