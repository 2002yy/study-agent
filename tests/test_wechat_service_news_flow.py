"""Test the wechat_service news flow with state sync fix.

- run_discussion_stage must call update_wechat_join_state with correct args
- WeChat generator calls must pass max_tokens and task_name
"""
from __future__ import annotations


# ── run_discussion_stage ──────────────────────────────────────────────────


class TestRunDiscussionStage:
    def test_writes_discussion_and_syncs_join_state(self, monkeypatch):
        from src import wechat_service

        writes: list[str] = []
        join_state_calls: list[tuple] = []

        monkeypatch.setattr(
            wechat_service,
            "generate_wechat_news_discussion",
            lambda *args, **kwargs: "mock discussion text",
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
        monkeypatch.setattr(
            wechat_service,
            "update_wechat_join_state",
            lambda user_has_joined, first_reaction_done, mode: join_state_calls.append(
                (user_has_joined, first_reaction_done, mode)
            ),
        )
        monkeypatch.setattr(wechat_service, "read_wechat_group", lambda: "group content")

        discussion, group_content = wechat_service.run_discussion_stage(
            digest="test digest",
            interaction_mode="warm",
            performance_mode="standard",
            selected_model="flash",
            source_block="source block text",
        )

        # Verify output
        assert discussion == "mock discussion text"
        assert group_content == "group content"

        # Verify writes in order
        assert writes == [
            ("note", "source block text"),
            ("reply", "mock discussion text"),
        ]
        # Verify join state was synced with correct args
        assert join_state_calls == [
            (False, False, "interactive_group"),
        ]

    def test_writes_discussion_without_source_block(self, monkeypatch):
        from src import wechat_service

        writes: list[str] = []
        join_state_calls: list[tuple] = []

        monkeypatch.setattr(
            wechat_service,
            "generate_wechat_news_discussion",
            lambda *args, **kwargs: "discussion",
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
        monkeypatch.setattr(
            wechat_service,
            "update_wechat_join_state",
            lambda user_has_joined, first_reaction_done, mode: join_state_calls.append(
                (user_has_joined, first_reaction_done, mode)
            ),
        )
        monkeypatch.setattr(wechat_service, "read_wechat_group", lambda: "group")

        wechat_service.run_discussion_stage(
            digest="digest",
            interaction_mode="standard",
            performance_mode="fast",
            selected_model="auto",
            source_block="",
        )

        # Without source_block, no system note should be written
        assert writes == [("reply", "discussion")]
        # Join state should still be synced
        assert join_state_calls == [(False, False, "interactive_group")]


# ── wechat_generator budget parameter verification ───────────────────────


class TestWechatGeneratorBudget:
    def test_generate_wechat_news_discussion_passes_max_tokens_and_task_name(
        self, monkeypatch
    ):
        from src import wechat_generator

        call_kwargs: dict = {}

        def _mock_chat(*args, **kwargs):
            call_kwargs.update(kwargs)
            return "【三月七】\nok\n\n【刻晴】\nok\n\n【纳西妲】\nok\n\n【流萤】\nok"

        monkeypatch.setattr(wechat_generator, "chat", _mock_chat)

        result = wechat_generator.generate_wechat_news_discussion(
            news_digest="test digest",
            relationship_mode="standard",
            performance_mode="fast",
            selected_model="auto",
        )

        assert result
        assert call_kwargs.get("max_tokens") is not None
        assert call_kwargs.get("task_name") == "wechat_news_discussion"

    def test_generate_interactive_wechat_reply_stream_passes_max_tokens_and_task_name(
        self, monkeypatch
    ):
        from src import wechat_generator

        call_kwargs: dict = {}
        stream_result = iter(["hello"])

        def _mock_stream_chat(*args, **kwargs):
            call_kwargs.update(kwargs)
            return stream_result

        monkeypatch.setattr(wechat_generator, "stream_chat", _mock_stream_chat)
        monkeypatch.setattr(wechat_generator, "read_wechat_group", lambda: "【三月七】\nhi")
        monkeypatch.setattr(
            wechat_generator, "load_runtime_modes", lambda: type("Modes", (), {
                "performance_mode": "fast",
                "relationship_mode": "standard",
                "first_reaction_done": True,
            })()
        )

        stream, _is_first = wechat_generator.generate_interactive_wechat_reply_stream(
            user_text="hello",
            model_profile="flash",
            relationship_mode="standard",
        )

        # Exhaust the iterator so the generator runs
        list(stream)

        assert call_kwargs.get("max_tokens") is not None
        assert call_kwargs.get("task_name") == "wechat_interactive"

    def test_generate_news_digest_passes_max_tokens_and_task_name(self, monkeypatch):
        from src.news import digest as news_digest_module

        call_kwargs: dict = {}

        def _mock_chat(*args, **kwargs):
            call_kwargs.update(kwargs)
            return "【搜索结果摘要】\nno news"

        monkeypatch.setattr(news_digest_module, "chat", _mock_chat)

        result = news_digest_module.generate_news_digest(
            news_items=[{"title": "A", "source": "S", "published_at": "today"}],
            performance_mode="standard",
            selected_model="auto",
        )

        assert result
        assert call_kwargs.get("max_tokens") is not None
        assert call_kwargs.get("task_name") == "news_digest"

    def test_generate_wechat_opening_passes_max_tokens_and_task_name(
        self, monkeypatch
    ):
        from src import wechat_generator

        call_kwargs: dict = {}

        def _mock_chat(*args, **kwargs):
            call_kwargs.update(kwargs)
            return "【三月七】\nok\n\n【刻晴】\nok\n\n【纳西妲】\nok\n\n【流萤】\nok"

        monkeypatch.setattr(wechat_generator, "chat", _mock_chat)
        monkeypatch.setattr(wechat_generator, "load_role", lambda x: "")

        result = wechat_generator.generate_wechat_opening(
            role_hint="auto",
            relationship_mode="standard",
            performance_mode="fast",
            selected_model="auto",
        )

        assert result
        assert call_kwargs.get("max_tokens") is not None
        assert call_kwargs.get("task_name") == "wechat_opening"
