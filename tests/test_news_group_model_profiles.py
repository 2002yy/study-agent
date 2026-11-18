"""News and opening calls honor model choice independently of legacy speed."""

import pytest

from src import wechat_generator
from src.news import digest


@pytest.mark.parametrize(
    "selected_model, expected",
    [
        ("flash", "flash"),
        ("pro", "pro"),
        ("auto", "flash"),
    ],
)
@pytest.mark.parametrize("performance_mode", ["fast", "standard", "deep"])
@pytest.mark.parametrize("generation", ["digest", "discussion", "opening"])
def test_generation_model_is_independent_of_legacy_performance(
    monkeypatch, selected_model, expected, performance_mode, generation
):
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append(kwargs)
        return "【三月七】\n一\n【刻晴】\n二\n【纳西妲】\n三\n【流萤】\n四"

    owner = digest if generation == "digest" else wechat_generator
    monkeypatch.setattr(owner, "chat", fake_chat)
    kwargs = {"selected_model": selected_model, "performance_mode": performance_mode}
    if generation == "digest":
        result = digest.generate_news_digest(
            [{"title": "A local test item", "link": "https://example.com/item"}],
            **kwargs,
        )
    elif generation == "discussion":
        result = wechat_generator.generate_wechat_news_discussion(
            "A local digest", **kwargs
        )
    else:
        result = wechat_generator.generate_wechat_opening(**kwargs)

    assert result
    assert len(calls) == 1
    assert calls[0]["model_profile"] == expected


def test_news_discussion_keeps_learning_memory_without_legacy_session_log(monkeypatch):
    prompts = []

    def fake_chat(messages, **kwargs):
        prompts.append(messages[0]["content"])
        return "【三月七】\n一\n【刻晴】\n二\n【纳西妲】\n三\n【流萤】\n四"

    monkeypatch.setattr(wechat_generator, "chat", fake_chat)
    wechat_generator.generate_wechat_news_discussion(
        "今日新闻",
        session_id="session-without-old-logger",
        memory_bundle={"current_focus.md": "Java 引用与对象共享"},
    )

    assert len(prompts) == 1
    assert "[学习记忆导入]" in prompts[0]
    assert "Java 引用与对象共享" in prompts[0]
    assert "[单聊近期对话]" not in prompts[0]
