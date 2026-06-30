"""Application service for direct web lookups."""

from __future__ import annotations

from src.domain.runtime_entities import WebLookupRun
from src.news.digest import format_news_source_block
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.gateway import WebSearchGateway


class WebLookupService:
    def __init__(
        self,
        repository: WebLookupRepository,
        gateway: WebSearchGateway | None = None,
    ):
        self.repository = repository
        self.gateway = gateway or WebSearchGateway()

    def lookup(self, query: str, *, max_items: int) -> WebLookupRun:
        normalized = query.strip()
        if not normalized:
            raise ValueError("Web lookup query is required")
        run = self.repository.create(WebLookupRun(query=normalized))
        try:
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
            return self.repository.complete(
                run.id,
                items=items,
                source_block=format_news_source_block(normalized, items),
                warnings=warnings,
            )
        except Exception as exc:
            self.repository.fail(run.id, str(exc))
            raise

    def get(self, run_id: str) -> WebLookupRun:
        run = self.repository.get(run_id)
        if run is None:
            raise ValueError(f"WebLookupRun not found: {run_id}")
        return run

    def list(self, *, limit: int = 20) -> list[WebLookupRun]:
        return self.repository.list(limit=limit)
