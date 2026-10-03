"""Application service for durable, resumable general-web research."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import re
import time
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.domain.runtime_entities import WebLookupRun, new_id, utc_now
from src.news.digest import format_news_source_block
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research_contract import (
    build_research_context,
    failed_attempt,
    successful_attempt,
)
from src.web.research_gateway import ResearchWebGateway
from src.web.source_assessment import assess_sources, evidence_confidence
from src.web.tool_evidence import (
    diagnostic_tool_calls,
    evidence_tool_calls,
    tool_evidence_items,
    trusted_tool_calls,
    tool_call_errors,
    tool_source_items,
)


class WebLookupGateway(Protocol):
    def search(self, query: str, *, max_items: int = 10) -> list[dict[str, Any]]: ...

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]: ...

    def warnings(self) -> list[dict[str, str]]: ...


class ResearchCancelled(RuntimeError):
    pass


_INHERITED_ITEM_FIELDS = (
    "title",
    "url",
    "link",
    "href",
    "published_at",
    "published",
    "date",
    "pubDate",
)
_INHERITED_ASSESSMENT_FIELDS = (
    "source_id",
    "title",
    "url",
    "domain",
    "source_type",
    "relevance",
    "directness",
    "freshness",
    "selected",
    "worth_reading",
)
_FOLLOW_UP_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "what",
        "how",
        "请问",
        "继续",
        "一下",
        "关于",
        "这个",
        "那个",
        "什么",
        "如何",
    }
)


def _canonical_source_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw.rstrip("/").lower()
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and key.lower() not in {"fbclid", "gclid"}
        ]
    )
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/") or "/",
            query,
            "",
        )
    )


def _follow_up_tokens(value: str) -> set[str]:
    normalized = str(value or "").lower()
    latin = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9._+-]{1,}", normalized)
        if token not in _FOLLOW_UP_STOPWORDS
    }
    cjk_runs = re.findall(r"[\u3400-\u9fff]+", normalized)
    cjk = {
        run[index : index + 2]
        for run in cjk_runs
        for index in range(max(0, len(run) - 1))
        if run[index : index + 2] not in _FOLLOW_UP_STOPWORDS
    }
    return latin | cjk


def _safe_inherited_source(record: Any) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    raw_item = record.get("item")
    item: dict[str, Any] = raw_item if isinstance(raw_item, dict) else {}
    raw_assessment = record.get("assessment")
    assessment: dict[str, Any] = (
        raw_assessment if isinstance(raw_assessment, dict) else {}
    )
    safe_item = {
        key: item[key]
        for key in _INHERITED_ITEM_FIELDS
        if key in item and isinstance(item[key], (str, int, float, bool, type(None)))
    }
    safe_assessment = {
        key: assessment[key]
        for key in _INHERITED_ASSESSMENT_FIELDS
        if key in assessment
        and isinstance(assessment[key], (str, int, float, bool, type(None)))
    }
    if not safe_item and not safe_assessment:
        return None
    return {
        "item": safe_item,
        "assessment": safe_assessment,
        "evidence_state": "inherited_candidate",
    }


def _bounded_inherited_notes(parent: WebLookupRun) -> list[dict[str, str]]:
    deep = parent.research_context.get("deep")
    raw_notes = deep.get("notes") if isinstance(deep, dict) else []
    successful_urls = {
        _canonical_source_url(_source_url(record))
        for record in parent.selected_sources
        if isinstance(record.get("read"), dict)
        and record["read"].get("status") == "read"
    }
    notes: list[dict[str, str]] = []
    used_chars = 0
    for raw in raw_notes if isinstance(raw_notes, list) else []:
        if not isinstance(raw, dict) or len(notes) >= 8:
            continue
        url = str(raw.get("url") or "").strip()
        facts = str(raw.get("facts") or "").strip()[:1000]
        if not facts or _canonical_source_url(url) not in successful_urls:
            continue
        remaining = 8000 - used_chars
        if remaining <= 0:
            break
        facts = facts[:remaining]
        notes.append(
            {
                "url": url,
                "title": str(raw.get("title") or url)[:300],
                "facts": facts,
            }
        )
        used_chars += len(facts)
    return notes


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
    del items  # Candidate metadata alone must never enter synthesis context.
    read_items: list[dict[str, Any]] = []
    read_blocks: list[str] = []
    for index, record in enumerate(selected_sources, start=1):
        excerpt = _read_excerpt(record)
        if not excerpt:
            continue
        raw_item = record.get("item")
        item = raw_item if isinstance(raw_item, dict) else {}
        read_items.append(item)
        raw_assessment = record.get("assessment")
        assessment = raw_assessment if isinstance(raw_assessment, dict) else {}
        title = str(item.get("title") or assessment.get("title") or f"来源 {index}")
        url = str(assessment.get("url") or item.get("url") or item.get("link") or "")
        inherited_note = ""
        if record.get("evidence_state") == "revalidated":
            raw_note = record.get("inherited_note")
            if isinstance(raw_note, dict):
                facts = str(raw_note.get("facts") or "").strip()[:1000]
                if facts:
                    inherited_note = f"\n经重新验证的既有笔记：{facts}"
        read_blocks.append(
            f"【已读取 {index}】{title}\n{url}\n{excerpt}{inherited_note}"
        )
    if not read_blocks:
        return ""
    base = format_news_source_block(query, read_items)
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
        planner: Any = None,
    ):
        self.repository = repository
        self.gateway = gateway or ResearchWebGateway()
        # G18: optional deep-research planner. Two callables are expected on
        # the object: ``plan(query, context) -> [sub_question]`` for initial
        # decomposition and ``revise(memo, notes, remaining) ->
        # {"done": bool, "additional": [sub_question]}`` for per-round gap
        # analysis. When absent, deterministic fallbacks are used.
        self.planner = planner

    def create(
        self,
        query: str,
        *,
        max_items: int = 8,
        owner_thread_id: str | None = None,
        owner_turn_id: str | None = None,
        run_kind: str = "standalone",
        research_mode: str = "standard",
        parent_run_id: str | None = None,
        create_request_id: str | None = None,
        suggestion_status: str = "not_checked",
        reader_capabilities: list[str] | None = None,
        reader_session_id: str | None = None,
        reader_setup_url: str | None = None,
    ) -> WebLookupRun:
        normalized = query.strip()
        if not normalized:
            raise ValueError("Web lookup query is required")
        if parent_run_id:
            return self.create_follow_up(
                normalized,
                max_items=max_items,
                owner_thread_id=owner_thread_id,
                owner_turn_id=owner_turn_id,
                parent_run_id=parent_run_id,
                create_request_id=create_request_id,
                suggestion_status=suggestion_status,
            )
        context = build_research_context(normalized).to_dict()
        context.update(
            {
                "source_truth_version": 2,
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
                "run_kind": run_kind,
                "follow_up_suggestion": suggestion_status,
            }
        )
        if research_mode not in {"standard", "deep"}:
            raise ValueError(f"Unsupported research_mode: {research_mode}")
        context["research_mode"] = research_mode
        # §143-P1 transport: express explicit reader-capability intent on the run
        # context. The read site owns routing authority; this layer only records
        # the canonical, adapter-validated declaration (never infers it).
        if reader_capabilities or reader_session_id or reader_setup_url:
            from src.application.reader_task_request import from_request_field

            reader_request = from_request_field(
                {
                    "reader_capabilities": reader_capabilities or [],
                    "session_id": reader_session_id,
                    "setup_url": reader_setup_url,
                }
            )
            if reader_request.reader_capabilities:
                context["reader_capabilities"] = sorted(reader_request.reader_capabilities)
                context["reader_capabilities_source"] = reader_request.hint_source
                context["reader_session_id"] = reader_request.session_id or ""
                context["reader_setup_url"] = reader_request.setup_url or ""
        if research_mode == "deep":
            context["deep"] = {
                "plan": [],
                "round_index": 0,
                "notes": [],
                "memo": "",
                "steering": [],
                "steps": [],
            }
        if owner_thread_id or owner_turn_id:
            context["owner"] = {
                "thread_id": owner_thread_id or "",
                "turn_id": owner_turn_id or "",
            }
        run = WebLookupRun(
            query=normalized,
            stage="planned",
            status="pending",
            research_context=context,
            max_items=max(1, min(int(max_items), 20)),
            owner_thread_id=owner_thread_id or None,
            create_request_id=create_request_id or None,
        )
        return self.repository.create(run)

    def follow_up_candidate(self, *, thread_id: str, query: str) -> dict[str, Any]:
        normalized_thread = thread_id.strip()
        normalized_query = query.strip()
        if not normalized_thread or not normalized_query:
            raise ValueError("Thread ID and follow-up query are required")
        if self.repository.thread_status(normalized_thread) != "active":
            raise ValueError(f"Chat thread is not active: {normalized_thread}")
        query_tokens = _follow_up_tokens(normalized_query)
        if not query_tokens:
            return {"available": False, "reason": "no_relevance_tokens"}
        for run in self.repository.list_by_owner_thread(normalized_thread, limit=50):
            overlap = sorted(query_tokens & _follow_up_tokens(run.query))
            if not overlap:
                continue
            if run.status in {"pending", "running"}:
                return {
                    "available": False,
                    "reason": "active_parent_requires_steering",
                    "parent_run_id": run.id,
                    "parent_query": run.query,
                    "parent_status": run.status,
                    "source_count": len(run.selected_sources),
                    "overlap_tokens": overlap[:12],
                    "steering_required": True,
                }
            if run.status not in {"completed", "partial", "failed", "cancelled"}:
                continue
            if int(run.lineage_summary.get("child_count") or 0) >= 20:
                continue
            deep = run.research_context.get("deep")
            notes = deep.get("notes") if isinstance(deep, dict) else []
            if not run.selected_sources and not (isinstance(notes, list) and notes):
                continue
            inherited_notes = _bounded_inherited_notes(run)
            return {
                "available": True,
                "reason": "deterministic_query_overlap",
                "parent_run_id": run.id,
                "parent_query": run.query,
                "parent_status": run.status,
                "source_count": len(run.selected_sources),
                "note_count": len(inherited_notes),
                "overlap_tokens": overlap[:12],
                "requires_explicit_confirmation": run.status in {"failed", "cancelled"},
            }
        return {"available": False, "reason": "no_related_terminal_run"}

    def create_follow_up(
        self,
        query: str,
        *,
        max_items: int,
        owner_thread_id: str | None,
        owner_turn_id: str | None,
        parent_run_id: str,
        create_request_id: str | None,
        suggestion_status: str = "accepted",
    ) -> WebLookupRun:
        thread_id = str(owner_thread_id or "").strip()
        request_id = str(create_request_id or "").strip()
        if not thread_id or not request_id:
            raise ValueError(
                "Follow-up child requires owner_thread_id and create_request_id"
            )
        parent = self.get(parent_run_id)
        if (
            parent.status in {"failed", "cancelled"}
            and suggestion_status != "accepted"
        ):
            raise ValueError(
                "Failed or cancelled research parent requires explicit confirmation"
            )
        safe_sources = [
            safe
            for record in parent.selected_sources[:20]
            if (safe := _safe_inherited_source(record)) is not None
        ]
        notes = _bounded_inherited_notes(parent)
        notes_by_url = {
            _canonical_source_url(note["url"]): note for note in notes
        }
        for source in safe_sources:
            note = notes_by_url.get(_canonical_source_url(_source_url(source)))
            if note is not None:
                source["inherited_note_seed"] = note
        context = build_research_context(query).to_dict()
        context.update(
            {
                "source_truth_version": 2,
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
                "run_kind": "follow_up",
                "research_mode": "standard",
                "follow_up_suggestion": suggestion_status,
                "owner": {
                    "thread_id": thread_id,
                    "turn_id": owner_turn_id or "",
                },
                "lineage": {
                    "parent_run_id": parent.id,
                    "root_run_id": parent.root_run_id or parent.id,
                    "parent_query": parent.query,
                    "parent_status": parent.status,
                    "inherited_candidates": safe_sources,
                    "inherited_note_count": len(notes),
                    "evidence_counts": {
                        "inherited_candidate": len(safe_sources),
                        "revalidated": 0,
                        "new": 0,
                        "invalid_or_rejected": 0,
                    },
                },
            }
        )
        return self.repository.create_child(
            WebLookupRun(
                query=query,
                stage="planned",
                status="pending",
                research_context=context,
                max_items=max(1, min(int(max_items), 20)),
                owner_thread_id=thread_id,
                parent_run_id=parent.id,
                create_request_id=request_id,
            ),
            max_descendants=20,
        )

    def record_tool_trace(
        self,
        run_id: str,
        *,
        calls: list[dict[str, Any]],
        source_block: str,
        error: str = "",
        operation_id: str | None = None,
    ) -> WebLookupRun:
        operation_id = operation_id or new_id("web_tool")
        run = self.get(run_id)
        if run.status != "running" or run.active_operation_id != operation_id:
            run = self.repository.begin_operation(
                run_id,
                operation_id=operation_id,
                stage="searching",
            )
        display_calls = trusted_tool_calls(calls)
        evidence_calls = evidence_tool_calls(calls)
        provider_errors = tool_call_errors(calls)
        items = tool_source_items(display_calls)
        evidence_items = tool_evidence_items(calls)
        read_urls = {
            _canonical_source_url(
                str(
                    (call.get("result") or {}).get("url")
                    or (call.get("arguments") or {}).get("url")
                    or ""
                )
            )
            for call in evidence_calls
            if call.get("name") == "web_read"
            and isinstance(call.get("result"), dict)
            and isinstance(call.get("arguments"), dict)
        }
        selected_sources = [
            {
                "item": item,
                "assessment": {
                    "url": item.get("url", ""),
                    "title": item.get("title", ""),
                    "worth_reading": True,
                    "selection_reason": (
                        "read_backed_tool_evidence"
                        if _canonical_source_url(str(item.get("url") or "")) in read_urls
                        else "structured_tool_evidence"
                    ),
                },
                "read_status": (
                    "read"
                    if _canonical_source_url(str(item.get("url") or "")) in read_urls
                    else "structured"
                ),
            }
            for item in evidence_items
        ]
        context = {
            **run.research_context,
            "source_truth_version": 2,
            "tool_trace": {
                "calls": display_calls,
                "evidence_calls": evidence_calls,
                "evidence_status": (
                    "read_backed"
                    if evidence_calls
                    else "candidate_only" if display_calls else "empty"
                ),
                "diagnostic_calls": (
                    diagnostic_tool_calls(calls)
                    if len(display_calls) != len(calls)
                    else []
                ),
                "provider_errors": provider_errors,
            },
            "run_attempt": int(run.research_context.get("run_attempt") or 0) + 1,
        }
        attempts = [
            *run.query_attempts,
            {
                "query": run.query,
                "status": "provider_failed" if error else "completed",
                "kind": "chat_tool_loop",
                "run_attempt": context["run_attempt"],
            },
        ]
        if self.repository.cancel_requested(run_id, operation_id=operation_id):
            return self.repository.finish_cancel(run_id, operation_id=operation_id)
        if error or (provider_errors and not display_calls):
            failure = error or "; ".join(provider_errors)
            return self.repository.fail(
                run_id,
                failure,
                research_context=context,
                query_attempts=attempts,
                provider_status="provider_failed",
                stop_reason="chat_tool_loop_failed",
                operation_id=operation_id,
            )
        return self.repository.complete(
            run_id,
            items=items,
            source_block=source_block if evidence_calls else "",
            warnings=provider_errors,
            research_context=context,
            query_attempts=attempts,
            selected_sources=selected_sources,
            rejected_sources=[],
            provider_status=(
                "found"
                if evidence_calls
                else "candidates_only" if display_calls else "empty"
            ),
            stop_reason=(
                "read_backed_tool_evidence_found"
                if evidence_calls
                else "search_candidates_only"
                if display_calls
                else "providers_returned_no_results"
                if calls
                else "no_tool_calls"
            ),
            operation_id=operation_id,
        )

    def begin_tool_trace(self, run_id: str) -> str:
        operation_id = new_id("web_tool")
        self.repository.begin_operation(
            run_id,
            operation_id=operation_id,
            stage="searching",
        )
        return operation_id

    def tool_trace_cancel_requested(self, run_id: str, operation_id: str) -> bool:
        return self.repository.cancel_requested(run_id, operation_id=operation_id)

    def finish_tool_trace_cancel(self, run_id: str, operation_id: str) -> WebLookupRun:
        return self.repository.finish_cancel(run_id, operation_id=operation_id)

    def cancel_owned_by_turn(
        self,
        turn_id: str,
        *,
        wait_seconds: float = 0.0,
    ) -> list[WebLookupRun]:
        normalized = turn_id.strip()
        if not normalized:
            raise ValueError("Owner turn ID is required")
        deadline = time.monotonic() + max(0.0, min(float(wait_seconds), 10.0))
        while True:
            active = [
                run
                for run in self.repository.list_by_owner_turn(normalized)
                if run.status in {"pending", "running", "failed", "partial"}
            ]
            if active:
                return [self.cancel(run.id) for run in active]
            if time.monotonic() >= deadline:
                return []
            time.sleep(0.05)

    def latest_owned_by_turn(self, turn_id: str) -> WebLookupRun | None:
        normalized = turn_id.strip()
        if not normalized:
            raise ValueError("Owner turn ID is required")
        runs = self.repository.list_by_owner_turn(normalized, limit=1)
        return runs[0] if runs else None

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

        if str(context.get("research_mode") or "") == "deep":
            return self._execute_deep(
                run_id,
                run=run,
                stage=stage,
                operation_id=operation_id,
                context=context,
                query_attempts=query_attempts,
                selected_sources=selected_sources,
                rejected_sources=rejected_sources,
                items=items,
                warnings=warnings,
                provider_status=provider_status,
                reason=reason,
                answer_confidence=answer_confidence,
                raise_on_error=raise_on_error,
            )

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
                lineage = context.get("lineage")
                if isinstance(lineage, dict):
                    raw_inherited = lineage.get("inherited_candidates")
                    inherited = [
                        dict(record)
                        for record in raw_inherited
                        if isinstance(record, dict)
                    ] if isinstance(raw_inherited, list) else []
                    inherited_by_url = {
                        _canonical_source_url(_source_url(record)): record
                        for record in inherited
                        if _canonical_source_url(_source_url(record))
                    }
                    matched_urls: set[str] = set()
                    annotated: list[dict[str, Any]] = []
                    for record in selected_sources:
                        current = dict(record)
                        canonical_url = _canonical_source_url(_source_url(current))
                        inherited_record = inherited_by_url.get(canonical_url)
                        if inherited_record is None:
                            current["evidence_state"] = "new"
                        else:
                            matched_urls.add(canonical_url)
                            current["evidence_state"] = "inherited_candidate"
                            seed = inherited_record.get("inherited_note_seed")
                            if isinstance(seed, dict):
                                current["inherited_note_seed"] = dict(seed)
                        annotated.append(current)
                    selected_sources = annotated
                    for canonical_url, inherited_record in inherited_by_url.items():
                        if canonical_url in matched_urls:
                            continue
                        stale = dict(inherited_record)
                        stale["evidence_state"] = "invalid_or_rejected"
                        assessment = dict(stale.get("assessment") or {})
                        assessment["selected"] = False
                        assessment["rejection_reason"] = "inherited_source_not_rediscovered"
                        stale["assessment"] = assessment
                        stale.pop("inherited_note_seed", None)
                        rejected_sources.append(stale)
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
                                **record,
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
                                **record,
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
                        updated_record = {
                            **record,
                            "item": dict(record.get("item") or {}),
                            "assessment": assessment,
                            "read": read_result,
                        }
                        if record.get("evidence_state") == "inherited_candidate":
                            if read_result.get("status") == "read":
                                updated_record["evidence_state"] = "revalidated"
                                seed = updated_record.pop("inherited_note_seed", None)
                                if isinstance(seed, dict):
                                    updated_record["inherited_note"] = seed
                            else:
                                updated_record["evidence_state"] = "invalid_or_rejected"
                                updated_record.pop("inherited_note_seed", None)
                        selected_sources[index] = updated_record
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
                invalid_inherited = [
                    record
                    for record in selected_sources
                    if record.get("evidence_state")
                    in {"inherited_candidate", "invalid_or_rejected"}
                ]
                if invalid_inherited:
                    for record in invalid_inherited:
                        rejected = dict(record)
                        rejected["evidence_state"] = "invalid_or_rejected"
                        assessment = dict(rejected.get("assessment") or {})
                        assessment["selected"] = False
                        assessment["rejection_reason"] = "inherited_source_revalidation_failed"
                        rejected["assessment"] = assessment
                        rejected_sources.append(rejected)
                    selected_sources = [
                        record
                        for record in selected_sources
                        if record.get("evidence_state")
                        not in {"inherited_candidate", "invalid_or_rejected"}
                    ]
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
                successful_reads = int(read_summary.get("successful") or 0)
                if items and successful_reads > 0:
                    provider_status = (
                        "partial"
                        if had_provider_failure or had_read_failure
                        else "found"
                    )
                elif items:
                    provider_status = "candidates_only"
                elif candidate_items:
                    provider_status = "insufficient"
                else:
                    provider_status = "partial" if had_provider_failure else "empty"
                if successful_reads > 0:
                    reason = (
                        "sources_partially_read"
                        if had_read_failure
                        else "sources_read"
                    )
                elif had_read_failure:
                    reason = "source_reading_failed"
                elif provider_status in {"candidates_only", "insufficient"}:
                    reason = "search_candidates_only"
                elif not reason:
                    reason = (
                        "providers_returned_no_results"
                        if provider_status == "empty"
                        else "direct_results_found"
                    )
                answer_confidence = (
                    evidence_confidence(selected_sources)
                    if successful_reads > 0
                    else "none"
                )
                lineage = context.get("lineage")
                if isinstance(lineage, dict):
                    lineage["evidence_counts"] = {
                        "inherited_candidate": sum(
                            1
                            for record in selected_sources
                            if record.get("evidence_state") == "inherited_candidate"
                        ),
                        "revalidated": sum(
                            1
                            for record in selected_sources
                            if record.get("evidence_state") == "revalidated"
                        ),
                        "new": sum(
                            1
                            for record in selected_sources
                            if record.get("evidence_state") == "new"
                        ),
                        "invalid_or_rejected": sum(
                            1
                            for record in rejected_sources
                            if record.get("evidence_state") == "invalid_or_rejected"
                        ),
                    }
                    context["lineage"] = lineage
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


    # ------------------------------------------------------------------
    # G18 deep research: multi-round iterative pipeline (decisions 1-16)
    # ------------------------------------------------------------------

    _DEEP_MAX_ROUNDS_DEFAULT = 4
    _DEEP_MAX_READS_DEFAULT = 16
    _DEEP_MAX_TOTAL_CHARS_DEFAULT = 100_000
    _DEEP_TASKS_PER_ROUND = 2
    _DEEP_PLAN_CAP = 12
    _DEEP_MEMO_CHARS = 8_000
    _DEEP_STEPS_CAP = 200
    _DEEP_NOTE_FACTS_CHARS = 1_200

    def steer(self, run_id: str, *, content: str) -> WebLookupRun:
        """G18 decision 12: inject a mid-run steering message."""
        steered = self.repository.append_steering(run_id, content=content)
        if steered is None:
            raise ValueError(
                f"WebLookupRun cannot be steered (not running): {run_id}"
            )
        return steered

    def _deep_log(self, deep: dict[str, Any], kind: str, text: str) -> None:
        steps = [
            dict(item) for item in deep.get("steps", []) if isinstance(item, dict)
        ]
        steps.append({"at": utc_now(), "kind": kind, "text": text[:300]})
        deep["steps"] = steps[-self._DEEP_STEPS_CAP :]

    def _deep_consume_steering(self, deep: dict[str, Any], round_index: int) -> bool:
        """Mark pending steering as incorporated; True when anything consumed."""
        consumed = False
        for entry in deep.get("steering", []):
            if isinstance(entry, dict) and entry.get("incorporated_in_round") is None:
                entry["incorporated_in_round"] = round_index
                consumed = True
                self._deep_log(
                    deep,
                    "steering",
                    f"研究方向已更新：{str(entry.get('content', ''))[:120]}",
                )
        return consumed

    def _deep_default_plan(
        self, query: str, context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        variants = [
            str(value).strip()
            for value in context.get("query_variants", [])
            if str(value).strip()
        ] or [query.strip()]
        return [
            {
                "task_id": f"t{index + 1}",
                "sub_question": variant,
                "status": "pending",
                "round": None,
            }
            for index, variant in enumerate(variants[: self._DEEP_PLAN_CAP])
        ]

    def _deep_planner_plan(
        self, query: str, context: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        plan_callable = getattr(self.planner, "plan", None)
        if not callable(plan_callable):
            return None
        result = plan_callable(query, context)
        tasks = [
            {
                "task_id": f"t{index + 1}",
                "sub_question": str(item),
                "status": "pending",
                "round": None,
            }
            for index, item in enumerate(result or [])
            if str(item).strip()
        ]
        return tasks or None

    @staticmethod
    def _deep_rewrite_query(sub_question: str) -> str:
        """Retry-once variant (decision 15): strip filler and refocus."""
        rewritten = re.sub(r"[？?！!。.,，\s]+", " ", sub_question or "").strip()
        return rewritten or sub_question

    def _execute_deep(
        self,
        run_id: str,
        *,
        run: WebLookupRun,
        stage: str,
        operation_id: str,
        context: dict[str, Any],
        query_attempts: list[dict[str, Any]],
        selected_sources: list[dict[str, Any]],
        rejected_sources: list[dict[str, Any]],
        items: list[dict[str, Any]],
        warnings: list[str],
        provider_status: str,
        reason: str,
        answer_confidence: str,
        raise_on_error: bool = False,
    ) -> WebLookupRun:
        max_rounds = _env_int(
            "WEB_RESEARCH_MAX_DEEP_ROUNDS",
            self._DEEP_MAX_ROUNDS_DEFAULT,
            minimum=1,
            maximum=5,
        )
        deep_reads = _env_int(
            "WEB_RESEARCH_DEEP_MAX_READS",
            self._DEEP_MAX_READS_DEFAULT,
            minimum=1,
            maximum=40,
        )
        deep_total_chars = _env_int(
            "WEB_RESEARCH_DEEP_MAX_TOTAL_CHARS",
            self._DEEP_MAX_TOTAL_CHARS_DEFAULT,
            minimum=5_000,
            maximum=400_000,
        )
        budget = ResearchReadBudget.from_env()
        deep = dict(context.get("deep") or {})
        plan = [dict(task) for task in deep.get("plan", []) if isinstance(task, dict)]
        notes = [dict(n) for n in deep.get("notes", []) if isinstance(n, dict)]
        memo = str(deep.get("memo") or "")
        round_index = int(deep.get("round_index") or 0)

        def persist() -> WebLookupRun:
            # Local working copies (plan/notes/memo/steps) are rebound or
            # mutated independently; fold them back before every durable
            # checkpoint so nothing accumulated during a round is lost.
            deep["notes"] = notes
            deep["memo"] = memo
            deep["round_index"] = round_index
            deep["plan"] = plan
            context["deep"] = deep
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

        def set_stage(next_stage: str) -> None:
            nonlocal stage
            stage = self.repository.set_stage(
                run_id, stage=next_stage, operation_id=operation_id
            ).stage

        def ensure_active() -> None:
            if self.repository.cancel_requested(run_id, operation_id=operation_id):
                raise ResearchCancelled("Research cancelled by user")

        try:
            ensure_active()

            # ---- planning -------------------------------------------------
            set_stage("planning")
            if not plan:
                planned = self._deep_planner_plan(run.query, context)
                plan = planned or self._deep_default_plan(run.query, context)
                deep["plan"] = plan
            self._deep_log(deep, "planning", f"研究计划已生成（{len(plan)} 个子问题）")
            persist()

            search_method = getattr(self.gateway, "search", None)
            read_method = getattr(self.gateway, "read", None)

            while round_index < max_rounds:
                ensure_active()
                steered_this_round = self._deep_consume_steering(
                    deep, round_index + 1
                )
                pending_tasks = [
                    task
                    for task in plan
                    if isinstance(task, dict) and task.get("status") == "pending"
                ]
                batch = pending_tasks[: self._DEEP_TASKS_PER_ROUND]
                if not batch:
                    break

                round_index += 1
                deep["round_index"] = round_index
                set_stage("searching")
                self._deep_log(
                    deep,
                    "round",
                    f"第 {round_index}/{max_rounds} 轮开始"
                    + ("（含用户转向）" if steered_this_round else ""),
                )
                persist()

                read_state = _read_summary(selected_sources, budget)
                used_chars = int(read_state.get("used_chars") or 0)
                attempted_reads = int(read_state.get("attempted") or 0)

                for task in batch:
                    ensure_active()
                    sub_question = str(task.get("sub_question", ""))
                    queries = [sub_question]
                    rewritten = self._deep_rewrite_query(sub_question)
                    # Decision 15: always retry once, even when the rewrite is
                    # identical (covers transient provider failures).
                    queries.append(rewritten)

                    found_any = False
                    for candidate_query in queries:
                        ensure_active()
                        if not callable(search_method):
                            break
                        try:
                            results = search_method(
                                candidate_query, max_items=run.max_items
                            )
                        except Exception as exc:
                            warnings.append(
                                f"deep search failed ({candidate_query}): {exc}"
                            )
                            results = []
                        payload = successful_attempt(
                            candidate_query, len(results)
                        ).to_dict()
                        payload.update(
                            {
                                "run_attempt": context["run_attempt"],
                                "operation_id": operation_id,
                                "round": round_index,
                                "influenced_by_steering": steered_this_round,
                            }
                        )
                        query_attempts.append(payload)
                        if results:
                            found_any = True
                            for item in results:
                                candidate = dict(item)
                                candidate["round"] = round_index
                                if steered_this_round:
                                    candidate["influenced_by_steering"] = True
                                context.setdefault("candidate_items", []).append(
                                    candidate
                                )
                            persist()
                            break
                    if not found_any:
                        # Decision 15: retry once via rewritten variant happened
                        # above; still nothing → skip this sub-question.
                        task["status"] = "skipped"
                        task["round"] = round_index
                        self._deep_log(
                            deep, "gap", f"子问题无可用结果，跳过：{sub_question[:80]}"
                        )
                        persist()
                        continue

                    # ---- assessing (this task's candidates only) ----------
                    set_stage("assessing")
                    task_candidates = [
                        dict(item)
                        for item in context.get("candidate_items", [])
                        if isinstance(item, dict)
                        and item.get("round") == round_index
                    ]
                    task_selected, task_rejected = assess_sources(
                        task_candidates,
                        canonical_query=str(
                            context.get("canonical_query") or run.query
                        ),
                    )
                    known_urls = {_source_url(record) for record in selected_sources}
                    fresh = [
                        record
                        for record in task_selected
                        if _source_url(record) not in known_urls
                    ]
                    selected_sources.extend(fresh)
                    rejected_sources.extend(task_rejected)
                    items.extend(_selected_items(fresh))
                    persist()

                    # ---- reading + noting ---------------------------------
                    if callable(read_method):
                        set_stage("reading")
                        for record in fresh:
                            ensure_active()
                            url = _source_url(record)
                            if (
                                attempted_reads >= deep_reads
                                or used_chars >= deep_total_chars
                            ):
                                break
                            assessment = dict(record.get("assessment") or {})
                            if assessment.get("worth_reading") is not True or not url:
                                continue
                            source_limit = min(
                                budget.max_chars_per_source,
                                deep_total_chars - used_chars,
                            )
                            try:
                                raw_result = read_method(url, max_chars=source_limit)
                                read_result, _ = _bounded_read_result(
                                    dict(raw_result or {}), max_chars=source_limit
                                )
                                read_result["status"] = (
                                    "read" if _is_read_ok(read_result) else "failed"
                                )
                            except Exception as exc:
                                read_result = {
                                    "ok": False,
                                    "status": "failed",
                                    "url": url,
                                    "error": f"{type(exc).__name__}: {exc}",
                                }
                            attempted_reads += 1
                            facts = str(read_result.get("content") or "")[
                                : self._DEEP_NOTE_FACTS_CHARS
                            ]
                            title = str(
                                (record.get("item") or {}).get("title") or url
                            )
                            note = {
                                "round": round_index,
                                "sub_question": sub_question[:160],
                                "url": url,
                                "title": title,
                                "facts": facts,
                                "influenced_by_steering": bool(
                                    record.get("influenced_by_steering")
                                    or steered_this_round
                                ),
                            }
                            if read_result.get("status") == "read":
                                notes.append(note)
                                used_chars += len(facts)
                                memo = (
                                    (memo + "\n\n" if memo else "")
                                    + f"[R{round_index}] {title}: "
                                    + facts[:300]
                                )
                                memo = memo[-self._DEEP_MEMO_CHARS :]
                                self._deep_log(deep, "read", f"已阅读：{title}")
                            else:
                                warnings.append(
                                    f"deep source read failed ({url}): "
                                    + str(read_result.get("error") or "read_failed")
                                )
                            record_read = dict(record)
                            record_read["read"] = read_result
                            for position, existing_record in enumerate(
                                selected_sources
                            ):
                                if _source_url(existing_record) == url:
                                    selected_sources[position] = record_read
                                    break
                            context["read_summary"] = {
                                **_read_summary(selected_sources, budget),
                                "attempted": attempted_reads,
                            }
                            persist()

                    task["status"] = "done"
                    task["round"] = round_index
                    answer_confidence = evidence_confidence(selected_sources)
                    persist()

                # ---- gap analysis / plan revision (decision 9) ----------
                revise = getattr(self.planner, "revise", None)
                if callable(revise):
                    verdict = revise(memo, notes, [
                        str(task.get("sub_question", ""))
                        for task in plan
                        if isinstance(task, dict) and task.get("status") == "pending"
                    ]) or {}
                    additional = [
                        str(item).strip()
                        for item in verdict.get("additional", [])
                        if str(item).strip()
                    ]
                    for index, sub_question in enumerate(additional):
                        if len(plan) >= self._DEEP_PLAN_CAP:
                            break
                        plan.append(
                            {
                                "task_id": f"a{round_index}_{index + 1}",
                                "sub_question": sub_question,
                                "status": "pending",
                                "round": None,
                            }
                        )
                        self._deep_log(
                            deep, "revise", f"新增子问题：{sub_question[:80]}"
                        )
                    if verdict.get("done"):
                        break
                remaining_pending = any(
                    task.get("status") == "pending"
                    for task in plan
                    if isinstance(task, dict)
                )
                if not remaining_pending:
                    break

            # ---- synthesizing ---------------------------------------------
            ensure_active()
            set_stage("synthesizing")
            items = _selected_items(selected_sources)
            read_summary = _read_summary(selected_sources, ResearchReadBudget.from_env())
            context["read_summary"] = read_summary
            had_provider_failure = any(
                attempt.get("status") == "provider_failed" for attempt in query_attempts
            )
            had_read_failure = int(read_summary.get("failed") or 0) > 0
            candidate_items = context.get("candidate_items", [])
            successful_reads = int(read_summary.get("successful") or 0)
            if items and successful_reads > 0:
                provider_status = (
                    "partial" if had_provider_failure or had_read_failure else "found"
                )
            elif items:
                provider_status = "candidates_only"
            elif candidate_items:
                provider_status = "insufficient"
            else:
                provider_status = "partial" if had_provider_failure else "empty"
            if successful_reads > 0:
                reason = "sources_partially_read" if had_read_failure else "sources_read"
            elif had_read_failure:
                reason = "source_reading_failed"
            elif provider_status in {"candidates_only", "insufficient"}:
                reason = "search_candidates_only"
            answer_confidence = (
                evidence_confidence(selected_sources)
                if successful_reads > 0
                else "none"
            )

            memo_block = ""
            if memo:
                memo_block = f"研究备忘录（滚动更新）：\n{memo}\n\n"
            notes_block = ""
            if notes:
                note_lines = [
                    f"- [{note['title']}]({note['url']}) R{note['round']}"
                    f"{'+steer' if note.get('influenced_by_steering') else ''}: "
                    f"{note['facts'][:200]}"
                    for note in notes[-30:]
                ]
                notes_block = (
                    f"逐页结构化笔记（{len(notes)} 条，最近 30 条）：\n"
                    + "\n".join(note_lines)
                    + "\n\n"
                )
            base_block = _format_research_source_block(
                run.query, items, selected_sources
            )
            source_block = f"{memo_block}{notes_block}{base_block}"

            persist()
            return self.repository.complete(
                run_id,
                operation_id=operation_id,
                items=items,
                source_block=source_block,
                warnings=_dedupe(warnings),
                research_context=context,
                query_attempts=query_attempts,
                selected_sources=selected_sources,
                rejected_sources=rejected_sources,
                provider_status=provider_status,
                stop_reason=reason,
                answer_confidence=answer_confidence,
            )
        except ResearchCancelled:
            return self.repository.finish_cancel(run_id, operation_id=operation_id)
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
