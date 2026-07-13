"""Application service for durable, recoverable public web research."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.domain.runtime_entities import WebLookupRun, new_id, utc_now
from src.news.digest import format_news_source_block
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.gateway import WebSearchGateway
from src.web.orchestrator import build_search_plan


def _warning_text(item: dict[str, Any]) -> str:
    return ": ".join(
        part
        for part in (
            str(item.get("source", "")).strip(),
            str(item.get("error_type", "")).strip(),
            str(item.get("message", "")).strip(),
        )
        if part
    )


def _dedupe_text(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


class WebLookupService:
    def __init__(
        self,
        repository: WebLookupRepository,
        gateway: WebSearchGateway | None = None,
    ):
        self.repository = repository
        self.gateway = gateway or WebSearchGateway()

    def create(self, query: str, *, max_items: int) -> WebLookupRun:
        normalized = query.strip()
        if not normalized:
            raise ValueError("Web lookup query is required")
        safe_max_items = max(1, min(int(max_items), 20))
        plan = build_search_plan(normalized)
        return self.repository.create(
            WebLookupRun(
                query=normalized,
                stage="planned",
                status="pending",
                query_plan=asdict(plan),
                max_items=safe_max_items,
            )
        )

    def lookup(self, query: str, *, max_items: int) -> WebLookupRun:
        run = self.create(query, max_items=max_items)
        return self.search(run.id, raise_on_error=True)

    def search(
        self,
        run_id: str,
        *,
        raise_on_error: bool = False,
        stale_after_seconds: int = 120,
    ) -> WebLookupRun:
        existing = self.get(run_id)
        if existing.status == "completed":
            raise ValueError(f"WebLookupRun is already completed: {run_id}")
        operation_id = new_id("web_search")
        running = self.repository.begin_search(
            run_id,
            operation_id=operation_id,
            stale_after_seconds=stale_after_seconds,
        )
        started_at = utc_now()
        attempted_queries: list[str] = []
        warnings: list[str] = []
        items: list[dict[str, Any]] = []
        plan_variants = running.query_plan.get("query_variants")
        variants = (
            [str(item) for item in plan_variants if str(item).strip()]
            if isinstance(plan_variants, (list, tuple))
            else []
        )
        if not variants:
            variants = [running.query]
        try:
            for query_variant in variants:
                attempted_queries.append(query_variant)
                items = self.gateway.search(
                    query_variant,
                    max_items=running.max_items,
                )
                warnings.extend(
                    _warning_text(item)
                    for item in self.gateway.warnings()
                    if isinstance(item, dict)
                )
                if items:
                    break
            completed_at = utc_now()
            attempt = {
                "attempt": len(running.attempts) + 1,
                "operation_id": operation_id,
                "status": "completed" if items else "empty",
                "queries": attempted_queries,
                "result_count": len(items),
                "warnings": _dedupe_text(warnings),
                "error": "",
                "started_at": started_at,
                "completed_at": completed_at,
            }
            return self.repository.complete_search(
                run_id,
                operation_id=operation_id,
                items=items,
                source_block=format_news_source_block(running.query, items),
                warnings=_dedupe_text(warnings),
                attempts=[*running.attempts, attempt],
                empty_reason="" if items else "providers_returned_no_results",
            )
        except Exception as exc:
            completed_at = utc_now()
            attempt = {
                "attempt": len(running.attempts) + 1,
                "operation_id": operation_id,
                "status": "failed",
                "queries": attempted_queries,
                "result_count": 0,
                "warnings": _dedupe_text(warnings),
                "error": str(exc),
                "started_at": started_at,
                "completed_at": completed_at,
            }
            failed = self.repository.fail_search(
                run_id,
                operation_id=operation_id,
                error=str(exc),
                warnings=_dedupe_text(warnings),
                attempts=[*running.attempts, attempt],
            )
            if raise_on_error:
                raise
            return failed

    def retry(self, run_id: str) -> WebLookupRun:
        run = self.get(run_id)
        if run.status not in {"pending", "empty", "failed", "running"}:
            raise ValueError(f"WebLookupRun is not retryable: {run_id}")
        return self.search(run_id, raise_on_error=False)

    def get(self, run_id: str) -> WebLookupRun:
        run = self.repository.get(run_id)
        if run is None:
            raise ValueError(f"WebLookupRun not found: {run_id}")
        return run

    def list(self, *, limit: int = 20) -> list[WebLookupRun]:
        return self.repository.list(limit=limit)
