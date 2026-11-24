"""Read a Bilibili video's spoken content.

Subtitles first; when the video has none, download a bounded audio section and
transcribe it locally with SenseVoice. Results are cached by video id and read
range, so the same video is transcribed once.

This module never downloads the whole video and never bypasses access control:
premium or login-only tracks are left as failures, not worked around.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from src.web.tool_evidence import _public_url

_BVID = re.compile(r"(BV[0-9A-Za-z]{10})")
_SUPPORTED_HOSTS = ("bilibili.com", "b23.tv")
#: Bilibili's "AI subtitle" tracks are not public; danmaku is not speech.
_SPEECH_LANGS = ("zh-Hans", "zh-CN", "zh", "ai-zh", "en")
_MAX_SECONDS = 600


def _cache_root() -> Path:
    raw = os.getenv("STUDY_AGENT_MEDIA_CACHE")
    if raw:
        return Path(raw)
    return Path.home() / ".cache" / "study-agent" / "media"


def _bvid(url: str) -> str:
    match = _BVID.search(str(url or ""))
    return match.group(1) if match else ""


def _failure(url: str, code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "kind": "video",
        "url": url,
        "error": message,
        "error_code": code,
    }


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=max(1, int(timeout)),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _parse_vtt(text: str) -> list[dict[str, Any]]:
    """Minimal VTT cue parser; timestamps stay attached to each line."""

    rows: list[dict[str, Any]] = []
    current_start = 0.0
    current_end = 0.0
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if "-->" in line:
            left, _, right = line.partition("-->")
            current_start = _seconds(left.strip().split(" ")[0])
            current_end = _seconds(right.strip().split(" ")[0])
            continue
        if not line or line.isdigit() or line.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")):
            continue
        rows.append({"start": current_start, "end": current_end, "text": line})
    return rows


def _seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return 0.0
    total = 0.0
    for number in numbers:
        total = total * 60 + number
    return round(total, 2)


def _speech_languages(meta: dict[str, Any]) -> list[str]:
    subtitles = meta.get("subtitles") or {}
    if not isinstance(subtitles, dict):
        return []
    available = [key for key in subtitles if key and key != "danmaku"]
    ordered = [lang for lang in _SPEECH_LANGS if lang in available]
    return ordered or available


def _transcript_from_subtitles(
    url: str, meta: dict[str, Any], work: Path, timeout: float
) -> list[dict[str, Any]] | None:
    languages = _speech_languages(meta)
    if not languages:
        return None
    for language in languages:
        done = _run(
            ["yt-dlp", "--skip-download", "--write-subs", "--sub-langs", language,
             "--sub-format", "vtt", "-o", str(work / "sub"), url],
            timeout,
        )
        for path in work.glob("sub*.vtt"):
            rows = _parse_vtt(path.read_text(encoding="utf-8", errors="replace"))
            if rows:
                return rows
        if done.returncode != 0:
            continue
    return None


def _transcript_from_asr(
    url: str, work: Path, seconds: int, timeout: float
) -> dict[str, Any]:
    asr_python = os.getenv(
        "STUDY_AGENT_ASR_PYTHON", r"D:\video\tools\envs\asr\Scripts\python.exe"
    )
    script = os.getenv(
        "STUDY_AGENT_SENSEVOICE",
        r"C:\Users\Zhang\.config\opencode\skills\z-video-study-webpage\scripts\asr_sensevoice.py",
    )
    if not Path(asr_python).exists() or not Path(script).exists():
        return {"error_code": "video_asr_unavailable",
                "error": "SenseVoice runtime is not installed"}

    audio = work / "audio.%(ext)s"
    started = time.monotonic()
    done = _run(
        ["yt-dlp", "--download-sections", f"*0-{seconds}", "-f", "ba/b",
         "-o", str(audio), url],
        timeout,
    )
    files = [path for path in work.glob("audio.*") if path.suffix not in {".part"}]
    if not files:
        return {"error_code": "video_no_audio",
                "error": (done.stderr or "no audio track")[-300:]}
    remaining = timeout - (time.monotonic() - started)
    if remaining < 5:
        return {"error_code": "video_timeout", "error": "no time left for transcription"}
    done = _run(
        [asr_python, script, "--video", str(files[0]), "--out-dir", str(work / "asr")],
        remaining,
    )
    transcript = work / "asr" / "transcript-asr.json"
    if not transcript.exists():
        return {"error_code": "video_asr_failed",
                "error": (done.stderr or "SenseVoice produced no transcript")[-300:]}
    rows = json.loads(transcript.read_text(encoding="utf-8"))
    return {"rows": rows}


def _trim(rows: list[Any], max_chars: int) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        if total + len(text) > max_chars and kept:
            break
        kept.append({
            "start": round(float(row.get("start") or 0), 2),
            "end": round(float(row.get("end") or 0), 2),
            "text": text,
        })
        total += len(text)
    return kept


def read_video(
    url: str, *, max_chars: int = 12_000, timeout: float = 180.0,
    max_seconds: int = 180,
) -> dict[str, Any]:
    """Return timed transcript rows for one Bilibili video."""

    target = _public_url(url)
    video_id = _bvid(target or str(url or ""))
    if not target or not video_id:
        return _failure(str(url or ""), "video_unsupported", "not a Bilibili video URL")
    host = (target.split("/")[2] if "//" in target else "").lower()
    if not any(host == item or host.endswith("." + item) for item in _SUPPORTED_HOSTS):
        return _failure(target, "video_unsupported", "host is not supported yet")

    seconds = max(15, min(int(max_seconds), _MAX_SECONDS))
    cache = _cache_root() / f"bili-{video_id}-{seconds}.json"
    if cache.exists():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            cached["cached"] = True
            return cached
        except (OSError, ValueError):
            pass

    deadline = time.monotonic() + max(10.0, float(timeout))
    work = _cache_root() / f"bili-{video_id}-{seconds}.work"
    work.mkdir(parents=True, exist_ok=True)

    try:
        done = _run(
            ["yt-dlp", "--dump-single-json", "--skip-download", target],
            min(60.0, deadline - time.monotonic()),
        )
    except subprocess.TimeoutExpired:
        return _failure(target, "video_timeout", "metadata lookup timed out")
    if done.returncode != 0 or not (done.stdout or "").strip():
        return _failure(target, "video_unavailable",
                        (done.stderr or "yt-dlp could not read the video")[-300:])
    try:
        meta = json.loads(done.stdout)
    except ValueError:
        return _failure(target, "video_unavailable", "yt-dlp returned invalid metadata")

    rows: list[dict[str, Any]] | None = None
    method = ""
    try:
        rows = _transcript_from_subtitles(
            target, meta, work, min(60.0, deadline - time.monotonic())
        )
        if rows:
            method = "subtitle"
    except subprocess.TimeoutExpired:
        rows = None
    if not rows:
        remaining = deadline - time.monotonic()
        if remaining < 10:
            return _failure(target, "video_timeout", "no time left for audio")
        result = _transcript_from_asr(target, work, seconds, remaining)
        if "error_code" in result:
            return _failure(target, result["error_code"], result.get("error") or "audio read failed")
        rows = result["rows"]
        method = "sensevoice"

    transcript = _trim(rows, max(1_000, min(int(max_chars), 40_000)))
    if not transcript:
        return _failure(target, "video_no_transcript", "the video produced no speech")
    duration = meta.get("duration")
    result = {
        "ok": True,
        "kind": "video",
        "url": target,
        "video_id": video_id,
        "title": str(meta.get("title") or ""),
        "duration": duration,
        "method": method,
        "language": "zh",
        "transcript": transcript,
        "chars": sum(len(row["text"]) for row in transcript),
        "scope": {
            "start": 0,
            "seconds": seconds,
            "may_be_partial": bool(duration and duration > seconds),
        },
        "cached": False,
    }
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass
    return result
