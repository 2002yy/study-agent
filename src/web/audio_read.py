"""Read standalone audio (podcasts, interviews, recordings) as a transcript.

The video reader already owns the hard parts: one bounded media fetch, one
FFmpeg trim and the local SenseVoice runtime. This module is only the URL
adapter for that chain, so audio does not grow a second downloader, a second
transcoder or a second speech model.

A read is bounded three ways: the shared transport caps the payload at 4 MB,
the section is at most 600 seconds, and the caller's timeout is one deadline
for download, conversion and transcription. A missing FFmpeg or ASR runtime is
reported as an explicit error code, never as an empty success.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.news.article_fetcher import _fetch_binary_payload
from src.web.safe_http import SafeFetchRefusal
from src.web.tool_evidence import _public_url
from src.web.video_read import (
    _MIN_BUDGET,
    _cache_root,
    _clock,
    _run,
    _transcribe_media,
    _trim,
)

_AUDIO_SUFFIXES = (
    ".mp3", ".m4a", ".m4b", ".aac", ".wav", ".flac", ".ogg", ".oga", ".opus",
)
_MAX_SECONDS = 600
#: The shared transport refuses payloads over 4 MB after decompression, so a
#: 128 kbps MP3 is readable for roughly four minutes. Larger files fail loudly.
_MAX_BYTES = 4 * 1024 * 1024
_DEFAULT_SECONDS = 240


def looks_like_audio_url(url: str) -> bool:
    """True only for a URL whose path ends in a known audio suffix."""

    try:
        path = urlparse(str(url or "")).path.lower()
    except ValueError:
        return False
    return path.endswith(_AUDIO_SUFFIXES)


def _failure(url: str, code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "kind": "audio",
        "url": url,
        "error": message,
        "error_code": code,
    }


def _fetch_audio(
    url: str, timeout: float, max_bytes: int,
) -> tuple[bytes, str, str, str]:
    try:
        return _fetch_binary_payload(url, int(max(1, timeout)), max_bytes)
    except SafeFetchRefusal as exc:
        # The transport refuses before contacting the host (SSRF rules) or when
        # the payload exceeds its cap. Neither is a transcription failure, so
        # keep the reason and let the caller name it.
        return b"", url, "", exc.reason or "refused"
    except (OSError, ValueError, TypeError):
        return b"", url, "", "fetch_failed"


def _trim_to_wav(
    source: Path, work: Path, start: int, seconds: int, deadline: float,
) -> dict[str, Any]:
    """Cut the requested window with FFmpeg; SenseVoice needs 16 kHz mono."""

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"error_code": "audio_ffmpeg_unavailable",
                "error": "ffmpeg is not installed"}
    remaining = deadline - time.monotonic()
    if remaining < _MIN_BUDGET:
        return {"error_code": "audio_no_budget", "error": "no time left for conversion"}
    target = work / "clip.wav"
    args = [ffmpeg, "-v", "error", "-y"]
    if start:
        args += ["-ss", str(start)]
    args += [
        "-t", str(seconds), "-i", str(source), "-vn",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target),
    ]
    done = _run(args, remaining)
    if done.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        return {"error_code": "audio_convert_failed",
                "error": (done.stderr or "ffmpeg could not decode the audio")[-300:]}
    return {"path": target}


def _asr_code(code: str) -> str:
    return {
        "video_asr_unavailable": "audio_asr_unavailable",
        "video_asr_failed": "audio_asr_failed",
        "video_no_budget": "audio_no_budget",
    }.get(code, "audio_asr_failed")


def _render(rows: list[dict[str, Any]], max_chars: int) -> dict[str, Any]:
    kept = _trim(rows, max(max(500, int(max_chars)), 500))
    content = "\n".join(f"[{_clock(row['start'])}] {row['text']}" for row in kept)
    return {
        "transcript": kept,
        "segments": kept,
        "text": "\n".join(row["text"] for row in kept),
        "content": content,
        "chars": sum(len(row["text"]) for row in kept),
    }


def _read_cache(cache: Path, max_chars: int) -> dict[str, Any] | None:
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = cached.get("transcript")
    if not isinstance(rows, list) or not rows:
        return None
    rendered = _render(rows, max_chars)
    if not rendered["transcript"]:
        return None
    available = sum(len(str(row.get("text") or "")) for row in rows if isinstance(row, dict))
    cached.update(rendered)
    cached.update({
        "ok": True,
        "kind": "audio",
        "method": "audio_asr",
        "language": "auto",
        "sources": {"speech": "sensevoice"},
    })
    cached["cached"] = True
    scope = dict(cached.get("scope") or {})
    scope["chars_truncated"] = rendered["chars"] < available
    scope["may_be_partial"] = bool(scope.get("may_be_partial") or scope["chars_truncated"])
    cached["scope"] = scope
    return cached


def read_audio(
    url: str, *, max_chars: int = 12_000, timeout: float = 240.0,
    start_seconds: int = 0, max_seconds: int = _DEFAULT_SECONDS,
) -> dict[str, Any]:
    """Transcribe one bounded window of a public audio file."""

    target = _public_url(url)
    if not target:
        return _failure(str(url or ""), "audio_unsupported",
                        "not a public HTTP(S) audio URL")
    if not looks_like_audio_url(target):
        return _failure(target, "audio_unsupported",
                        "the URL does not end in a known audio suffix")
    if timeout < _MIN_BUDGET:
        return _failure(target, "audio_no_budget", "no time left for an audio read")

    start = max(0, min(int(start_seconds), 3600))
    seconds = max(15, min(int(max_seconds), _MAX_SECONDS))
    digest = hashlib.sha1(f"{target}|{start}|{seconds}".encode()).hexdigest()[:16]
    root = _cache_root()
    cache = root / f"audio-{digest}.json"
    cached = _read_cache(cache, max_chars)
    if cached is not None:
        return cached

    deadline = time.monotonic() + float(timeout)
    work = root / f"audio-{digest}.work"
    work.mkdir(parents=True, exist_ok=True)
    try:
        data, final_url, content_type, reason = _fetch_audio(
            target, deadline - time.monotonic(), _MAX_BYTES,
        )
        if reason:
            code = {
                "response_too_large": "audio_too_large",
                "unsafe_redirect_target": "audio_unsafe_redirect",
                "deadline_exhausted": "audio_timeout",
            }.get(reason)
            if not code:
                code = (
                    "audio_blocked"
                    if reason.startswith(("unsafe_", "dns_"))
                    else "audio_fetch_failed"
                )
            return _failure(target, code, reason)
        if not data:
            return _failure(target, "audio_fetch_failed", "the audio download was empty")
        lowered = (content_type or "").lower()
        if lowered.startswith("text/html") or lowered.startswith("application/xhtml"):
            return _failure(target, "audio_not_media",
                            f"the server returned {content_type}, not an audio file")
        suffix = Path(urlparse(final_url or target).path).suffix.lower() or ".bin"
        source = work / f"source{suffix}"
        source.write_bytes(data)

        try:
            trimmed = _trim_to_wav(source, work, start, seconds, deadline)
        except subprocess.TimeoutExpired:
            return _failure(target, "audio_timeout",
                            "audio conversion did not finish in the read budget")
        if "error_code" in trimmed:
            return _failure(target, trimmed["error_code"],
                            trimmed.get("error") or "audio conversion failed")

        try:
            result = _transcribe_media(
                trimmed["path"], work, start, deadline, language="auto",
            )
        except subprocess.TimeoutExpired:
            return _failure(
                target, "audio_timeout",
                "transcription did not finish in the read budget; retry with a "
                "shorter audio_seconds or a larger timeout",
            )
        if "error_code" in result:
            return _failure(target, _asr_code(result["error_code"]),
                            result.get("error") or "audio transcription failed")
        rows = [row for row in result.get("rows") or [] if isinstance(row, dict)]
        # SenseVoice hallucinates a stray punctuation mark on music or silence;
        # that is not speech, and reporting it as a transcript would be a lie.
        rows = [
            row for row in rows
            if re.search(r"[0-9A-Za-z\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]",
                         str(row.get("text") or ""))
        ]
        if not rows:
            return _failure(
                target, "audio_no_speech",
                "no speech detected in this audio (music, silence or noise)",
            )

        rendered = _render(rows, max_chars)
        last_end = max(float(row.get("end") or 0) for row in rows)
        result = {
            "ok": True,
            "kind": "audio",
            "url": target,
            "final_url": final_url or target,
            "content_type": content_type,
            "method": "audio_asr",
            "language": "auto",
            "sources": {"speech": "sensevoice"},
            "scope": {
                "start": start,
                "seconds": seconds,
                "may_be_partial": bool(
                    last_end >= start + seconds - 2
                    or rendered["chars"] < sum(len(row["text"]) for row in rows)
                ),
                "chars_truncated": rendered["chars"] < sum(
                    len(row["text"]) for row in rows
                ),
            },
            **rendered,
        }
        try:
            cache.write_text(
                json.dumps(
                    {"transcript": rows, "scope": result["scope"],
                     "kind": "audio", "method": "audio_asr", "url": target},
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)
