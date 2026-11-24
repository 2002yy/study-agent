from __future__ import annotations

import json

from src.web import video_read


def test_a_bvid_is_taken_from_the_url():
    assert video_read._bvid("https://www.bilibili.com/video/BV1Va4y167wd") == "BV1Va4y167wd"
    assert video_read._bvid("https://b23.tv/BV1Va4y167wd") == "BV1Va4y167wd"
    assert video_read._bvid("https://example.com/watch") == ""


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
        "ok": True, "kind": "video", "url": "https://www.bilibili.com/video/BV1Va4y167wd",
        "video_id": "BV1Va4y167wd", "title": "T", "method": "sensevoice",
        "transcript": [{"start": 0, "end": 1, "text": "缓存"}], "chars": 2,
    }
    (tmp_path / "bili-BV1Va4y167wd-60.json").write_text(
        json.dumps(cached, ensure_ascii=False), encoding="utf-8"
    )
    result = video_read.read_video(
        "https://www.bilibili.com/video/BV1Va4y167wd", max_seconds=60
    )
    assert result["cached"] is True
    assert result["transcript"][0]["text"] == "缓存"


def test_an_unsupported_host_fails_closed():
    result = video_read.read_video("https://example.com/video/1", max_seconds=60)
    assert result["ok"] is False
    assert result["error_code"] == "video_unsupported"


def test_the_transcript_stops_at_the_character_cap():
    rows = [{"start": 0, "end": 1, "text": "字" * 6}, {"start": 1, "end": 2, "text": "字" * 6}]
    kept = video_read._trim(rows, 8)
    assert [len(row["text"]) for row in kept] == [6]
