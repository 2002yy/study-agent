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
    stop_reason,
    successful_attempt,
)
from src.web.source_assessment import assess_sources, evidence_confidence


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
        run = self.repository.create(
            WebLookupRun(
                query=normalized,
                stage="searching",
                research_context=context.to_dict(),
            )
        )
        attempts: list[QueryAttempt] = []
        candidate_items: list[dict] = []
        attempt_warnings: list[str] = []
        last_error: Exception | None = None

        for search_query in context.query_variants:
            try:
                results = self.gateway.search(
                    search_query,
                    max_items=max_items,
                )
                attempts.append(successful_attempt(search_query, len(results)))
                if results:
                    candidate_items = results
                    break
            except Exception as exc:
                last_error = exc
                attempts.append(failed_attempt(search_query, exc))
                attempt_warnings.append(
                    f"research query failed ({search_query}): {exc}"
                )

        attempt_payload = [attempt.to_dict() for attempt in attempts]
        reason = stop_reason(attempts)
        if attempts and all(attempt.status == "provider_failed" for attempt in attempts):
            error = last_error or RuntimeError("All web lookup providers failed")
            self.repository.fail(
                run.id,
                str(error),
                research_context=context.to_dict(),
                query_attempts=attempt_payload,
                provider_status="provider_failed",
                stop_reason=reason,
            )
            raise error

        self.repository.transition_stage(
            run.id,
            expected_stage="searching",
            stage="assessing",
        )
        selected_sources, rejected_sources = assess_sources(
            candidate_items,
            canonical_query=context.canonical_query,
        )
        selected_items = [
            dict(record["item"])
            for record in selected_sources
            if isinstance(record.get("item"), dict)
        ]
        if candidate_items and not selected_items:
            reason = "insufficient_valid_sources"

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
        had_provider_failure = any(
            attempt.status == "provider_failed" for attempt in attempts
        )
        if selected_items:
            provider_status = "partial" if had_provider_failure else "found"
        elif candidate_items:
            provider_status = "insufficient"
        else:
            provider_status = "partial" if had_provider_failure else "empty"

        return self.repository.complete(
            run.id,
            items=selected_items,
            source_block=format_news_source_block(normalized, selected_items),
            warnings=warnings,
            research_context=context.to_dict(),
            query_attempts=attempt_payload,
            selected_sources=selected_sources,
            rejected_sources=rejected_sources,
            provider_status=provider_status,
            stop_reason=reason,
            answer_confidence=evidence_confidence(selected_sources),
        )

    def get(self, run_id: str) -> WebLookupRun:
        run = self.repository.get(run_id)
        if run is None:
            raise ValueError(f"WebLookupRun not found: {run_id}")
        return run

    def list(self, *, limit: int = 20) -> list[WebLookupRun]:
        return self.repository.list(limit=limit)
