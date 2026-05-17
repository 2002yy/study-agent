"""Test performance budget module — verify ordering and fallback."""
from __future__ import annotations

from src.performance_budget import (
    chat_max_tokens,
    news_digest_max_tokens,
    news_discussion_max_tokens,
    wechat_history_lines,
    wechat_opening_max_tokens,
    wechat_reply_max_tokens,
)


def _assert_strictly_increasing(values: list[int]):
    for a, b in zip(values, values[1:]):
        assert a < b, f"Expected {a} < {b}"


class TestChatMaxTokens:
    def test_fast_lt_standard_lt_deep(self):
        _assert_strictly_increasing([
            chat_max_tokens("fast"),
            chat_max_tokens("standard"),
            chat_max_tokens("deep"),
        ])

    def test_none_falls_back_to_standard(self):
        assert chat_max_tokens(None) == chat_max_tokens("standard")

    def test_unknown_mode_falls_back_to_standard(self):
        assert chat_max_tokens("unknown") == chat_max_tokens("standard")

    def test_values_are_positive(self):
        for mode in ("fast", "standard", "deep"):
            assert chat_max_tokens(mode) > 0


class TestWechatHistoryLines:
    def test_fast_lt_standard_lt_deep(self):
        _assert_strictly_increasing([
            wechat_history_lines("fast"),
            wechat_history_lines("standard"),
            wechat_history_lines("deep"),
        ])

    def test_unknown_falls_back(self):
        assert wechat_history_lines(None) == wechat_history_lines("standard")

    def test_values_are_positive(self):
        for mode in ("fast", "standard", "deep"):
            assert wechat_history_lines(mode) > 0


class TestWechatReplyMaxTokens:
    def test_fast_lt_standard_lt_deep(self):
        _assert_strictly_increasing([
            wechat_reply_max_tokens("fast"),
            wechat_reply_max_tokens("standard"),
            wechat_reply_max_tokens("deep"),
        ])

    def test_unknown_falls_back(self):
        assert wechat_reply_max_tokens(None) == wechat_reply_max_tokens("standard")


class TestWechatOpeningMaxTokens:
    def test_fast_lt_standard_lt_deep(self):
        _assert_strictly_increasing([
            wechat_opening_max_tokens("fast"),
            wechat_opening_max_tokens("standard"),
            wechat_opening_max_tokens("deep"),
        ])

    def test_unknown_falls_back(self):
        assert wechat_opening_max_tokens(None) == wechat_opening_max_tokens("standard")


class TestNewsDigestMaxTokens:
    def test_fast_lt_standard_lt_deep(self):
        _assert_strictly_increasing([
            news_digest_max_tokens("fast"),
            news_digest_max_tokens("standard"),
            news_digest_max_tokens("deep"),
        ])

    def test_unknown_falls_back(self):
        assert news_digest_max_tokens(None) == news_digest_max_tokens("standard")


class TestNewsDiscussionMaxTokens:
    def test_fast_lt_standard_lt_deep(self):
        _assert_strictly_increasing([
            news_discussion_max_tokens("fast"),
            news_discussion_max_tokens("standard"),
            news_discussion_max_tokens("deep"),
        ])

    def test_unknown_falls_back(self):
        assert news_discussion_max_tokens(None) == news_discussion_max_tokens("standard")
