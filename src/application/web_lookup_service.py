"""Application service for durable general-web research lookups."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from typing import Any, Callable, Protocol

from src.domain.runtime_entities import WebLookupRun
from src.news.digest import format_news_source_block
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research_contract import (
    QueryAttempt,
    build_research_context,
    failed_attempt,
    stop_reason,
    successful_attempt,
)
from src.web.research_gateway import ResearchWebGateway
from src.web.source_assessment import assess_sources, evidence_confidence


class WebLookupGateway(Protocol):
    def search(self, query: str, *, max_items: int = 10) -> list[dict[str, Any]]: ...

    def warnings(self) -> list[dict[str, str]]: ...


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


@dataclass(frozen=True)
class ResearchReadBudget:
    max_reads: int = 3
    max_chars_per_source: int = 6000
    max_total_chars: int = 16000

    @classmethod
    def from_env(cls) -> "ResearchReadBudget":
        return cls(
            max_reads=_env_int(
                "WEB_RESEARCH_MAX_READS",
                3,
                minimum=0,
                maximum=8,
            ),
            max_chars_per_source=_env_int(
                "WEB_RESEARCH_MAX_CHARS_PER_SOURCE",
                6000,
                minimum=500,
                maximum=30000,
            ),
            max_total_chars=_env_int(
                "WEB_RESEARCH_MAX_TOTAL_CHARS",
                16000,
                minimum=1000,
                maximum=100000,
            ),
        )

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _source_url(record: dict[str, Any]) -> str:
    assessment = record.get("assessment")
    item = record.get("item")
    if isinstance(assessment, dict) and assessment.get("url"):
        return str(assessment["url"])
    if isinstance(item, dict):
        return str(item.get("url") or item.get("link") or item.get("href") or "")
    return ""


def _is_read_ok(result: dict[str, Any]) -> bool:
    value = result.get("ok")
    return value is True or str(value).strip().lower() == "true"


def _bounded_read_result(
    result: dict[str, Any],
    *,
    max_chars: int,
) -> tuple[dict[str, Any], int]:
    bounded = dict(result)
    used = 0
    for key in ("content", "readme"):
        value = bounded.get(key)
        if not isinstance(value, str):
            continue
        bounded[key] = value[:max_chars]
        used += len(bounded[key])
        if len(value) > max_chars:
            bounded[f"{key}_truncated"] = True
    entries = bounded.get("entries")
    if isinstance(entries, list) and len(entries) > 200:
        bounded["entries"] = entries[:200]
        bounded["entries_truncated"] = True
    return bounded, used


def _read_selected_sources(
    selected_sources: list[dict[str, Any]],
    *,
    read: Callable[..., dict[str, Any]],
    budget: ResearchReadBudget,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    updated: list[dict[str, Any]] = []
    warnings: list[str] = []
    attempted = 0
    successful = 0
    failed = 0
    skipped = 0
    used_chars = 0

    for record in selected_sources:
        item = dict(record.get("item") or {})
        assessment = dict(record.get("assessment") or {})
        next_record: dict[str, Any] = {
            "item": item,
            "assessment": assessment,
        }
        worth_reading = assessment.get("worth_reading") is True
        url = _source_url(record)
        if not worth_reading or not url:
            next_record["read"] = {
                "ok": False,
                "status": "skipped",
                "reason": "not_worth_reading" if not worth_reading else "missing_url",
            }
            skipped += 1
            updated.append(next_record)
            continue
        if attempted >= budget.max_reads or used_chars >= budget.max_total_chars:
            next_record["read"] = {
                "ok": False,
                "status": "skipped",
                "reason": "read_budget_exhausted",
            }
            skipped += 1
            updated.append(next_record)
            continue

        remaining = budget.max_total_chars - used_chars
        source_limit = min(budget.max_chars_per_source, remaining)
        attempted += 1
        try:
            raw_result = read(url, max_chars=source_limit)
            result, consumed = _bounded_read_result(
                dict(raw_result or {}),
                max_chars=source_limit,
            )
            used_chars += consumed
            result["status"] = "read" if _is_read_ok(result) else "failed"
            next_record["read"] = result
            if _is_read_ok(result):
                successful += 1
            else:
                failed += 1
                reason = str(result.get("error") or result.get("reason") or "read_failed")
                warnings.append(f"source read failed ({url}): {reason}")
        except Exception as exc:
            failed += 1
            next_record["read"] = {
                "ok": False,
                "status": "failed",
                "url": url,
                "error": f"{type(exc).__name__}: {exc}",
            }
            warnings.append(f"source read failed ({url}): {type(exc).__name__}: {exc}")
        updated.append(next_record)

    summary = {
        "attempted": attempted,
        "successful": successful,
        "failed": failed,
        "skipped": skipped,
        "used_chars": used_chars,
        "budget": budget.to_dict(),
    }
    return updated, summary, warnings


def _read_excerpt(record: dict[str, Any], *, max_chars: int = 3000) -> str:
    read = record.get("read")
    if not isinstance(read, dict) or not _is_read_ok(read):
        return ""
    content = read.get("content") or read.get("readme")
    if isinstance(content, str) and content.strip():
        return content.strip()[:max_chars]
    entries = read.get("entries")
    if isinstance(entries, list):
        paths = [
            str(entry.get("path") or entry.get("name") or "")
            for entry in entries[:80]
            if isinstance(entry, dict)
        ]
        return "\n".join(path for path in paths if path)[:max_chars]
    return ""


def _format_research_source_block(
    query: str,
    items: list[dict[str, Any]],
    selected_sources: list[dict[str, Any]],
) -> str:
    base = format_news_source_block(query, items)
    read_blocks: list[str] = []
    for index, record in enumerate(selected_sources, start=1):
        excerpt = _read_excerpt(record)
        if not excerpt:
            continue
        item = record.get("item") if isinstance(record.get("item"), dict) else {}
        assessment = (
            record.get("assessment")
            if isinstance(record.get("assessment"), dict)
            else {}
        )
        title = str(item.get("title") or assessment.get("title") or f"来源 {index}")
        url = str(assessment.get("url") or item.get("url") or item.get("link") or "")
        read_blocks.append(f"【已读取 {index}】{title}\n{url}\n{excerpt}")
    if not read_blocks:
        return base
    combined = "\n\n".join(part for part in (base, *read_blocks) if part.strip())
    return combined[:24000]


class WebLookupService:
    def __init__(
        self,
        repository: WebLookupRepository,
        gateway: WebLookupGateway | None = None,
    ):
        self.repository = repository
        self.gateway = gateway or ResearchWebGateway()

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
        candidate_items: list[dict[str, Any]] = []
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

        read_summary: dict[str, Any] = {
            "attempted": 0,
            "successful": 0,
            "failed": 0,
            "skipped": len(selected_sources),
            "used_chars": 0,
            "budget": ResearchReadBudget.from_env().to_dict(),
        }
        read_warnings: list[str] = []
        read_method = getattr(self.gateway, "read", None)
        if callable(read_method) and selected_sources:
            self.repository.transition_stage(
                run.id,
                expected_stage="assessing",
                stage="reading",
            )
            selected_sources, read_summary, read_warnings = _read_selected_sources(
                selected_sources,
                read=read_method,
                budget=ResearchReadBudget.from_env(),
            )
            self.repository.transition_stage(
                run.id,
                expected_stage="reading",
                stage="synthesizing",
            )
        else:
            self.repository.transition_stage(
                run.id,
                expected_stage="assessing",
                stage="synthesizing",
            )

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
        warnings.extend(read_warnings)
        had_provider_failure = any(
            attempt.status == "provider_failed" for attempt in attempts
        )
        had_read_failure = int(read_summary.get("failed") or 0) > 0
        if selected_items:
            provider_status = (
                "partial" if had_provider_failure or had_read_failure else "found"
            )
        elif candidate_items:
            provider_status = "insufficient"
        else:
            provider_status = "partial" if had_provider_failure else "empty"

        if int(read_summary.get("successful") or 0) > 0:
            reason = (
                "sources_partially_read" if had_read_failure else "sources_read"
            )
        elif had_read_failure:
            reason = "source_reading_failed"

        research_context = {
            **context.to_dict(),
            "read_summary": read_summary,
        }
        return self.repository.complete(
            run.id,
            items=selected_items,
            source_block=_format_research_source_block(
                normalized,
                selected_items,
                selected_sources,
            ),
            warnings=warnings,
            research_context=research_context,
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
