"""Read a Bilibili video's spoken content.

Subtitles first; when the video has none, download a bounded audio section and
transcribe it locally with SenseVoice. Results are cached by video id, part and
read range, so the same section is transcribed once.

This module never downloads the whole video and never bypasses access control:
premium or login-only tracks are left as failures, not worked around.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from src.web.tool_evidence import _public_url

_BVID = re.compile(r"(BV[0-9A-Za-z]{10})")
_PART = re.compile(r"[?&](?:p|page)=(\d+)")
_SUPPORTED_HOSTS = ("bilibili.com", "b23.tv")
#: Bilibili's "AI subtitle" tracks are not public; danmaku is not speech.
_SPEECH_LANGS = ("zh-Hans", "zh-CN", "zh", "ai-zh", "en")
_MAX_SECONDS = 600
_MIN_BUDGET = 3.0


def _cache_root() -> Path:
    raw = os.getenv("STUDY_AGENT_MEDIA_CACHE")
    if raw:
        return Path(raw)
    return Path.home() / ".cache" / "study-agent" / "media"


def _bvid(url: str) -> str:
    match = _BVID.search(str(url or ""))
    return match.group(1) if match else ""


def _part(url: str) -> int:
    match = _PART.search(str(url or ""))
    return max(1, int(match.group(1))) if match else 1


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


def _clock(seconds: float) -> str:
    total = int(max(0, seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def _speech_languages(meta: dict[str, Any]) -> list[str]:
    subtitles = meta.get("subtitles") or {}
    if not isinstance(subtitles, dict):
        return []
    available = [key for key in subtitles if key and key != "danmaku"]
    ordered = [lang for lang in _SPEECH_LANGS if lang in available]
    return ordered or available


def _transcript_from_subtitles(
    url: str, meta: dict[str, Any], work: Path, deadline: float,
) -> list[dict[str, Any]] | None:
    languages = _speech_languages(meta)
    if not languages:
        return None
    for language in languages:
        remaining = deadline - time.monotonic()
        if remaining < _MIN_BUDGET:
            return None
        done = _run(
            ["yt-dlp", "--skip-download", "--write-subs", "--sub-langs", language,
             "--sub-format", "vtt", "-o", str(work / "sub"), url],
            remaining,
        )
        for path in work.glob("sub*.vtt"):
            rows = _parse_vtt(path.read_text(encoding="utf-8", errors="replace"))
            if rows:
                return rows
        if done.returncode != 0:
            continue
    return None


def _transcript_from_asr(
    url: str, work: Path, start: int, seconds: int, deadline: float,
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
    end = start + seconds
    remaining = deadline - time.monotonic()
    if remaining < _MIN_BUDGET:
        return {"error_code": "video_no_budget", "error": "no time left for audio"}
    done = _run(
        ["yt-dlp", "--download-sections", f"*{start}-{end}", "-f", "ba/b",
         "-o", str(audio), url],
        remaining,
    )
    files = [path for path in work.glob("audio.*") if path.suffix not in {".part"}]
    if not files:
        return {"error_code": "video_no_audio",
                "error": (done.stderr or "no audio track")[-300:]}
    remaining = deadline - time.monotonic()
    if remaining < _MIN_BUDGET:
        return {"error_code": "video_no_budget", "error": "no time left for transcription"}
    done = _run(
        [asr_python, script, "--video", str(files[0]), "--out-dir", str(work / "asr")],
        remaining,
    )
    transcript = work / "asr" / "transcript-asr.json"
    if not transcript.exists():
        return {"error_code": "video_asr_failed",
                "error": (done.stderr or "SenseVoice produced no transcript")[-300:]}
    rows = json.loads(transcript.read_text(encoding="utf-8"))
    # The clip starts at 0; citations must point at the real video time.
    shifted = []
    for row in rows:
        if isinstance(row, dict) and str(row.get("text") or "").strip():
            shifted.append({
                "start": round(start + float(row.get("start") or 0), 2),
                "end": round(start + float(row.get("end") or 0), 2),
                "text": str(row["text"]).strip(),
            })
    return {"rows": shifted}


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


def _project(transcript: list[dict[str, Any]]) -> str:
    """The citable text form: one timestamped line per row."""

    return "\n".join(f"[{_clock(row['start'])}] {row['text']}" for row in transcript)


def _read_cache(cache: Path, max_chars: int) -> dict[str, Any] | None:
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = cached.get("transcript")
    if not isinstance(rows, list):
        return None
    transcript = _trim(rows, max_chars)
    if not transcript:
        return None
    cached["transcript"] = transcript
    cached["content"] = _project(transcript)
    cached["chars"] = sum(len(row["text"]) for row in transcript)
    cached["cached"] = True
    return cached


def read_video(
    url: str, *, max_chars: int = 12_000, timeout: float = 180.0,
    max_seconds: int = 180, start_seconds: int = 0,
) -> dict[str, Any]:
    """Return timed transcript rows for one Bilibili video section."""

    target = _public_url(url)
    video_id = _bvid(target or str(url or ""))
    if not target or not video_id:
        return _failure(str(url or ""), "video_unsupported", "not a Bilibili video URL")
    host = (target.split("/")[2] if "//" in target else "").lower()
    if not any(host == item or host.endswith("." + item) for item in _SUPPORTED_HOSTS):
        return _failure(target, "video_unsupported", "host is not supported yet")
    if timeout < _MIN_BUDGET:
        return _failure(target, "video_no_budget", "no time left for a video read")

    start = max(0, min(int(start_seconds), 3600))
    seconds = max(15, min(int(max_seconds), _MAX_SECONDS))
    part = _part(target)
    # Identity is the section, not the request: a smaller max_chars must not
    # poison a later, larger read of the same section.
    cache = _cache_root() / f"bili-{video_id}-p{part}-{start}-{seconds}.json"
    cached = _read_cache(cache, max_chars)
    if cached is not None:
        return cached

    deadline = time.monotonic() + float(timeout)
    work = _cache_root() / f"bili-{video_id}-p{part}-{start}-{seconds}.work"
    work.mkdir(parents=True, exist_ok=True)

    try:
        remaining = deadline - time.monotonic()
        if remaining < _MIN_BUDGET:
            return _failure(target, "video_no_budget", "no time left for metadata")
        try:
            done = _run(
                ["yt-dlp", "--dump-single-json", "--skip-download", target],
                min(60.0, remaining),
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
            rows = _transcript_from_subtitles(target, meta, work, deadline)
            if rows:
                method = "subtitle"
        except subprocess.TimeoutExpired:
            rows = None
        if rows and start:
            rows = [row for row in rows if start <= float(row.get("start") or 0) < start + seconds]
        if not rows:
            result = _transcript_from_asr(target, work, start, seconds, deadline)
            if "error_code" in result:
                return _failure(target, result["error_code"], result.get("error") or "audio read failed")
            rows = result["rows"]
            method = "sensevoice"

        full = _trim(rows, 40_000)
        transcript = _trim(full, max(1_000, min(int(max_chars), 40_000)))
        if not transcript:
            return _failure(target, "video_no_transcript", "the video produced no speech")
        duration = meta.get("duration")
        result = {
            "ok": True,
            "kind": "video",
            "url": target,
            "video_id": video_id,
            "part": part,
            "title": str(meta.get("title") or ""),
            "duration": duration,
            "method": method,
            "language": "zh",
            "transcript": transcript,
            # The existing evidence path reads `content`; keep one timestamped
            # projection so a video read is citable without a second system.
            "content": _project(transcript),
            "chars": sum(len(row["text"]) for row in transcript),
            "scope": {
                "start": start,
                "seconds": seconds,
                "may_be_partial": bool(duration and duration > start + seconds),
            },
            "cached": False,
        }
        try:
            payload = dict(result)
            payload["transcript"] = full
            payload.pop("content", None)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError:
            pass
        return result
    finally:
        # Keep the JSON cache, not the downloaded audio.
        shutil.rmtree(work, ignore_errors=True)
