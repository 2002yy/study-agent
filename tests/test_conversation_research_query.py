from __future__ import annotations

import pytest

from src.application.chat_service import _tool_context
from src.web.conversation_query import conversation_search_query, research_query_lead
from src.web.query_normalizer import normalize_web_query


def test_real_opus_followups_preserve_topic_beyond_recent_six_messages():
    history = [{"role": "user", "content": "请联网研究：opus5.5"}]
    for text in [
        "是最新的a÷模型。你联网没有找到内容吗？不太可能吧",
        "claude啊？你不知道吗？",
        "？意思刚刚你没有搜？",
        "快去",
    ]:
        history.append({"role": "assistant", "content": "Research query lead: 快手"})
        query = conversation_search_query(text, _tool_context(history))
        assert "opus5.5" in query.casefold()
        assert query != "快去"
        history.append({"role": "user", "content": text})
    assert "claude" in query.casefold()
    assert "快手" not in query


@pytest.mark.parametrize(
    "text", ["请联网研究：Python3.14", "另外查一下Java", "Python啊？", "opus6.5啊？",
             "刚刚发布的豆包模型怎么样？", "刚才看到的赵翠是谁？"]
)
def test_new_subject_is_not_replaced_by_old_research(text):
    assert (
        conversation_search_query(text, "Research query lead: opus5.5")
        == normalize_web_query(text).canonical_query
    )


def test_history_lead_only_uses_user_messages_and_clears_after_new_subject():
    assert (
        research_query_lead([{"role": "assistant", "content": "请联网研究：快手"}])
        == ""
    )
    history = [
        {"role": "user", "content": "请联网研究：opus5.5"},
        {"role": "user", "content": "如何写Python代码"},
    ]
    assert "opus" not in research_query_lead(history)


def test_resume_without_authorized_history_does_not_search_literal_command():
    assert conversation_search_query("快去", "") == ""
    assert (
        conversation_search_query("快去", "assistant: Research query lead: 快手") == ""
    )


def test_research_directive_is_removed_before_search():
    assert normalize_web_query("请联网研究：opus5.5").canonical_query == "opus5.5"


@pytest.mark.parametrize(
    "initial", ["opus5.5", "Research opus5.5", "Search for opus5.5"]
)
def test_lookup_followup_does_not_require_chinese_research_prefix(initial):
    lead = _tool_context([{"role": "user", "content": initial}])
    assert "opus5.5" in conversation_search_query("快去", lead).casefold()


@pytest.mark.parametrize("text", [
    "直接去。不要一次失败就返回", "再查查", "继续查", "再搜一下", "retry",
])
def test_retry_controls_preserve_the_whole_original_question(text):
    original = "联网研究：opus5.5是什么？性能如何？对比？"
    history = [{"role": "user", "content": original}]
    for control in ["直接去。不要一次失败就返回", "再查查", text]:
        assert conversation_search_query(control, _tool_context(history)) == (
            "opus5.5是什么？性能如何？对比？"
        )
        history.extend([
            {"role": "assistant", "content": "Read an unrelated dictionary."},
            {"role": "user", "content": control},
        ])


@pytest.mark.parametrize("text", ["直接去。不要一次失败就返回", "再查查"])
def test_retry_control_without_history_never_becomes_a_dictionary_query(text):
    assert conversation_search_query(text, "") == ""


@pytest.mark.parametrize("text", ["赵翠", "再查查Python", "直接查Python", "再查查是什么意思"])
def test_new_subject_or_command_definition_is_not_inherited(text):
    assert conversation_search_query(text, "Research query lead: opus5.5") == (
        normalize_web_query(text).canonical_query
    )
