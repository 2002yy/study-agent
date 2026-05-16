from __future__ import annotations

from pathlib import Path


def file_signature(path: Path) -> str:
    """Return a cache-busting signature for a file path (mtime + size)."""
    if not path.is_file():
        return "missing"
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = [line for line in cleaned.splitlines() if not line.startswith("```")]
        cleaned = "\n".join(lines)
    return cleaned
