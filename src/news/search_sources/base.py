"""Shared search source types for the news pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchSourceResult:
    """Normalized output from an optional web search provider."""

    title: str
    url: str
    source: str = "Search Source"
    content: str = ""
    published_at: str = ""

    def to_news_item(self) -> dict:
        return {
            "title": self.title.strip(),
            "source": self.source.strip() or "Search Source",
            "published_at": self.published_at.strip() or "Today",
            "published_timestamp": 0.0,
            "link": self.url.strip(),
            "resolved_link": "",
            "canonical_url": "",
            "domain": "",
            "resolution_status": "pending",
            "search_excerpt": self.content.strip(),
            "_sort_ts": 0.0,
        }
