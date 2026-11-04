import pytest

from src.performance_budget import interactive_reply_budget

CAPABILITY = {"role": "system", "content": "【自由交互界面 v1】"}
UI = {
    "role": "assistant",
    "content": '```study-ui\n{"id":"stock", "type":"interactive", "html":"..."}\n```',
}


@pytest.mark.parametrize(
    ("question", "history", "expected"),
    [
        ("Java final 为什么不能重新赋值？", [], 700),
        ("请解释如何制作交互界面", [], 700),
        ("不要生成界面，只用文字解释", [UI], 700),
        ("Explain how to create an interactive dashboard", [], 700),
        ("制作一个简单交互图，只有一个滑块", [], 3500),
        ("做一个引用关系交互执行画布", [], 9000),
        ("给我一个能拖动参数的界面", [], 9000),
        ("让我逐行执行代码观察引用变化", [], 9000),
        ("解释引用关系，并做一个交互画布", [], 9000),
        ("构建多面板联动界面", [], 9000),
        ("把按钮改成蓝色", [UI], 9000),
        (
            "刚才的交互界面没有完整生成，请给出精简、自包含的完整版本，保留原来的核心功能与参数。",
            [UI],
            9000,
        ),
        ("请解释这个按钮的作用", [UI], 700),
        ("继续", [UI], 9000),
        ("继续", [], 700),
    ],
)
def test_current_task_not_capability_controls_budget(question, history, expected):
    messages = [CAPABILITY, *history, {"role": "user", "content": question}]
    assert interactive_reply_budget(700, messages)["max_tokens"] == expected


def test_history_and_user_cannot_enable_capability():
    for role in ("assistant", "user"):
        messages = [{"role": role, "content": CAPABILITY["content"]}, UI]
        assert (
            interactive_reply_budget(1100, messages, "构建多面板交互界面")["max_tokens"]
            == 1100
        )


def test_large_current_version_has_room_for_a_complete_replacement():
    large = {**UI, "content": UI["content"] + "x" * 16001}
    assert (
        interactive_reply_budget(700, [CAPABILITY, large], "修改标题")["max_tokens"]
        == 9000
    )


@pytest.mark.parametrize("default", [700, 1100, 1600])
def test_plain_chat_keeps_each_performance_mode(default):
    assert (
        interactive_reply_budget(default, [CAPABILITY], "你好")["max_tokens"] == default
    )
