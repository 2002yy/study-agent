"""Shared search source types for the news pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from src.web.models import parse_published_at


@dataclass(frozen=True)
class SearchSourceResult:
    """Normalized output from an optional web search provider."""

    title: str
    url: str
    source: str = "Search Source"
    content: str = ""
    published_at: str = ""
    thumbnail: str = ""
    img_src: str = ""
    favicon: str = ""
    score: float = 0.0

    def to_news_item(self) -> dict:
        published = parse_published_at(self.published_at)
        published_timestamp = published.timestamp() if published else 0.0
        item: dict = {
            "title": self.title.strip(),
            "source": self.source.strip() or "Search Source",
            "published_at": self.published_at.strip() or "Today",
            "published_timestamp": published_timestamp,
            "link": self.url.strip(),
            "resolved_link": "",
            "canonical_url": "",
            "domain": "",
            "resolution_status": "pending",
            "search_excerpt": self.content.strip(),
            "_search_score": self.score,
            "_sort_ts": published_timestamp,
        }
        if self.thumbnail.strip():
            item["search_thumbnail"] = self.thumbnail.strip()
        if self.img_src.strip():
            item["search_img_src"] = self.img_src.strip()
        if self.favicon.strip():
            item["search_favicon"] = self.favicon.strip()
        return item
