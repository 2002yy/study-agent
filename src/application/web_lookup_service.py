"""Application service for durable, resumable general-web research."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from typing import Any, Protocol

from src.domain.runtime_entities import WebLookupRun, new_id
from src.news.digest import format_news_source_block
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research_contract import (
    build_research_context,
    failed_attempt,
    successful_attempt,
)
from src.web.research_gateway import ResearchWebGateway
from src.web.source_assessment import assess_sources, evidence_confidence


class WebLookupGateway(Protocol):
    def search(self, query: str, *, max_items: int = 10) -> list[dict[str, Any]]: ...

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]: ...

    def warnings(self) -> list[dict[str, str]]: ...


class ResearchCancelled(RuntimeError):
    pass


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


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value.strip()))


def _gateway_warning_text(items: list[dict[str, str]]) -> list[str]:
    result: list[str] = []
    for item in items:
        text = ": ".join(
            part
            for part in (
                str(item.get("source", "")).strip(),
                str(item.get("error_type", "")).strip(),
                str(item.get("message", "")).strip(),
            )
            if part
        )
        if text:
            result.append(text)
    return result


def _selected_items(selected_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(record["item"])
        for record in selected_sources
        if isinstance(record.get("item"), dict)
    ]


def _read_summary(
    selected_sources: list[dict[str, Any]],
    budget: ResearchReadBudget,
) -> dict[str, Any]:
    attempted = successful = failed = skipped = used_chars = 0
    for record in selected_sources:
        read = record.get("read")
        if not isinstance(read, dict):
            continue
        status = str(read.get("status") or "")
        if status == "read":
            attempted += 1
            successful += 1
        elif status == "failed":
            attempted += 1
            failed += 1
        elif status == "skipped":
            skipped += 1
        for key in ("content", "readme"):
            value = read.get(key)
            if isinstance(value, str):
                used_chars += len(value)
    return {
        "attempted": attempted,
        "successful": successful,
        "failed": failed,
        "skipped": skipped,
        "used_chars": used_chars,
        "budget": budget.to_dict(),
    }


def _resume_stage(run: WebLookupRun) -> str:
    context = run.research_context
    if run.status == "running" and run.stage in {
        "searching",
        "assessing",
        "reading",
        "synthesizing",
    }:
        return run.stage
    if run.selected_sources:
        needs_read = any(
            isinstance(record.get("assessment"), dict)
            and record["assessment"].get("worth_reading") is True
            and not (
                isinstance(record.get("read"), dict)
                and record["read"].get("status") == "read"
            )
            for record in run.selected_sources
        )
        return "reading" if needs_read else "synthesizing"
    candidate_items = context.get("candidate_items")
    if isinstance(candidate_items, list) and candidate_items:
        return "assessing"
    return "searching"


def stop_reason_from_payloads(attempts: list[dict[str, Any]]) -> str:
    if any(int(attempt.get("result_count") or 0) > 0 for attempt in attempts):
        return "direct_results_found"
    if attempts and all(
        attempt.get("status") == "provider_failed" for attempt in attempts
    ):
        return "providers_failed"
    return "providers_returned_no_results"


class WebLookupService:
    def __init__(
        self,
        repository: WebLookupRepository,
        gateway: WebLookupGateway | None = None,
    ):
        self.repository = repository
        self.gateway = gateway or ResearchWebGateway()

    def create(self, query: str, *, max_items: int = 8) -> WebLookupRun:
        normalized = query.strip()
        if not normalized:
            raise ValueError("Web lookup query is required")
        context = build_research_context(normalized).to_dict()
        context.update(
            {
                "candidate_items": [],
                "read_summary": {
                    "attempted": 0,
                    "successful": 0,
                    "failed": 0,
                    "skipped": 0,
                    "used_chars": 0,
                    "budget": ResearchReadBudget.from_env().to_dict(),
                },
                "run_attempt": 0,
            }
        )
        return self.repository.create(
            WebLookupRun(
                query=normalized,
                stage="planned",
                status="pending",
                research_context=context,
                max_items=max(1, min(int(max_items), 20)),
            )
        )

    def lookup(self, query: str, *, max_items: int) -> WebLookupRun:
        run = self.create(query, max_items=max_items)
        return self.execute(run.id, raise_on_error=True)

    def execute(
        self,
        run_id: str,
        *,
        raise_on_error: bool = False,
        stale_after_seconds: int = 120,
    ) -> WebLookupRun:
        existing = self.get(run_id)
        if existing.status == "completed" and existing.provider_status == "found":
            raise ValueError(f"WebLookupRun is already complete: {run_id}")
        operation_id = new_id("web_research")
        stage = _resume_stage(existing)
        run = self.repository.begin_operation(
            run_id,
            operation_id=operation_id,
            stage=stage,
            stale_after_seconds=stale_after_seconds,
        )
        context = dict(run.research_context)
        context["run_attempt"] = int(context.get("run_attempt") or 0) + 1
        query_attempts = list(run.query_attempts)
        selected_sources = list(run.selected_sources)
        rejected_sources = list(run.rejected_sources)
        items = list(run.items)
        warnings = list(run.warnings)
        provider_status = run.provider_status
        reason = run.stop_reason
        answer_confidence = run.answer_confidence

        def checkpoint() -> WebLookupRun:
            return self.repository.checkpoint(
                run_id,
                operation_id=operation_id,
                research_context=context,
                query_attempts=query_attempts,
                selected_sources=selected_sources,
                rejected_sources=rejected_sources,
                items=items,
                warnings=_dedupe(warnings),
                provider_status=provider_status,
                stop_reason=reason,
                answer_confidence=answer_confidence,
            )

        def ensure_active() -> None:
            if self.repository.cancel_requested(run_id, operation_id=operation_id):
                raise ResearchCancelled("Research cancelled by user")

        try:
            ensure_active()
            if stage == "searching":
                candidate_items: list[dict[str, Any]] = []
                current_attempts: list[dict[str, Any]] = []
                last_error: Exception | None = None
                variants = [
                    str(value)
                    for value in context.get("query_variants", [])
                    if str(value).strip()
                ] or [run.query]
                for search_query in variants:
                    ensure_active()
                    try:
                        results = self.gateway.search(
                            search_query,
                            max_items=run.max_items,
                        )
                        payload = successful_attempt(search_query, len(results)).to_dict()
                        payload.update(
                            {
                                "run_attempt": context["run_attempt"],
                                "operation_id": operation_id,
                            }
                        )
                        query_attempts.append(payload)
                        current_attempts.append(payload)
                        warnings.extend(_gateway_warning_text(self.gateway.warnings()))
                        if results:
                            candidate_items = [dict(item) for item in results]
                            context["candidate_items"] = candidate_items
                            checkpoint()
                            break
                    except Exception as exc:
                        last_error = exc
                        payload = failed_attempt(search_query, exc).to_dict()
                        payload.update(
                            {
                                "run_attempt": context["run_attempt"],
                                "operation_id": operation_id,
                            }
                        )
                        query_attempts.append(payload)
                        current_attempts.append(payload)
                        warnings.append(f"research query failed ({search_query}): {exc}")
                    context["candidate_items"] = candidate_items
                    checkpoint()
                    ensure_active()
                reason = stop_reason_from_payloads(current_attempts)
                if current_attempts and all(
                    attempt.get("status") == "provider_failed"
                    for attempt in current_attempts
                ):
                    error = last_error or RuntimeError("All web lookup providers failed")
                    failed = self.repository.fail(
                        run_id,
                        str(error),
                        research_context=context,
                        query_attempts=query_attempts,
                        provider_status="provider_failed",
                        stop_reason=reason,
                        operation_id=operation_id,
                    )
                    if raise_on_error:
                        raise error
                    return failed
                self.repository.transition_stage(
                    run_id,
                    expected_stage="searching",
                    stage="assessing",
                    operation_id=operation_id,
                )
                stage = "assessing"

            ensure_active()
            if stage == "assessing":
                candidate_items = [
                    dict(item)
                    for item in context.get("candidate_items", [])
                    if isinstance(item, dict)
                ]
                selected_sources, rejected_sources = assess_sources(
                    candidate_items,
                    canonical_query=str(context.get("canonical_query") or run.query),
                )
                items = _selected_items(selected_sources)
                if candidate_items and not items:
                    reason = "insufficient_valid_sources"
                answer_confidence = evidence_confidence(selected_sources)
                checkpoint()
                self.repository.transition_stage(
                    run_id,
                    expected_stage="assessing",
                    stage="reading",
                    operation_id=operation_id,
                )
                stage = "reading"

            ensure_active()
            if stage == "reading":
                read_method = getattr(self.gateway, "read", None)
                budget = ResearchReadBudget.from_env()
                if callable(read_method):
                    for index, record in enumerate(list(selected_sources)):
                        ensure_active()
                        assessment = dict(record.get("assessment") or {})
                        existing_read = record.get("read")
                        if (
                            isinstance(existing_read, dict)
                            and existing_read.get("status") == "read"
                        ):
                            continue
                        summary = _read_summary(selected_sources, budget)
                        url = _source_url(record)
                        if assessment.get("worth_reading") is not True or not url:
                            selected_sources[index] = {
                                "item": dict(record.get("item") or {}),
                                "assessment": assessment,
                                "read": {
                                    "ok": False,
                                    "status": "skipped",
                                    "reason": (
                                        "not_worth_reading"
                                        if assessment.get("worth_reading") is not True
                                        else "missing_url"
                                    ),
                                },
                            }
                            checkpoint()
                            continue
                        if (
                            int(summary["attempted"]) >= budget.max_reads
                            or int(summary["used_chars"]) >= budget.max_total_chars
                        ):
                            selected_sources[index] = {
                                "item": dict(record.get("item") or {}),
                                "assessment": assessment,
                                "read": {
                                    "ok": False,
                                    "status": "skipped",
                                    "reason": "read_budget_exhausted",
                                },
                            }
                            checkpoint()
                            continue
                        remaining = budget.max_total_chars - int(summary["used_chars"])
                        source_limit = min(budget.max_chars_per_source, remaining)
                        try:
                            raw_result = read_method(url, max_chars=source_limit)
                            read_result, _ = _bounded_read_result(
                                dict(raw_result or {}),
                                max_chars=source_limit,
                            )
                            read_result["status"] = (
                                "read" if _is_read_ok(read_result) else "failed"
                            )
                            if not _is_read_ok(read_result):
                                read_reason = str(
                                    read_result.get("error")
                                    or read_result.get("reason")
                                    or "read_failed"
                                )
                                warnings.append(
                                    f"source read failed ({url}): {read_reason}"
                                )
                        except Exception as exc:
                            read_result = {
                                "ok": False,
                                "status": "failed",
                                "url": url,
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                            warnings.append(
                                f"source read failed ({url}): {type(exc).__name__}: {exc}"
                            )
                        selected_sources[index] = {
                            "item": dict(record.get("item") or {}),
                            "assessment": assessment,
                            "read": read_result,
                        }
                        context["read_summary"] = _read_summary(
                            selected_sources,
                            budget,
                        )
                        checkpoint()
                        ensure_active()
                else:
                    context["read_summary"] = _read_summary(
                        selected_sources,
                        ResearchReadBudget.from_env(),
                    )
                    checkpoint()
                self.repository.transition_stage(
                    run_id,
                    expected_stage="reading",
                    stage="synthesizing",
                    operation_id=operation_id,
                )
                stage = "synthesizing"

            ensure_active()
            if stage == "synthesizing":
                items = _selected_items(selected_sources)
                read_summary = _read_summary(
                    selected_sources,
                    ResearchReadBudget.from_env(),
                )
                context["read_summary"] = read_summary
                had_provider_failure = any(
                    attempt.get("status") == "provider_failed"
                    for attempt in query_attempts
                )
                had_read_failure = int(read_summary.get("failed") or 0) > 0
                candidate_items = context.get("candidate_items", [])
                if items:
                    provider_status = (
                        "partial"
                        if had_provider_failure or had_read_failure
                        else "found"
                    )
                elif candidate_items:
                    provider_status = "insufficient"
                else:
                    provider_status = "partial" if had_provider_failure else "empty"
                if int(read_summary.get("successful") or 0) > 0:
                    reason = (
                        "sources_partially_read"
                        if had_read_failure
                        else "sources_read"
                    )
                elif had_read_failure:
                    reason = "source_reading_failed"
                elif not reason:
                    reason = (
                        "providers_returned_no_results"
                        if provider_status == "empty"
                        else "direct_results_found"
                    )
                answer_confidence = evidence_confidence(selected_sources)
                checkpoint()
                return self.repository.complete(
                    run_id,
                    operation_id=operation_id,
                    items=items,
                    source_block=_format_research_source_block(
                        run.query,
                        items,
                        selected_sources,
                    ),
                    warnings=_dedupe(warnings),
                    research_context=context,
                    query_attempts=query_attempts,
                    selected_sources=selected_sources,
                    rejected_sources=rejected_sources,
                    provider_status=provider_status,
                    stop_reason=reason,
                    answer_confidence=answer_confidence,
                )
            raise ValueError(f"Unsupported ResearchRun stage: {stage}")
        except ResearchCancelled:
            return self.repository.finish_cancel(
                run_id,
                operation_id=operation_id,
            )
        except Exception as exc:
            latest = self.get(run_id)
            if latest.status == "running" and latest.active_operation_id == operation_id:
                failed = self.repository.fail(
                    run_id,
                    str(exc),
                    research_context=context,
                    query_attempts=query_attempts,
                    provider_status=(provider_status or "unknown"),
                    stop_reason=(reason or "research_stage_failed"),
                    operation_id=operation_id,
                )
            else:
                failed = latest
            if raise_on_error:
                raise
            return failed

    def retry(self, run_id: str) -> WebLookupRun:
        return self.execute(run_id, raise_on_error=False)

    def resume(self, run_id: str) -> WebLookupRun:
        return self.execute(run_id, raise_on_error=False)

    def cancel(self, run_id: str) -> WebLookupRun:
        return self.repository.request_cancel(run_id)

    def get(self, run_id: str) -> WebLookupRun:
        run = self.repository.get(run_id)
        if run is None:
            raise ValueError(f"WebLookupRun not found: {run_id}")
        return run

    def list(self, *, limit: int = 20) -> list[WebLookupRun]:
        return self.repository.list(limit=limit)
