"""Test the news entry state machine fix:

- _should_render_news_phase_before_group detects wechat_news_phase
- _clear_wechat_news_state resets all news-related session state
"""
from __future__ import annotations

from src.ui.wechat_panel import (
    _clear_wechat_news_state,
    _should_render_news_phase_before_group,
)


class _FakeSessionState(dict):
    """dict subclass that also supports attribute access like st.session_state."""
    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name: str, value):
        self[name] = value

    def __delattr__(self, name: str):
        try:
            del self[name]
        except KeyError:
            raise AttributeError(name) from None


def _make_session(**overrides) -> _FakeSessionState:
    """Build a fake session_state-like object with news defaults."""
    ss = _FakeSessionState()
    for k, v in {
        "wechat_news_items": [],
        "wechat_news_digest": "",
        "wechat_news_phase": "",
        "wechat_news_query_text": "",
        "wechat_news_read_articles": True,
        "wechat_news_source_block": "",
        "wechat_news_coverage": {},
        "wechat_news_warnings": [],
        "wechat_news_elapsed_ms": 0,
    }.items():
        ss[k] = v
    for k, v in overrides.items():
        ss[k] = v
    return ss


# ── _should_render_news_phase_before_group ────────────────────────────────


class TestShouldRenderNewsPhaseBeforeGroup:
    def test_phase_searched_returns_true(self):
        ss = _make_session(wechat_news_phase="searched")
        assert _should_render_news_phase_before_group(ss) is True

    def test_phase_empty_returns_false(self):
        ss = _make_session(wechat_news_phase="")
        assert _should_render_news_phase_before_group(ss) is False

    def test_phase_none_returns_false(self):
        ss = _make_session()
        del ss.wechat_news_phase
        assert _should_render_news_phase_before_group(ss) is False

    def test_phase_other_string_returns_true(self):
        ss = _make_session(wechat_news_phase="digested")
        assert _should_render_news_phase_before_group(ss) is True

    def test_phase_discussed_returns_true(self):
        ss = _make_session(wechat_news_phase="discussed")
        assert _should_render_news_phase_before_group(ss) is True


# ── _clear_wechat_news_state ──────────────────────────────────────────────


class TestClearWechatNewsState:
    def test_clears_all_fields(self):
        ss = _make_session(
            wechat_news_items=[{"title": "A"}],
            wechat_news_digest="some digest",
            wechat_news_phase="searched",
            wechat_news_query_text="latest AI news",
            wechat_news_read_articles=False,
            wechat_news_source_block="source block",
            wechat_news_coverage={"total": 5},
            wechat_news_warnings=["warning"],
            wechat_news_elapsed_ms=1234,
        )

        _clear_wechat_news_state(ss)

        assert ss.wechat_news_items == []
        assert ss.wechat_news_digest == ""
        assert ss.wechat_news_phase == ""
        assert ss.wechat_news_query_text == ""
        assert ss.wechat_news_source_block == ""
        assert ss.wechat_news_coverage == {}
        assert ss.wechat_news_warnings == []
        assert ss.wechat_news_elapsed_ms == 0
        assert ss.wechat_news_read_articles is True

    def test_idempotent_on_already_clean(self):
        ss = _make_session()
        _clear_wechat_news_state(ss)

        assert ss.wechat_news_items == []
        assert ss.wechat_news_digest == ""
        assert ss.wechat_news_phase == ""
        assert ss.wechat_news_query_text == ""
        assert ss.wechat_news_read_articles is True
        assert ss.wechat_news_source_block == ""
        assert ss.wechat_news_coverage == {}
        assert ss.wechat_news_warnings == []
        assert ss.wechat_news_elapsed_ms == 0
