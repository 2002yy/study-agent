"""Small feed registry and health-state helpers for Study Agent news sources."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from src.safe_writer import safe_write_text

ROOT = Path(__file__).resolve().parent.parent.parent
FEED_REGISTRY_FILE = ROOT / "config" / "news_feeds.json"
FEED_STATE_FILE = ROOT / "logs" / "news_feed_state.json"


@dataclass(frozen=True)
class FeedDefinition:
    """A configured feed endpoint."""

    name: str
    url: str
    requires_query: bool = False
    filter_by_query: bool = False
    enabled: bool = True

    def resolved_url(self, query_text: str) -> str:
        if self.requires_query:
            return self.url.format(query=quote_plus(query_text))
        return self.url


@dataclass(frozen=True)
class FeedHealth:
    """Persisted health summary for one feed."""

    source: str
    url: str
    status: str
    updated_at: float
    item_count: int = 0
    error_type: str = ""
    message: str = ""
    etag: str = ""
    modified: str = ""


@dataclass(frozen=True)
class FeedState:
    """Persisted state for feed polling and lightweight dedup."""

    health: dict[str, FeedHealth] = field(default_factory=dict)
    seen_entries: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "health": {
                key: asdict(value)
                for key, value in sorted(self.health.items(), key=lambda item: item[0])
            },
            "seen_entries": dict(sorted(self.seen_entries.items())),
        }


DEFAULT_FEEDS = (
    FeedDefinition(
        name="Google News",
        url="https://news.google.com/rss/search?q={query}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        requires_query=True,
    ),
    FeedDefinition(
        name="Bing News",
        url="https://www.bing.com/search?q={query}&format=rss&setlang=zh-hans",
        requires_query=True,
    ),
    FeedDefinition(
        name="Yicai Headline",
        url="https://rsshub.app/yicai/headline",
        filter_by_query=True,
    ),
    FeedDefinition(
        name="Sina Finance China",
        url="https://rsshub.app/sina/finance/china",
        filter_by_query=True,
    ),
    FeedDefinition(
        name="Caijing Roll",
        url="https://rsshub.app/caijing/roll",
        filter_by_query=True,
    ),
)


def _feed_key(source: str, url: str) -> str:
    return f"{source}|{url}"


def load_feed_registry(path: Path = FEED_REGISTRY_FILE) -> list[FeedDefinition]:
    """Load configured feeds or fall back to the built-in defaults."""
    if not path.is_file():
        return list(DEFAULT_FEEDS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return list(DEFAULT_FEEDS)

    feeds: list[FeedDefinition] = []
    for item in raw.get("feeds", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        if not name or not url:
            continue
        feeds.append(
            FeedDefinition(
                name=name,
                url=url,
                requires_query=bool(item.get("requires_query", False)),
                filter_by_query=bool(item.get("filter_by_query", False)),
                enabled=bool(item.get("enabled", True)),
            )
        )
    return feeds or list(DEFAULT_FEEDS)


def registered_feed_urls(query_text: str) -> list[tuple[str, str, bool]]:
    """Return resolved feed URLs in the legacy tuple shape used by rss_fetcher."""
    return [
        (feed.name, feed.resolved_url(query_text), feed.filter_by_query)
        for feed in load_feed_registry()
        if feed.enabled
    ]


def load_feed_state(path: Path = FEED_STATE_FILE) -> FeedState:
    if not path.is_file():
        return FeedState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return FeedState()

    health: dict[str, FeedHealth] = {}
    for key, value in (raw.get("health") or {}).items():
        if not isinstance(value, dict):
            continue
        try:
            health[str(key)] = FeedHealth(
                source=str(value.get("source", "")),
                url=str(value.get("url", "")),
                status=str(value.get("status", "")),
                updated_at=float(value.get("updated_at", 0.0)),
                item_count=int(value.get("item_count", 0)),
                error_type=str(value.get("error_type", "")),
                message=str(value.get("message", "")),
                etag=str(value.get("etag", "")),
                modified=str(value.get("modified", "")),
            )
        except Exception:
            continue

    seen_entries = {
        str(key): float(value)
        for key, value in (raw.get("seen_entries") or {}).items()
        if isinstance(value, int | float)
    }
    return FeedState(health=health, seen_entries=seen_entries)


def save_feed_state(state: FeedState, path: Path = FEED_STATE_FILE) -> None:
    safe_write_text(path, json.dumps(state.to_dict(), ensure_ascii=False, indent=2))


def record_feed_result(
    source: str,
    url: str,
    *,
    ok: bool,
    item_count: int = 0,
    error: Exception | None = None,
    etag: str = "",
    modified: str = "",
    path: Path = FEED_STATE_FILE,
) -> FeedState:
    state = load_feed_state(path)
    health = dict(state.health)
    health[_feed_key(source, url)] = FeedHealth(
        source=source,
        url=url,
        status="ok" if ok else "error",
        updated_at=time.time(),
        item_count=item_count,
        error_type=type(error).__name__ if error is not None else "",
        message=str(error) if error is not None else "",
        etag=etag,
        modified=modified,
    )
    next_state = FeedState(health=health, seen_entries=state.seen_entries)
    save_feed_state(next_state, path)
    return next_state


def entry_key(item: dict) -> str:
    return (
        item.get("canonical_url")
        or item.get("resolved_link")
        or item.get("link")
        or item.get("title")
        or ""
    ).strip().lower()


def mark_seen_entries(
    items: list[dict],
    *,
    path: Path = FEED_STATE_FILE,
    now: float | None = None,
) -> FeedState:
    state = load_feed_state(path)
    seen = dict(state.seen_entries)
    timestamp = time.time() if now is None else now
    for item in items:
        key = entry_key(item)
        if key:
            seen[key] = timestamp
    next_state = FeedState(health=state.health, seen_entries=seen)
    save_feed_state(next_state, path)
    return next_state


def filter_unseen_entries(items: list[dict], state: FeedState) -> list[dict]:
    return [item for item in items if entry_key(item) not in state.seen_entries]


def feed_health_rows(path: Path = FEED_STATE_FILE) -> list[dict[str, Any]]:
    state = load_feed_state(path)
    rows = [asdict(item) for item in state.health.values()]
    return sorted(rows, key=lambda row: (row["source"], row["url"]))
