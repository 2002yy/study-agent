"""Standalone audio reads reuse the video download, trim and ASR chain."""

from __future__ import annotations

import subprocess

import pytest

from src.web import audio_read
from src.web.safe_http import SafeFetchRefusal
from src.web.tool_gateway import GeneralWebGateway


@pytest.fixture()
def audio_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDY_AGENT_MEDIA_CACHE", str(tmp_path / "media"))
    return tmp_path / "media"


def test_audio_url_detection_is_suffix_only():
    assert audio_read.looks_like_audio_url("https://cdn.example.com/ep1.mp3")
    assert audio_read.looks_like_audio_url("https://x.example/a/b.m4a?token=1")
    assert audio_read.looks_like_audio_url("https://x.example/b.WAV")
    assert not audio_read.looks_like_audio_url("https://x.example/story.html")
    assert not audio_read.looks_like_audio_url("https://x.example/ep.mp3.html")
    assert not audio_read.looks_like_audio_url("not a url")


def test_audio_read_returns_timed_rows(audio_cache, monkeypatch):
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        audio_read,
        "_fetch_audio",
        lambda url, timeout, max_bytes: (b"ID3fake", url, "audio/mpeg", ""),
    )
    monkeypatch.setattr(
        audio_read, "_trim_to_wav",
        lambda source, work, start, seconds, deadline: {"path": work / "clip.wav"},
    )

    def fake_transcribe(media, work, start, deadline, language="zh"):
        calls["language"] = language
        calls["start"] = start
        return {"rows": [
            {"start": start + 1.0, "end": start + 2.5, "text": "你好，这里是访谈"},
            {"start": start + 3.0, "end": start + 4.0, "text": "hello from the show"},
        ]}

    monkeypatch.setattr(audio_read, "_transcribe_media", fake_transcribe)
    result = audio_read.read_audio(
        "https://cdn.example.com/show/ep1.mp3", max_chars=4000,
        timeout=60, start_seconds=30, max_seconds=120,
    )

    assert result["ok"] is True
    assert result["kind"] == "audio"
    assert result["method"] == "audio_asr"
    assert result["sources"] == {"speech": "sensevoice"}
    assert "[00:31] 你好，这里是访谈" in result["content"]
    assert "[00:33] hello from the show" in result["content"]
    assert result["scope"]["start"] == 30
    assert result["scope"]["seconds"] == 120
    assert calls == {"language": "auto", "start": 30}
    assert result["segments"][0]["end"] == 32.5


def test_second_read_uses_the_cached_transcript(audio_cache, monkeypatch):
    fetches = {"count": 0}

    def fake_fetch(url, timeout, max_bytes):
        fetches["count"] += 1
        return b"ID3fake", url, "audio/mpeg", ""

    monkeypatch.setattr(audio_read, "_fetch_audio", fake_fetch)
    monkeypatch.setattr(
        audio_read, "_trim_to_wav",
        lambda source, work, start, seconds, deadline: {"path": work / "clip.wav"},
    )
    monkeypatch.setattr(
        audio_read, "_transcribe_media",
        lambda media, work, start, deadline, language="zh": {
            "rows": [{"start": 0.0, "end": 2.0, "text": "one line"}]
        },
    )
    first = audio_read.read_audio("https://cdn.example.com/a.mp3", timeout=60)
    second = audio_read.read_audio("https://cdn.example.com/a.mp3", timeout=60)

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["cached"] is True
    assert fetches["count"] == 1


def test_missing_asr_runtime_is_reported_not_silent(audio_cache, monkeypatch):
    monkeypatch.setattr(
        audio_read, "_fetch_audio",
        lambda url, timeout, max_bytes: (b"ID3fake", url, "audio/mpeg", ""),
    )
    monkeypatch.setattr(
        audio_read, "_trim_to_wav",
        lambda source, work, start, seconds, deadline: {"path": work / "clip.wav"},
    )
    monkeypatch.setattr(
        audio_read, "_transcribe_media",
        lambda media, work, start, deadline, language="zh": {
            "error_code": "video_asr_unavailable",
            "error": "SenseVoice runtime is not installed",
        },
    )
    result = audio_read.read_audio("https://cdn.example.com/a.mp3", timeout=60)

    assert result["ok"] is False
    assert result["error_code"] == "audio_asr_unavailable"
    assert "SenseVoice" in result["error"]


def test_html_payload_is_not_transcribed(audio_cache, monkeypatch):
    monkeypatch.setattr(
        audio_read, "_fetch_audio",
        lambda url, timeout, max_bytes: (
            b"<html>login</html>", url, "text/html; charset=utf-8", "",
        ),
    )
    result = audio_read.read_audio("https://cdn.example.com/a.mp3", timeout=60)

    assert result["ok"] is False
    assert result["error_code"] == "audio_not_media"


def test_oversized_download_fails_loudly(audio_cache, monkeypatch):
    monkeypatch.setattr(
        audio_read, "_fetch_audio",
        lambda url, timeout, max_bytes: (b"", "", "", "response_too_large"),
    )
    result = audio_read.read_audio("https://cdn.example.com/big.mp3", timeout=60)

    assert result["ok"] is False
    assert result["error_code"] == "audio_too_large"


def test_security_refusal_is_not_reported_as_transcription_failure(
    audio_cache, monkeypatch,
):
    def refuse(url, timeout, max_bytes):
        raise SafeFetchRefusal("dns_failed")

    # The real wrapper converts the transport refusal into a reason; stub only
    # the transport call underneath it.
    monkeypatch.setattr(audio_read, "_fetch_binary_payload", refuse)
    result = audio_read.read_audio("https://cdn.example.com/a.mp3", timeout=60)

    assert result["ok"] is False
    assert result["error_code"] == "audio_blocked"
    assert "dns_failed" in result["error"]


def test_music_without_speech_is_reported_as_no_speech(audio_cache, monkeypatch):
    monkeypatch.setattr(
        audio_read, "_fetch_audio",
        lambda url, timeout, max_bytes: (b"ID3fake", url, "audio/mpeg", ""),
    )
    monkeypatch.setattr(
        audio_read, "_trim_to_wav",
        lambda source, work, start, seconds, deadline: {"path": work / "clip.wav"},
    )
    # SenseVoice often emits one punctuation mark on music or silence.
    monkeypatch.setattr(
        audio_read, "_transcribe_media",
        lambda media, work, start, deadline, language="zh": {
            "rows": [{"start": 0.0, "end": 1.0, "text": "。"}]
        },
    )
    result = audio_read.read_audio("https://cdn.example.com/music.mp3", timeout=60)

    assert result["ok"] is False
    assert result["error_code"] == "audio_no_speech"


def test_missing_ffmpeg_is_reported(audio_cache, monkeypatch):
    monkeypatch.setattr(
        audio_read, "_fetch_audio",
        lambda url, timeout, max_bytes: (b"ID3fake", url, "audio/mpeg", ""),
    )
    monkeypatch.setattr(audio_read.shutil, "which", lambda name: None)
    result = audio_read.read_audio("https://cdn.example.com/a.mp3", timeout=60)

    assert result["ok"] is False
    assert result["error_code"] == "audio_ffmpeg_unavailable"


def test_a_transcription_that_overruns_the_budget_fails_explicitly(
    audio_cache, monkeypatch,
):
    """A long window under a short read budget must not raise TimeoutExpired."""

    def overrun(media, work, start, deadline, language="zh"):
        raise subprocess.TimeoutExpired(cmd="sensevoice", timeout=8)

    monkeypatch.setattr(
        audio_read, "_fetch_audio",
        lambda url, timeout, max_bytes: (b"ID3fake", url, "audio/mpeg", ""),
    )
    monkeypatch.setattr(
        audio_read, "_trim_to_wav",
        lambda source, work, start, seconds, deadline: {"path": work / "clip.wav"},
    )
    monkeypatch.setattr(audio_read, "_transcribe_media", overrun)
    result = audio_read.read_audio(
        "https://cdn.example.com/long.mp3", timeout=8, max_seconds=240,
    )

    assert result["ok"] is False
    assert result["error_code"] == "audio_timeout"
    assert "shorter audio_seconds" in result["error"]


def test_gateway_auto_mode_routes_audio_urls(monkeypatch):
    seen: dict[str, object] = {}

    def fake_read_audio(url, max_chars, timeout, *, start_seconds=0, audio_seconds=240):
        seen.update(url=url, start=start_seconds, seconds=audio_seconds)
        return {"ok": True, "kind": "audio", "method": "audio_asr",
                "url": url, "content": "[00:00] hello"}

    monkeypatch.setattr("src.web.tool_gateway._read_audio", fake_read_audio)
    result = GeneralWebGateway(search_strategy="fallback").read(
        "https://cdn.example.com/ep.mp3", mode="auto",
        start_seconds=5, audio_seconds=90,
    )

    assert result["ok"] is True
    assert result["method"] == "audio_asr"
    assert seen == {"url": "https://cdn.example.com/ep.mp3", "start": 5, "seconds": 90}


def test_gateway_rejects_unknown_mode():
    result = GeneralWebGateway(search_strategy="fallback").read(
        "https://cdn.example.com/ep.mp3", mode="nope",
    )
    assert result["ok"] is False
    assert result["error_code"] == "invalid_mode"


def test_web_read_tool_schema_exposes_the_audio_entry():
    """The capability is only real if the model can see and ask for it."""

    from src.tools.web_agent import WEB_TOOLS

    tool = next(item for item in WEB_TOOLS if item["function"]["name"] == "web_read")
    properties = tool["function"]["parameters"]["properties"]

    assert "audio" in properties["mode"]["enum"]
    assert properties["audio_seconds"]["maximum"] == 600
    assert "audio" in tool["function"]["description"]
