from types import SimpleNamespace

from src.mode_manager import (
    RuntimeModes,
    build_runtime_profile,
    is_memory_write_allowed,
    run_with_confirm_write,
)
from src.context_builder import build_messages, build_system_prompt
from src.router import RoutingConfig, route_request
from src.ui.sidebar import _switch_to_wechat_entry
from src.ui.wechat_panel import _apply_mark_wechat_read, _apply_new_wechat_group


def test_route_request_maps_code_error_to_keqing_project_pro(monkeypatch):
    from src import router

    monkeypatch.setattr(
        router,
        "load_routing_config",
        lambda: RoutingConfig(
            rules=[
                (["改代码", "报错"], "keqing", "项目", "pro", "task", 90),
            ],
            default_role="nahida",
            default_mode="普通",
            default_model="flash",
            default_reason="default",
        ),
    )

    result = route_request(
        "帮我改代码报错",
        "auto",
        "auto",
        "auto",
        RuntimeModes(performance_mode="standard"),
    )

    assert result["role"] == "keqing"
    assert result["mode"] == "项目"
    assert result["model_profile"] == "pro"


def test_route_request_maps_mechanism_question_to_nahida(monkeypatch):
    from src import router

    monkeypatch.setattr(
        router,
        "load_routing_config",
        lambda: RoutingConfig(
            rules=[
                (["底层", "机制"], "nahida", "概念地图", "pro", "mechanism", 100),
            ],
            default_role="march7",
            default_mode="普通",
            default_model="flash",
            default_reason="default",
        ),
    )

    result = route_request(
        "解释底层机制",
        "auto",
        "auto",
        "auto",
        RuntimeModes(performance_mode="standard"),
    )

    assert result["role"] == "nahida"
    assert result["mode"] == "概念地图"
    assert result["model_profile"] == "pro"


def test_fast_mode_does_not_trigger_llm_router(monkeypatch):
    from src import router

    monkeypatch.setattr(router, "_match", lambda *args, **kwargs: None)

    result = route_request(
        "totally unmatched prompt",
        "auto",
        "auto",
        "auto",
        RuntimeModes(performance_mode="fast", route_mode="hybrid"),
    )

    assert result["llm_router_used"] is False
    assert result["model_profile"] == "flash"


def test_llm_router_requests_json_mode(monkeypatch):
    from src import llm_router

    captured = {}

    def fake_chat(messages, **kwargs):
        captured["kwargs"] = kwargs
        return (
            '{"role":"nahida","mode":"普通","model_profile":"flash",'
            '"confidence":"medium","reason":"ok"}'
        )

    monkeypatch.setattr(llm_router, "chat", fake_chat)
    monkeypatch.setattr(llm_router, "record_llm_router_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(llm_router, "estimate_tokens", lambda text: 10)

    result = llm_router.route_by_llm("解释一下底层机制")

    assert result is not None
    assert captured["kwargs"]["task_name"] == "llm_router"
    assert captured["kwargs"]["temperature"] is None


def test_memory_write_permissions_respect_safe_and_locked():
    assert is_memory_write_allowed(
        RuntimeModes(memory_mode="confirm_write", safe_mode=False)
    ) is True
    assert is_memory_write_allowed(
        RuntimeModes(memory_mode="confirm_write", safe_mode=True)
    ) is False
    assert is_memory_write_allowed(
        RuntimeModes(memory_mode="locked", safe_mode=False)
    ) is False


def test_runtime_profile_centralizes_effective_permissions():
    profile = build_runtime_profile(
        RuntimeModes(
            performance_mode="fast",
            route_mode="hybrid",
            memory_mode="confirm_write",
            safe_mode=True,
        )
    )

    assert profile.memory_write_allowed is False
    assert profile.memory_write_reason == "safe_mode"
    assert profile.allow_llm_router is False
    assert profile.llm_router_reason == "fast_mode"
    assert profile.allow_article_network_read is False
    assert profile.article_network_read_reason == "safe_mode"
    assert profile.preferred_model == "flash"
    assert profile.context_mode == "fast"


def test_run_with_confirm_write_restores_original_mode(monkeypatch):
    from src import mode_manager

    writes = []

    monkeypatch.setattr(
        mode_manager,
        "load_runtime_modes",
        lambda: RuntimeModes(memory_mode="preview"),
    )
    monkeypatch.setattr(mode_manager, "set_memory_mode", lambda mode: writes.append(mode))

    result = run_with_confirm_write(lambda: "ok")

    assert result == "ok"
    assert writes == ["confirm_write", "preview"]


def test_switch_to_wechat_entry_updates_mode_and_notice(monkeypatch):
    from src.ui import sidebar

    writes = []
    runtime_modes = RuntimeModes(entry_mode="single")
    session_state = SimpleNamespace(wechat_messages=None, sidebar_notice="")

    monkeypatch.setattr(sidebar, "update_entry_mode", lambda mode: writes.append(mode))

    _switch_to_wechat_entry("unread block", runtime_modes, session_state)

    assert session_state.wechat_messages == "unread block"
    assert session_state.sidebar_notice == "已切换到微信群未读视图"
    assert runtime_modes.entry_mode == "wechat"
    assert writes == ["wechat"]


def test_apply_mark_wechat_read_keeps_group_visible(monkeypatch):
    from src.ui import wechat_panel

    calls = []
    session_state = SimpleNamespace(wechat_messages=None)

    monkeypatch.setattr(wechat_panel, "mark_wechat_read", lambda: calls.append("mark"))
    monkeypatch.setattr(
        wechat_panel,
        "set_wechat_unread_cleared",
        lambda session_id: calls.append(("cleared", session_id)),
    )
    monkeypatch.setattr(wechat_panel, "read_wechat_group", lambda: "group history")

    _apply_mark_wechat_read("sess1", session_state)

    assert calls == ["mark", ("cleared", "sess1")]
    assert session_state.wechat_messages == "group history"


def test_apply_new_wechat_group_clears_pending_input(monkeypatch):
    from src.ui import wechat_panel

    session_state = SimpleNamespace(
        wechat_messages="old",
        wechat_pending_input="hello",
        wechat_news_items=[{"title": "x"}],
        wechat_news_digest="digest",
    )
    reset_calls = []

    monkeypatch.setattr(wechat_panel, "reset_wechat_group", lambda: reset_calls.append(True))

    _apply_new_wechat_group(session_state)

    assert reset_calls == [True]
    assert session_state.wechat_messages is None
    assert session_state.wechat_pending_input is None
    assert session_state.wechat_news_items == []
    assert session_state.wechat_news_digest == ""


def test_build_messages_includes_rag_context_with_citations():
    messages = build_messages(
        user_input="Explain routing",
        role_prompt="You are a tutor.",
        mode="普通",
        memory_bundle={},
        rag_context="[1] notes (notes.md:L1-L2, score=3.000)\nRouting uses rules.",
    )

    system_prompt = messages[0]["content"]

    assert "[Retrieved local documents]" in system_prompt
    assert "Preserve citation numbers" in system_prompt
    assert "notes.md:L1-L2" in system_prompt


def test_build_messages_omits_empty_rag_context():
    messages = build_messages(
        user_input="Explain routing",
        role_prompt="You are a tutor.",
        mode="普通",
        memory_bundle={},
        rag_context="No relevant local documents retrieved.",
    )

    assert "[Retrieved local documents]" not in messages[0]["content"]


def test_single_chat_policy_and_conversation_instruction_override_role_limits():
    prompt = build_system_prompt(
        role_prompt="角色偏好：遇到项目问题倾向让刻晴收束。",
        mode="普通",
        memory_bundle={},
        scene="single",
        conversation_instruction="不要转交给其他角色，直接回答我的问题。",
    )

    assert "当前场景是单人对话" in prompt
    assert "角色分工只表示擅长领域和回答风格，不构成能力限制" in prompt
    assert "不得以“这不是我的职责”“请切换到其他角色”“请去找某角色”等理由拒绝" in prompt
    assert "[Conversation instruction]\n不要转交给其他角色，直接回答我的问题。" in prompt


def test_group_chat_policy_keeps_group_scene_separate():
    prompt = build_system_prompt(
        role_prompt="群聊角色资料",
        mode="普通",
        memory_bundle={},
        scene="group",
    )

    assert "当前场景是群聊" in prompt
    assert "开场、提炼、收束、收尾" in prompt
    assert "当前场景是单人对话" not in prompt
