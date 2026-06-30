"""Search gateway shared by NewsRun and direct web lookup."""

from __future__ import annotations

from src.news.rss_fetcher import fetch_news_items, get_last_feed_warnings


class WebSearchGateway:
    def search(self, query: str, *, max_items: int = 10) -> list[dict]:
        return fetch_news_items(query_text=query, max_items=max_items)

    def warnings(self) -> list[dict]:
        return get_last_feed_warnings()
