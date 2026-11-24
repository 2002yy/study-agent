from __future__ import annotations

import json
from types import SimpleNamespace

from src.web import video_read
from src.web.tool_evidence import tool_source_items, trusted_tool_calls

URL = "https://www.bilibili.com/video/BV1Va4y167wd"


def test_a_bvid_is_taken_from_the_url():
    assert video_read._bvid(URL) == "BV1Va4y167wd"
    assert video_read._bvid("https://b23.tv/BV1Va4y167wd") == "BV1Va4y167wd"
    assert video_read._bvid("https://example.com/watch") == ""


def test_the_part_is_taken_from_the_url():
    assert video_read._part(URL) == 1
    assert video_read._part(URL + "?p=3") == 3
    assert video_read._part(URL + "?page=2") == 2


def test_vtt_cues_keep_their_timestamps():
    text = (
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.500\n第一句\n\n"
        "00:00:03.500 --> 00:00:06.000\n第二句\n"
    )
    rows = video_read._parse_vtt(text)
    assert rows == [
        {"start": 1.0, "end": 3.5, "text": "第一句"},
        {"start": 3.5, "end": 6.0, "text": "第二句"},
    ]


def test_a_cached_transcript_is_reused(monkeypatch, tmp_path):
    monkeypatch.setattr(video_read, "_cache_root", lambda: tmp_path)
    cached = {
        "ok": True, "kind": "video", "url": URL, "video_id": "BV1Va4y167wd",
        "part": 1, "title": "T", "method": "sensevoice",
        "transcript": [{"start": 0, "end": 1, "text": "缓存"}], "chars": 2,
        "scope": {"start": 0, "seconds": 60, "may_be_partial": True},
    }
    (tmp_path / "bili-BV1Va4y167wd-p1-0-60.json").write_text(
        json.dumps(cached, ensure_ascii=False), encoding="utf-8"
    )
    result = video_read.read_video(URL, max_seconds=60)
    assert result["cached"] is True
    assert result["transcript"][0]["text"] == "缓存"
    assert result["content"] == "[00:00] 缓存"


def test_the_cache_keeps_full_text_and_caps_only_the_output(monkeypatch, tmp_path):
    monkeypatch.setattr(video_read, "_cache_root", lambda: tmp_path)
    rows = [{"start": 0, "end": 1, "text": "字" * 100},
            {"start": 1, "end": 2, "text": "词" * 100}]
    (tmp_path / "bili-BV1Va4y167wd-p1-0-60.json").write_text(
        json.dumps({"ok": True, "kind": "video", "url": URL,
                    "video_id": "BV1Va4y167wd", "part": 1, "method": "sensevoice",
                    "transcript": rows, "scope": {"start": 0, "seconds": 60}},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    small = video_read.read_video(URL, max_chars=150, max_seconds=60)
    large = video_read.read_video(URL, max_chars=1000, max_seconds=60)
    assert len(small["transcript"]) == 1
    assert len(large["transcript"]) == 2
    # The second read must not reuse the first read's truncation.
    assert sum(len(row["text"]) for row in large["transcript"]) == 200


def test_a_different_part_does_not_hit_the_first_part_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(video_read, "_cache_root", lambda: tmp_path)
    (tmp_path / "bili-BV1Va4y167wd-p1-0-60.json").write_text(
        json.dumps({"ok": True, "kind": "video", "url": URL,
                    "video_id": "BV1Va4y167wd", "part": 1, "method": "sensevoice",
                    "transcript": [{"start": 0, "end": 1, "text": "第一P"}],
                    "scope": {"start": 0, "seconds": 60}}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        video_read, "_run",
        lambda args, timeout: SimpleNamespace(returncode=1, stdout="", stderr="blocked"),
    )
    result = video_read.read_video(URL + "?p=2", max_seconds=60)
    assert result.get("cached") is not True
    assert result["ok"] is False


def test_a_tiny_budget_is_not_inflated(monkeypatch):
    monkeypatch.setattr(video_read, "_run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not start work with no budget")))
    result = video_read.read_video(URL, timeout=2)
    assert result["error_code"] == "video_no_budget"


def test_an_unsupported_host_fails_closed():
    result = video_read.read_video("https://example.com/video/1", max_seconds=60)
    assert result["ok"] is False
    assert result["error_code"] == "video_unsupported"


def test_the_transcript_stops_at_the_character_cap():
    rows = [{"start": 0, "end": 1, "text": "字" * 6}, {"start": 1, "end": 2, "text": "字" * 6}]
    kept = video_read._trim(rows, 8)
    assert [len(row["text"]) for row in kept] == [6]


def test_a_video_read_is_citable_evidence():
    calls = [
        {"name": "web_search", "result": {
            "status": "ok", "results": [{"title": "video", "url": URL}],
        }},
        {"name": "web_read", "arguments": {"url": URL, "mode": "video"}, "result": {
            "ok": True, "kind": "video", "url": URL, "method": "sensevoice",
            "content": "[00:00] 正文",
            "transcript": [{"start": 0, "end": 20, "text": "正文"}],
        }},
    ]
    assert len(trusted_tool_calls(calls)) == 2
    items = tool_source_items(calls)
    assert any(item["url"] == URL for item in items)
