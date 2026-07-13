"""Application service for direct web lookups."""

from __future__ import annotations

from src.domain.runtime_entities import WebLookupRun
from src.news.digest import format_news_source_block
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.gateway import WebSearchGateway
from src.web.research_contract import (
    QueryAttempt,
    build_research_context,
    failed_attempt,
    successful_attempt,
)


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

        context = build_research_context(normalized)
        run = self.repository.create(WebLookupRun(query=normalized))
        attempts: list[QueryAttempt] = []
        items: list[dict] = []
        attempt_warnings: list[str] = []
        last_error: Exception | None = None

        for search_query in context.query_variants:
            try:
                candidate_items = self.gateway.search(
                    search_query,
                    max_items=max_items,
                )
                attempts.append(successful_attempt(search_query, len(candidate_items)))
                if candidate_items:
                    items = candidate_items
                    break
            except Exception as exc:
                last_error = exc
                attempts.append(failed_attempt(search_query, exc))
                attempt_warnings.append(
                    f"research query failed ({search_query}): {exc}"
                )

        if attempts and all(attempt.status == "provider_failed" for attempt in attempts):
            error = last_error or RuntimeError("All web lookup providers failed")
            self.repository.fail(run.id, str(error))
            raise error

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
        warnings.extend(attempt_warnings)

        return self.repository.complete(
            run.id,
            items=items,
            source_block=format_news_source_block(normalized, items),
            warnings=warnings,
        )

    def get(self, run_id: str) -> WebLookupRun:
        run = self.repository.get(run_id)
        if run is None:
            raise ValueError(f"WebLookupRun not found: {run_id}")
        return run

    def list(self, *, limit: int = 20) -> list[WebLookupRun]:
        return self.repository.list(limit=limit)
