import pytest
from pathlib import Path
import time
from src.wechat import (
    _ARTICLE_CACHE,
    _article_fetch_priority,
    _clean_article_text,
    _decode_html_payload,
    _dedupe_and_trim_news_items,
    _extract_resolved_url_from_google_news_html,
    _extract_article_text,
    _fetch_query_news_items,
    _is_fetchable_article_url,
    _parse_news_pub_date,
    _news_article_coverage_summary,
    _title_matches_query,
    append_system_group_note,
    append_wechat_messages,
    enrich_news_items_with_article_text,
    fetch_article_text_with_method,
    format_news_source_block,
    read_wechat_unread,
    read_wechat_group,
    clear_wechat_unread,
    resolve_news_link,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GROUP = PROJECT_ROOT / "chat" / "wechat_group.md"
UNREAD = PROJECT_ROOT / "chat" / "wechat_unread.md"
STATE = PROJECT_ROOT / "chat" / "wechat_state.md"


@pytest.fixture(autouse=True)
def _save_restore():
    """备份原文件，测试结束后恢复"""
    gb = GROUP.read_text(encoding="utf-8") if GROUP.is_file() else ""
    ub = UNREAD.read_text(encoding="utf-8") if UNREAD.is_file() else ""
    sb = STATE.read_text(encoding="utf-8") if STATE.is_file() else ""
    yield
    GROUP.write_text(gb, encoding="utf-8")
    UNREAD.write_text(ub, encoding="utf-8")
    STATE.write_text(sb, encoding="utf-8")


def test_unread_has_metadata_header():
    append_wechat_messages("【三月七】\n测试\n\n【刻晴】\n测试")
    content = read_wechat_unread()
    assert "# 微信群未读消息" in content
    assert "生成时间:" in content
    assert "状态: unread" in content


def test_unread_has_four_roles():
    sample = "【三月七】\na\n\n【刻晴】\nb\n\n【纳西妲】\nc\n\n【流萤】\nd"
    append_wechat_messages(sample)
    content = read_wechat_unread()
    for role in ["【三月七】", "【刻晴】", "【纳西妲】", "【流萤】"]:
        assert role in content, f"缺失角色: {role}"


def test_unread_not_empty():
    append_wechat_messages("【流萤】\n测试内容")
    content = read_wechat_unread()
    assert len(content) > 0


def test_group_preserved_after_clear():
    append_wechat_messages("【流萤】\nunique_test_marker")
    clear_wechat_unread()
    after = GROUP.read_text(encoding="utf-8")
    assert "unique_test_marker" in after


def test_clean_article_text_drops_too_short_text():
    assert _clean_article_text("太短") == ""


def test_decode_html_payload_supports_declared_charset_and_fallback():
    gbk_payload = "中文内容".encode("gb18030")
    assert _decode_html_payload(gbk_payload, "text/html; charset=gbk") == "中文内容"
    assert _decode_html_payload(gbk_payload, "") == "中文内容"


def test_extract_resolved_url_from_google_news_html_prefers_external_url():
    html = """
    <html><head>
    <script>
    {"targetUrl":"https://example.com/articles/openai-audio"}
    </script>
    </head></html>
    """

    resolved = _extract_resolved_url_from_google_news_html(html)
    assert resolved == "https://example.com/articles/openai-audio"


def test_extract_article_text_falls_back_across_layers(monkeypatch):
    from src.news import article_extractor

    monkeypatch.setattr(
        article_extractor, "extract_article_text_with_trafilatura", lambda *args, **kwargs: ""
    )
    monkeypatch.setattr(
        article_extractor,
        "extract_article_text_with_readability",
        lambda *args, **kwargs: "readability text",
    )
    monkeypatch.setattr(
        article_extractor,
        "extract_article_text_with_fallback_parser",
        lambda *args, **kwargs: "fallback text",
    )

    text, method = _extract_article_text(
        "<html></html>", url="https://example.com/a", max_chars=5000
    )

    assert text == "readability text"
    assert method == "readability"


def test_parse_news_pub_date_includes_year_and_timestamp():
    published_at, published_ts = _parse_news_pub_date("Wed, 08 May 2024 07:51:00 GMT")

    assert published_at.startswith("2024-")
    assert len(published_at) == 16
    assert published_ts > 0


def test_enrich_news_items_falls_back_when_article_unavailable(monkeypatch):
    from src import wechat

    monkeypatch.setattr(wechat, "fetch_article_text", lambda *args, **kwargs: "")

    items = [{"title": "测试新闻", "link": "https://example.com/a"}]
    enriched = enrich_news_items_with_article_text(items)

    assert enriched[0]["article_excerpt"] == ""
    assert "正文不可用" in enriched[0]["article_status"]


def test_resolve_news_link_returns_original_for_non_google_url():
    url = "https://example.com/a"
    assert resolve_news_link(url) == url


def test_resolve_news_link_uses_final_redirect_url(monkeypatch):
    from src import wechat

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def geturl(self):
            return "https://publisher.example.com/article"

    monkeypatch.setattr(wechat, "urlopen", lambda *args, **kwargs: _FakeResponse())

    resolved = resolve_news_link("https://news.google.com/rss/articles/abc")
    assert resolved == "https://publisher.example.com/article"


def test_fetch_article_text_with_method_uses_cached_method():
    _ARTICLE_CACHE.clear()
    _ARTICLE_CACHE["https://example.com/a"] = (
        time.time(),
        "cached text",
        "readability",
    )

    text, method = fetch_article_text_with_method("https://example.com/a")

    assert text == "cached text"
    assert method == "readability"


def test_article_fetch_priority_prefers_openai_official_voice_news():
    low_score = _article_fetch_priority(
        {
            "title": "OpenAI 最新实时语音 API 更新",
            "source": "OpenAI",
            "resolved_link": "https://openai.com/index/realtime-audio",
        },
        query_text="OpenAI 语音 API",
    )
    high_score = _article_fetch_priority(
        {
            "title": "普通行业新闻",
            "source": "Some Blog",
            "resolved_link": "https://news.google.com/rss/articles/example",
        },
    )

    assert low_score < high_score


def test_article_fetch_priority_uses_generic_query_matching_for_non_openai_queries():
    godot_match = _article_fetch_priority(
        {
            "title": "Godot 4.6 新功能介绍：渲染和脚本大更新",
            "source": "Godot Blog",
            "resolved_link": "https://godotengine.org/article/godot-4-6",
        },
        query_text="Godot 4.6 新功能",
    )
    godot_no_match = _article_fetch_priority(
        {
            "title": "Unity 6 发布路线图与定价说明",
            "source": "Unity Blog",
            "resolved_link": "https://unity.com/blog/unity6",
        },
        query_text="Godot 4.6 新功能",
    )

    assert godot_match < godot_no_match


def test_enrich_news_items_reads_high_priority_articles_not_just_first_five(
    monkeypatch,
):
    from src import wechat

    calls = []

    def fake_fetch(url, **kwargs):
        calls.append(url)
        return f"text-for:{url}", "trafilatura"

    monkeypatch.setattr(wechat, "fetch_article_text_with_method", fake_fetch)

    items = [
        {
            "title": f"普通新闻{i}",
            "link": f"https://example.com/{i}",
            "source": "Example",
        }
        for i in range(7)
    ]
    items[6] = {
        "title": "OpenAI 最新实时语音 API 更新",
        "link": "https://news.google.com/rss/articles/openai",
        "resolved_link": "https://openai.com/index/realtime-audio",
        "source": "OpenAI",
    }
    enriched = enrich_news_items_with_article_text(items)

    assert len(calls) == 5
    assert "https://openai.com/index/realtime-audio" in calls
    assert "https://example.com/5" not in calls
    assert enriched[0]["article_status"] == "正文已读｜trafilatura"
    assert enriched[6]["article_status"] == "正文已读｜trafilatura"
    assert enriched[5]["article_excerpt"] == ""
    assert "未进入正文读取候选" in enriched[5]["article_status"]


def test_enrich_news_items_prefers_resolved_link(monkeypatch):
    from src import wechat

    calls = []

    def fake_fetch(url, **kwargs):
        calls.append(url)
        return "resolved text", "readability"

    monkeypatch.setattr(wechat, "fetch_article_text_with_method", fake_fetch)

    items = [
        {
            "title": "测试新闻",
            "link": "https://news.google.com/rss/articles/original",
            "resolved_link": "https://example.com/final-article",
        }
    ]
    enriched = enrich_news_items_with_article_text(items)

    assert calls == ["https://example.com/final-article"]
    assert enriched[0]["article_excerpt"] == "resolved text"
    assert enriched[0]["article_status"] == "正文已读｜readability-lxml"


def test_enrich_news_items_marks_unresolved_google_link_without_fetch(monkeypatch):
    from src import wechat

    calls = []

    def fake_fetch(*args, **kwargs):
        calls.append(args[0] if args else "")
        return ""

    monkeypatch.setattr(wechat, "fetch_article_text_with_method", fake_fetch)

    items = [
        {
            "title": "测试新闻",
            "link": "https://news.google.com/rss/articles/original",
            "resolved_link": "https://news.google.com/rss/articles/original",
        }
    ]
    enriched = enrich_news_items_with_article_text(items)

    assert calls == []
    assert enriched[0]["article_excerpt"] == ""
    assert "未解析到原文链接" in enriched[0]["article_status"]


def test_append_system_group_note_separates_from_existing_content():
    append_wechat_messages("【流萤】\nexisting_marker")
    append_system_group_note("【联网检索】\nquery_marker")

    content = read_wechat_group()
    assert "existing_marker\n\n【联网检索】" in content
    assert "query_marker" in content


def test_format_news_source_block_uses_compact_host_display():
    block = format_news_source_block(
        "openai最新语音模型",
        [
            {
                "title": "OpenAI 发布了一个非常长非常长非常长的实时语音模型标题示例",
                "source": "Cryptopolitan",
                "published_at": "05-08 07:51",
                "link": "https://news.google.com/rss/articles/abc?long=1",
                "resolved_link": "https://news.google.com/rss/articles/abc?long=1",
                "article_status": "正文不可用，使用标题与来源",
            }
        ],
    )

    assert "1. OpenAI 发布了一个非常长非常长非常长的实时语..." in block
    assert "来源：Cryptopolitan｜05-08 07:51｜正文不可用，使用标题与来源" in block
    assert "链接：news.google.com" in block
    assert "https://news.google.com/rss/articles/abc?long=1" not in block


def test_news_article_coverage_summary_warns_when_no_article_text():
    summary = _news_article_coverage_summary(
        [
            {"title": "A", "article_status": "正文不可用，使用标题与来源"},
            {"title": "B", "article_status": "未进入正文读取候选，仅使用标题与来源"},
        ]
    )

    assert "0 条读到页面文本" in summary
    assert "只能给出保守判断" in summary


def test_is_fetchable_article_url_blocks_local_and_private_hosts():
    assert not _is_fetchable_article_url("http://127.0.0.1/a")
    assert not _is_fetchable_article_url("http://172.20.1.5/a")
    assert not _is_fetchable_article_url("http://169.254.1.10/a")
    assert not _is_fetchable_article_url("http://[::1]/a")
    assert not _is_fetchable_article_url("http://[fe80::1]/a")
    assert _is_fetchable_article_url("https://example.com/a")


def test_title_matches_query_uses_any_query_term():
    assert _title_matches_query("OpenAI 发布新模型", "OpenAI 最近进展")
    assert _title_matches_query("OpenAI 最新语音模型发布", "openai最新语音模型")
    assert _title_matches_query("Godot 4.6 发布", "Godot 4.6")
    assert not _title_matches_query("苹果发布会", "OpenAI 最近进展")


def test_dedupe_and_trim_news_items_prefers_newer_items():
    items = [
        {"title": "A", "link": "https://example.com/a", "_sort_ts": 1.0},
        {
            "title": "A",
            "link": "https://example.com/a",
            "_sort_ts": 2.0,
            "source": "newer",
        },
        {"title": "B", "link": "https://example.com/b", "_sort_ts": 3.0},
    ]
    deduped = _dedupe_and_trim_news_items(items, max_items=2)

    assert len(deduped) == 2
    assert deduped[0]["title"] == "B"
    assert deduped[1]["source"] == "newer"
    assert "_sort_ts" not in deduped[0]


def test_dedupe_and_trim_news_items_prefers_recent_results(monkeypatch):
    from src import wechat

    now_ts = 200 * 86400
    monkeypatch.setattr(wechat.time, "time", lambda: now_ts)

    items = [
        {
            "title": "OpenAI 最新语音模型发布",
            "link": "https://example.com/recent",
            "_sort_ts": now_ts - 10 * 86400,
        },
        {
            "title": "OpenAI 旧语音模型消息",
            "link": "https://example.com/old",
            "_sort_ts": now_ts - 140 * 86400,
        },
    ]

    deduped = wechat._dedupe_and_trim_news_items(
        items,
        max_items=2,
        query_text="openai最新语音模型",
    )

    assert deduped[0]["link"] == "https://example.com/recent"
    assert deduped[1]["link"] == "https://example.com/old"


def test_dedupe_and_trim_news_items_prefers_recent_window_before_backfill(monkeypatch):
    from src import wechat

    now_ts = 200 * 86400
    monkeypatch.setattr(wechat.time, "time", lambda: now_ts)

    items = [
        {
            "title": "最近新闻 A",
            "link": "https://example.com/recent-a",
            "_sort_ts": now_ts - 5 * 86400,
        },
        {
            "title": "旧新闻 B",
            "link": "https://example.com/old-b",
            "_sort_ts": now_ts - 200 * 86400,
        },
        {
            "title": "最近新闻 C",
            "link": "https://example.com/recent-c",
            "_sort_ts": now_ts - 20 * 86400,
        },
        {
            "title": "旧新闻 D",
            "link": "https://example.com/old-d",
            "_sort_ts": now_ts - 300 * 86400,
        },
    ]

    deduped = wechat._dedupe_and_trim_news_items(
        items, max_items=3, query_text="测试最新新闻"
    )

    assert [item["link"] for item in deduped] == [
        "https://example.com/recent-a",
        "https://example.com/recent-c",
        "https://example.com/old-b",
    ]


def test_dedupe_and_trim_news_items_excludes_old_backfill_when_recent_pool_is_enough(
    monkeypatch,
):
    from src import wechat

    now_ts = 200 * 86400
    monkeypatch.setattr(wechat.time, "time", lambda: now_ts)

    items = [
        {
            "title": "最近新闻 A",
            "link": "https://example.com/recent-a",
            "_sort_ts": now_ts - 3 * 86400,
        },
        {
            "title": "最近新闻 B",
            "link": "https://example.com/recent-b",
            "_sort_ts": now_ts - 10 * 86400,
        },
        {
            "title": "最近新闻 C",
            "link": "https://example.com/recent-c",
            "_sort_ts": now_ts - 30 * 86400,
        },
        {
            "title": "旧新闻 D",
            "link": "https://example.com/old-d",
            "_sort_ts": now_ts - 300 * 86400,
        },
    ]

    deduped = wechat._dedupe_and_trim_news_items(
        items, max_items=2, query_text="测试最新新闻"
    )

    assert [item["link"] for item in deduped] == [
        "https://example.com/recent-a",
        "https://example.com/recent-b",
    ]


def test_dedupe_and_trim_news_items_prefers_openai_official_source(monkeypatch):
    from src import wechat

    now_ts = 200 * 86400
    monkeypatch.setattr(wechat.time, "time", lambda: now_ts)

    items = [
        {
            "title": "OpenAI 最新语音模型",
            "link": "https://news.example.com/openai-audio",
            "resolved_link": "https://news.example.com/openai-audio",
            "_sort_ts": now_ts - 2 * 86400,
        },
        {
            "title": "OpenAI 最新语音模型",
            "link": "https://news.google.com/rss/articles/openai",
            "resolved_link": "https://openai.com/index/new-audio-model",
            "_sort_ts": now_ts - 3 * 86400,
        },
    ]

    deduped = wechat._dedupe_and_trim_news_items(
        items,
        max_items=2,
        query_text="openai最新语音模型",
    )

    assert deduped[0]["resolved_link"] == "https://openai.com/index/new-audio-model"


def test_dedupe_and_trim_news_items_prefers_direct_links_over_unresolved_google(
    monkeypatch,
):
    from src import wechat

    now_ts = 200 * 86400
    monkeypatch.setattr(wechat.time, "time", lambda: now_ts)

    items = [
        {
            "title": "OpenAI 最新语音模型报道",
            "link": "https://news.google.com/rss/articles/google-item",
            "resolved_link": "https://news.google.com/rss/articles/google-item",
            "_sort_ts": now_ts - 2 * 86400,
        },
        {
            "title": "OpenAI 最新语音模型报道",
            "link": "https://direct.example.com/openai-audio",
            "resolved_link": "https://direct.example.com/openai-audio",
            "_sort_ts": now_ts - 3 * 86400,
        },
    ]

    deduped = wechat._dedupe_and_trim_news_items(
        items,
        max_items=2,
        query_text="openai最新语音模型",
    )

    assert deduped[0]["resolved_link"] == "https://direct.example.com/openai-audio"


def test_fetch_query_news_items_merges_sources_and_dedupes(monkeypatch):
    from src import wechat

    feed_map = {
        "Google News": [
            {
                "title": "OpenAI 发布新模型",
                "link": "https://a/1",
                "_sort_ts": 10.0,
                "source": "Google News",
            },
            {
                "title": "重复新闻",
                "link": "https://dup/1",
                "_sort_ts": 8.0,
                "source": "Google News",
            },
        ],
        "Bing News": [
            {
                "title": "Godot 4.6 发布",
                "link": "https://b/1",
                "_sort_ts": 9.0,
                "source": "Bing News",
            },
            {
                "title": "重复新闻",
                "link": "https://dup/1",
                "_sort_ts": 11.0,
                "source": "Bing News",
            },
        ],
        "Yicai Headline": [
            {
                "title": "国内 AI 芯片进展",
                "link": "https://c/1",
                "_sort_ts": 7.0,
                "source": "Yicai Headline",
            },
        ],
        "Sina Finance China": [],
        "Caijing Roll": [],
    }

    def fake_fetch(
        feed_url, max_items=10, source_fallback="News Source", query_text=""
    ):
        return list(feed_map[source_fallback])

    monkeypatch.setattr(wechat, "_fetch_rss_items_from_url", fake_fetch)

    items = _fetch_query_news_items("OpenAI 最近进展", max_items=10)

    assert len(items) == 4
    assert items[0]["source"] == "Google News"
    assert items[0]["title"] == "OpenAI 发布新模型"
    assert [item["link"] for item in items].count("https://dup/1") == 1


def test_news_digest_prompt_is_not_corrupted():
    text = Path("src/wechat.py").read_text(encoding="utf-8")
    assert "????????" not in text
    assert (
        "\\u4f60\\u8981\\u57fa\\u4e8e\\u8054\\u7f51\\u641c\\u7d22\\u7ed3\\u679c\\u6574\\u7406"
        in text
    )
    assert (
        "\\u4e0d\\u8981\\u5047\\u88c5\\u8bfb\\u53d6\\u4e86\\u6ca1\\u6709\\u63d0\\u4f9b\\u7684\\u6b63\\u6587"
        in text
    )
