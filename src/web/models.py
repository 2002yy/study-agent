"""Typed models shared by web search, readers, and evidence building."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def parse_published_at(value: str | int | float | None) -> datetime | None:
    """Parse common provider timestamps into an aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class SearchResult:
    result_id: str
    title: str
    url: str
    canonical_url: str
    provider: str
    source_name: str
    snippet: str = ""
    published_at: datetime | None = None
    language: str = ""
    provider_score: float | None = None


@dataclass(frozen=True)
class ReadResult:
    url: str
    final_url: str
    title: str
    text: str
    reader: str
    content_type: str
    quality_score: float
    elapsed_ms: int
    error_code: str = ""
    attempts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    result_id: str
    text: str
    evidence_type: str
    source_url: str
    title: str
    score: float
