"""Article reader boundary for web results."""

from __future__ import annotations

from src.news.article_fetcher import enrich_news_items_with_article_text


class ArticleReader:
    def enrich(
        self,
        items: list[dict],
        *,
        max_articles: int,
        query_text: str = "",
        max_chars_per_article: int = 5000,
    ) -> list[dict]:
        return enrich_news_items_with_article_text(
            items,
            max_articles=max_articles,
            query_text=query_text,
            max_chars_per_article=max_chars_per_article,
        )
