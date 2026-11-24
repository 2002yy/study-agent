"""Thin adapter for the local video-study skill.

Study Agent decides what to read; the skill does the media work (OCR, frames,
transcript checks). This module only invokes its stable entry point and
converts the result, so the pipeline is not reimplemented here.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

_DEFAULT_SCRIPT = (
    r"C:\Users\Zhang\.config\opencode\skills\z-video-study-webpage\scripts\video_study.py"
)


def _skill_script() -> Path:
    return Path(os.getenv("STUDY_AGENT_VIDEO_STUDY", _DEFAULT_SCRIPT))


def _python() -> list[str]:
    raw = os.getenv("STUDY_AGENT_VIDEO_PYTHON", "")
    if raw:
        return [raw]
    return ["py", "-3.12"]


def ocr_transcript(
    video: Path, out_dir: Path, *, timeout: float, interval: float = 3.0,
) -> dict[str, Any]:
    """Read burned-in captions through the skill; no model, no page render."""

    script = _skill_script()
    if not script.exists():
        return {"ok": False, "error_code": "video_ocr_unavailable",
                "error": "video_study.py is not installed"}
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    try:
        done = subprocess.run(
            [*_python(), str(script), "--video", str(video), "--out-dir", str(out_dir),
             "--ocr-subtitles", "--ocr-interval", str(interval),
             "--skip-transcribe", "--mock-analysis", "--ocr-engine", "auto"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=max(5, int(timeout)), env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_code": "video_ocr_timeout",
                "error": "the OCR pipeline timed out"}
    path = out_dir / "transcript-ocr.json"
    if not path.exists():
        return {"ok": False, "error_code": "video_ocr_failed",
                "error": (done.stderr or "OCR produced no transcript")[-300:]}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error_code": "video_ocr_failed",
                "error": "OCR transcript is not valid JSON"}
    segments = []
    for row in data.get("segments") or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        segments.append({
            "start": round(float(row.get("start") or 0), 2),
            "end": round(float(row.get("end") or 0), 2),
            "text": text,
        })
    if not segments:
        return {"ok": False, "error_code": "video_ocr_empty",
                "error": "no burned-in caption was read"}
    return {
        "ok": True,
        "source": "ocr",
        "engine": str(data.get("engine") or ""),
        "segments": segments,
        "text": "\n".join(row["text"] for row in segments),
        "samples": int(data.get("samples") or 0),
        "completeness": data.get("completeness") or {},
        "chart_rows": data.get("chart_rows") or [],
    }
