"""Exact git identity binding for RQ1-C qualification artifacts."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_HEX40 = re.compile(r"^[0-9a-f]{40}$")


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("RQ1-C qualification requires a readable git checkout") from exc


def exact_checkout_git_sha(repo_root: Path) -> str:
    """Return exact clean checkout HEAD and fail closed on identity conflicts."""

    head = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip().lower()
    if not _HEX40.fullmatch(head):
        raise RuntimeError("RQ1-C checkout HEAD is not an exact 40-character git sha")

    configured_raw = str(os.getenv("GITHUB_SHA") or "").strip().lower()
    if configured_raw:
        if not _HEX40.fullmatch(configured_raw):
            raise RuntimeError("GITHUB_SHA is present but is not an exact git sha")
        if configured_raw != head:
            raise RuntimeError(
                "GITHUB_SHA does not match the checked-out RQ1-C qualification HEAD"
            )

    tracked_status = _run_git(
        repo_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    ).stdout
    if tracked_status.strip():
        raise RuntimeError(
            "RQ1-C qualification requires a clean tracked checkout at the exact HEAD"
        )

    return head
