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
