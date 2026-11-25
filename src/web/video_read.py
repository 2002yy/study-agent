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
_YT_ID = re.compile(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})")
_PART = re.compile(r"[?&](?:p|page)=(\d+)")
_SUPPORTED_HOSTS = ("bilibili.com", "b23.tv")
_YT_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")
_YT_LANGS = ("zh-Hans", "zh-CN", "zh", "en", "en-US", "en-GB")
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


def _youtube_id(url: str) -> str:
    match = _YT_ID.search(str(url or ""))
    return match.group(1) if match else ""


def _ytdlp_prefix() -> list[str]:
    """yt-dlp plus the operator's proxy, when one is configured."""

    command = ["yt-dlp"]
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    if proxy:
        command.extend(["--proxy", proxy])
    return command


def _youtube_track(meta: dict[str, Any]) -> dict[str, str] | None:
    """Prefer the author's language, then translations; label both honestly."""

    manual = meta.get("subtitles") or {}
    automatic = meta.get("automatic_captions") or {}
    original = str(meta.get("language") or "").split("-")[0].casefold()
    if original:
        for language in manual:
            if language.split("-")[0].casefold() == original:
                return {"kind": "manual", "language": language}
        for language in automatic:
            if language.split("-")[0].casefold() == original:
                return {"kind": "auto", "language": language}
    for language in _YT_LANGS:
        if language in manual:
            family = language.split("-")[0].casefold()
            kind = "manual" if not original or family == original else "manual_translated"
            return {"kind": kind, "language": language}
    for language in _YT_LANGS:
        if language in automatic:
            family = language.split("-")[0].casefold()
            kind = "auto" if not original or family == original else "auto_translated"
            return {"kind": kind, "language": language}
    return None


def _read_youtube(
    url: str, *, max_chars: int, timeout: float,
    max_seconds: int, start_seconds: int,
) -> dict[str, Any]:
    """Subtitles only. No audio download, no ASR, no OCR."""

    video_id = _youtube_id(url)
    if not video_id:
        return _failure(url, "video_unsupported", "not a YouTube video URL")
    if timeout < _MIN_BUDGET:
        return _failure(url, "video_no_budget", "no time left for a video read")
    start = max(0, min(int(start_seconds), 3600))
    seconds = max(15, min(int(max_seconds), _MAX_SECONDS))
    deadline = time.monotonic() + float(timeout)
    remaining = deadline - time.monotonic()
    try:
        done = _run(
            [*_ytdlp_prefix(), "--dump-single-json", "--skip-download", url],
            _meta_timeout(remaining),
        )
    except subprocess.TimeoutExpired:
        return _failure(url, "video_timeout", "metadata lookup timed out")
    if done.returncode != 0 or not (done.stdout or "").strip():
        return _failure(url, "video_unavailable",
                        (done.stderr or "yt-dlp could not read the video")[-300:])
    try:
        meta = json.loads(done.stdout)
    except ValueError:
        return _failure(url, "video_unavailable", "yt-dlp returned invalid metadata")

    track = _youtube_track(meta)
    if track is None:
        # The requirement is explicit: no silent audio download.
        return _failure(url, "video_no_subtitles", "no public subtitles on this video")
    kind, language = track["kind"], track["language"]
    cache = _cache_root() / (
        f"yt-{video_id}-{kind}-{language}-{start}-{seconds}.json"
    )
    cached = _read_cache(cache, max_chars)
    if cached is not None:
        return cached

    work = _cache_root() / f"yt-{video_id}-{kind}-{language}-{start}-{seconds}.work"
    work.mkdir(parents=True, exist_ok=True)
    try:
        remaining = deadline - time.monotonic()
        if remaining < _MIN_BUDGET:
            return _failure(url, "video_no_budget", "no time left for subtitles")
        command = [*_ytdlp_prefix(), "--skip-download", "--sub-langs", language,
                   "--sub-format", "vtt", "-o", str(work / "sub")]
        command.append("--write-subs" if kind == "manual" else "--write-auto-subs")
        command.append(url)
        done = _run(command, remaining)
        path = next(iter(work.glob("sub*.vtt")), None)
        if path is None:
            return _failure(url, "video_no_subtitles",
                            (done.stderr or "subtitle download produced no file")[-300:])
        rows = _parse_vtt(path.read_text(encoding="utf-8", errors="replace"))
        window_end = start + seconds
        rows = [row for row in rows if start <= float(row.get("start") or 0) < window_end]
        rows = _dedupe_cues(rows)
        transcript = _trim(rows, max(500, min(int(max_chars), 40_000)))
        if not transcript:
            return _failure(url, "video_no_transcript", "this section has no subtitle text")
        duration = meta.get("duration")
        result = {
            "ok": True,
            "kind": "video",
            "url": url,
            "platform": "youtube",
            "video_id": video_id,
            "title": str(meta.get("title") or ""),
            "duration": duration,
            "method": "subtitle",
            "subtitle_type": kind,
            "language": language,
            "transcript": transcript,
            "segments": transcript,
            "text": "\n".join(row["text"] for row in transcript),
            "content": _content(transcript, None),
            "chars": sum(len(row["text"]) for row in transcript),
            "sources": {"speech": "subtitle", "ocr": ""},
            "scope": {
                "start": start,
                "seconds": seconds,
                "may_be_partial": bool(duration and duration > window_end),
                "chars_truncated": False,
            },
            "cached": False,
        }
        try:
            cache.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError:
            pass
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


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


def _dedupe_cues(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rolling auto-captions repeat the same line; keep one of each run."""

    out: list[dict[str, Any]] = []
    for row in rows:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        if out and text == out[-1]["text"]:
            out[-1]["end"] = max(out[-1]["end"], row["end"])
            continue
        out.append({"start": row["start"], "end": row["end"], "text": text})
    return out


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
        # Auto captions carry inline <c>/timestamp markup; keep the words.
        line = re.sub(r"<[^>]*>", "", line).strip()
        if line:
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


def _download_section(
    url: str, work: Path, start: int, seconds: int, *,
    video: bool, deadline: float,
) -> dict[str, Any]:
    """One media download for this section; video also serves OCR."""

    remaining = deadline - time.monotonic()
    if remaining < _MIN_BUDGET:
        return {"error_code": "video_no_budget", "error": "no time left for the media"}
    target = work / ("clip.%(ext)s" if video else "audio.%(ext)s")
    fmt = "bv*[height<=480]+ba/b[height<=480]" if video else "ba/b"
    done = _run(
        ["yt-dlp", "--download-sections", f"*{start}-{start + seconds}",
         "-f", fmt, "-o", str(target), url],
        remaining,
    )
    pattern = "clip.*" if video else "audio.*"
    files = [path for path in work.glob(pattern) if path.suffix not in {".part"}]
    if not files:
        return {"error_code": "video_no_audio" if not video else "video_no_media",
                "error": (done.stderr or "no media track")[-300:]}
    return {"path": files[0]}


def _transcribe_media(
    media: Path, work: Path, start: int, deadline: float, language: str = "zh",
) -> dict[str, Any]:
    """Transcribe one bounded clip; audio reads pass ``auto`` for mixed speech."""

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
    remaining = deadline - time.monotonic()
    if remaining < _MIN_BUDGET:
        return {"error_code": "video_no_budget", "error": "no time left for transcription"}
    done = _run(
        [asr_python, script, "--video", str(media), "--out-dir", str(work / "asr"),
         "--language", language],
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


def _ocr_media(
    media: Path, work: Path, start: int, seconds: int, deadline: float,
) -> dict[str, Any]:
    from src.web.video_skill import ocr_transcript

    remaining = deadline - time.monotonic()
    if remaining < _MIN_BUDGET:
        return {"ok": False, "error_code": "video_no_budget",
                "error": "no time left for OCR"}
    result = ocr_transcript(media, work / "ocr", timeout=remaining)
    if not result.get("ok"):
        return result
    shifted = []
    for row in result.get("segments") or []:
        if not isinstance(row, dict):
            continue
        begin = start + float(row.get("start") or 0)
        if start <= begin < start + seconds:
            shifted.append({
                "start": round(begin, 2),
                "end": round(start + float(row.get("end") or 0), 2),
                "text": str(row.get("text") or "").strip(),
            })
    result["segments"] = shifted
    result["text"] = "\n".join(str(row["text"]) for row in shifted)
    return result


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


def _content(transcript: list[dict[str, Any]], ocr: dict[str, Any] | None) -> str:
    """Speech first; burned-in captions are prepended with an explicit label.

    Research briefs and evidence snippets read ``content``; without this the
    OCR text would stay in JSON and never reach the answer context. OCR lines
    keep their timestamps so a caption can be tied to a video interval.
    """

    speech = _project(transcript)
    if not (ocr and ocr.get("ok")):
        return speech
    rows = [row for row in (ocr.get("segments") or []) if isinstance(row, dict)]
    lines = [
        f"[{_clock(float(row.get('start') or 0))}] {str(row.get('text') or '').strip()}"
        for row in rows
        if str(row.get("text") or "").strip()
    ]
    text = "\n".join(lines)[:2000]
    if not text:
        return speech
    return f"[画面字幕 OCR]\n{text}\n\n[语音转写]\n{speech}"


def _meta_timeout(remaining: float) -> float:
    """Metadata may use a slice of the read budget, never all of it."""

    if remaining <= 10:
        return max(1.0, remaining)
    return min(remaining, max(10.0, min(90.0, remaining * 0.4)))


def _apply_ocr(result: dict[str, Any], ocr: dict[str, Any]) -> dict[str, Any]:
    ok = bool(ocr.get("ok"))
    result["ocr"] = ocr if ok else None
    result["ocr_error"] = None if ok else {
        "error": ocr.get("error"),
        "error_code": ocr.get("error_code"),
    }
    sources = dict(result.get("sources") or {})
    sources.setdefault("speech", str(result.get("method") or ""))
    sources["ocr"] = "ocr" if ok else ""
    result["sources"] = sources
    transcript = result.get("transcript")
    if isinstance(transcript, list):
        result["content"] = _content(transcript, ocr)
    return result


def _store_ocr(cache: Path, ocr: dict[str, Any]) -> None:
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    payload = _apply_ocr(payload, ocr)
    try:
        cache.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass


def _read_cache(cache: Path, max_chars: int) -> dict[str, Any] | None:
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = cached.get("transcript")
    if not isinstance(rows, list):
        return None
    transcript = _trim(rows, max(500, min(int(max_chars), 40_000)))
    if not transcript:
        return None
    available = int(cached.get("available_chars") or 0)
    if available <= 0:
        available = sum(len(str(row.get("text") or "").strip())
                        for row in rows if isinstance(row, dict))
    kept = sum(len(row["text"]) for row in transcript)
    scope = dict(cached.get("scope") or {})
    # The cache keeps every row it fetched; this read may still be capped.
    scope["chars_truncated"] = kept < available
    scope["may_be_partial"] = bool(scope.get("may_be_partial") or scope["chars_truncated"])
    cached["scope"] = scope
    cached["transcript"] = transcript
    cached["segments"] = transcript
    cached["text"] = "\n".join(row["text"] for row in transcript)
    cached["content"] = _content(transcript, cached.get("ocr"))
    cached["chars"] = kept
    cached["cached"] = True
    return cached


def read_video(
    url: str, *, max_chars: int = 12_000, timeout: float = 180.0,
    max_seconds: int = 180, start_seconds: int = 0, include_ocr: bool = False,
) -> dict[str, Any]:
    """Return timed transcript rows for one Bilibili video section."""

    target = _public_url(url)
    host = (target.split("/")[2] if target and "//" in target else "").lower()
    if target and any(host == item or host.endswith("." + item) for item in _YT_HOSTS):
        return _read_youtube(
            target, max_chars=max_chars, timeout=timeout,
            max_seconds=max_seconds, start_seconds=start_seconds,
        )
    video_id = _bvid(target or str(url or ""))
    if not target or not video_id:
        return _failure(str(url or ""), "video_unsupported", "not a Bilibili video URL")
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
        if not include_ocr or cached.get("ocr"):
            return cached
        # Speech is already cached. Only the video track and OCR are needed;
        # do not re-download audio or re-run transcription.
        deadline = time.monotonic() + float(timeout)
        work = _cache_root() / f"bili-{video_id}-p{part}-{start}-{seconds}.work"
        work.mkdir(parents=True, exist_ok=True)
        try:
            download = _download_section(
                target, work, start, seconds, video=True, deadline=deadline,
            )
            if "error_code" in download:
                return _apply_ocr(cached, {
                    "ok": False,
                    "error": download.get("error"),
                    "error_code": download["error_code"],
                })
            cached_ocr = _ocr_media(download["path"], work, start, seconds, deadline)
            _store_ocr(cache, cached_ocr)
            return _apply_ocr(cached, cached_ocr)
        finally:
            shutil.rmtree(work, ignore_errors=True)

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
                _meta_timeout(remaining),
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
        if rows:
            # Always clip to the requested window; a 0-second start is still a
            # 60-second window, not "the whole video".
            window_end = start + seconds
            rows = [
                row for row in rows
                if start <= float(row.get("start") or 0) < window_end
            ]
        if not rows:
            media = None
            download = _download_section(
                target, work, start, seconds, video=include_ocr, deadline=deadline,
            )
            if "error_code" in download:
                return _failure(
                    target, download["error_code"], download.get("error") or "media download failed"
                )
            media = download["path"]
            result = _transcribe_media(media, work, start, deadline)
            if "error_code" in result:
                return _failure(target, result["error_code"], result.get("error") or "audio read failed")
            rows = result["rows"]
            method = "sensevoice"
        elif include_ocr:
            media = None
            download = _download_section(
                target, work, start, seconds, video=True, deadline=deadline,
            )
            media = download.get("path")
        else:
            media = None

        ocr: dict[str, Any] | None = None
        if include_ocr:
            if media is None:
                ocr = {"ok": False, "error_code": "video_no_media",
                       "error": "a video track was required for OCR"}
            else:
                ocr = _ocr_media(media, work, start, seconds, deadline)

        full = _trim(rows, 40_000)
        transcript = _trim(full, max(500, min(int(max_chars), 40_000)))
        if not transcript:
            return _failure(target, "video_no_transcript", "the video produced no speech")
        available_chars = sum(
            len(str(row.get("text") or "").strip())
            for row in rows if isinstance(row, dict)
        )
        kept_chars = sum(len(row["text"]) for row in transcript)
        chars_truncated = kept_chars < available_chars
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
            # `segments` + `text` match the local video-study transcript
            # schema, so video_study.py --transcript can consume this directly.
            "segments": transcript,
            "text": "\n".join(row["text"] for row in transcript),
            # The existing evidence path reads `content`; keep one timestamped
            # projection so a video read is citable without a second system.
            "content": _content(transcript, ocr),
            "chars": kept_chars,
            "sources": {
                "speech": method,
                "ocr": "ocr" if (ocr and ocr.get("ok")) else "",
            },
            "scope": {
                "start": start,
                "seconds": seconds,
                "may_be_partial": bool(
                    (duration and duration > start + seconds) or chars_truncated
                ),
                "chars_truncated": chars_truncated,
            },
            "cached": False,
        }
        if include_ocr:
            ocr_ok = bool(ocr and ocr.get("ok"))
            result["ocr"] = ocr if ocr_ok else None
            result["ocr_error"] = None if ocr_ok else {
                "error": (ocr or {}).get("error"),
                "error_code": (ocr or {}).get("error_code"),
            }
        try:
            payload = dict(result)
            payload["transcript"] = full
            payload["available_chars"] = available_chars
            payload.pop("content", None)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError:
            pass
        return result
    finally:
        # Keep the JSON cache, not the downloaded audio.
        shutil.rmtree(work, ignore_errors=True)
