"""Application service for direct web lookups."""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.runtime_entities import new_id
from src.news.digest import format_news_source_block
from src.web.gateway import WebSearchGateway


@dataclass(frozen=True)
class WebLookupRun:
    id: str
    query: str
    items: list[dict]
    source_block: str
    warnings: list[str]


class WebLookupService:
    def __init__(self, gateway: WebSearchGateway | None = None):
        self.gateway = gateway or WebSearchGateway()

    def lookup(self, query: str, *, max_items: int) -> WebLookupRun:
        normalized = query.strip()
        items = self.gateway.search(normalized, max_items=max_items)
        warnings = [
            ": ".join(
                part
                for part in (
                    str(item.get("source", "")).strip(),
                    str(item.get("error_type", "")).strip(),
                    str(item.get("message", "")).strip(),
                )
                if part
            )
            for item in self.gateway.warnings()
        ]
        return WebLookupRun(
            id=new_id("web_lookup"),
            query=normalized,
            items=items,
            source_block=format_news_source_block(normalized, items),
            warnings=warnings,
        )
