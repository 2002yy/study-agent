"""Per-read time budgets by resource kind.

A page, a PDF and a spoken-audio clip are different jobs. Giving every read the
same ten seconds makes a normal page slow and a podcast impossible. This module
only answers "how long may this one read take"; the research window remains the
outer cap for the whole run.
"""

from __future__ import annotations

from urllib.parse import urlparse

_AUDIO_SUFFIXES = (
    ".mp3", ".m4a", ".m4b", ".aac", ".wav", ".flac", ".ogg", ".oga", ".opus",
)

PAGE_SECONDS = 10.0
PDF_SECONDS = 30.0
MEDIA_SECONDS = 330.0


def looks_like_media_url(url: str) -> bool:
    """True for a URL whose path ends in a known audio suffix."""

    try:
        path = urlparse(str(url or "")).path.lower()
    except ValueError:
        return False
    return path.endswith(_AUDIO_SUFFIXES)


def looks_like_pdf_url(url: str) -> bool:
    try:
        path = urlparse(str(url or "")).path.lower()
    except ValueError:
        return False
    return path.endswith(".pdf") or "/pdf/" in path


def read_budget_seconds(
    url: str,
    *,
    remaining: float,
    page_seconds: float = PAGE_SECONDS,
    pdf_seconds: float = PDF_SECONDS,
    media_seconds: float = MEDIA_SECONDS,
) -> float:
    """Budget for one read, never beyond the caller's remaining window."""

    if remaining <= 0:
        return 0.0
    if looks_like_media_url(url):
        budget = media_seconds
    elif looks_like_pdf_url(url):
        budget = pdf_seconds
    else:
        budget = page_seconds
    return max(0.1, min(float(budget), float(remaining)))
