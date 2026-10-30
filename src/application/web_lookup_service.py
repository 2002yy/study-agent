"""Application service for durable, resumable general-web research."""

from __future__ import annotations
from collections.abc import Callable, Mapping

from dataclasses import asdict, dataclass
import os
import re
import time
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.domain.runtime_entities import WebLookupRun, new_id, utc_now
from src.news.digest import format_news_source_block
from src.application.research_shadow_seam import observe_shadow, shadow_enabled
from src.application.shadow_telemetry_sink import shadow_telemetry
from src.repositories.web_lookup_repository import WebLookupRepository
from src.llm_spend_guard import experiment_id, spend_scope
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
from src.web.research_recovery import recovery_summary
from src.web.research.candidate_funnel import candidate_funnel
from src.web.research.incremental_budget import (
    authorize_goal, consume as consume_incremental_budget, initialize_budget,
    load_incremental_policy, remaining as incremental_remaining, total_authorized,
)
from src.tools.python_isolation import isolated_python_available
from src.web.research.interim_analysis import analysis_sources, interim_revision, validate_interim_analysis
from src.web.research.steering_replies import (
    LIFECYCLE_OPEN,
    apply_analysis,
    content_state,
    apply_evidence,
    attribute_analysis,
    find_reply,
    next_content_version,
    reply_id_for_steering,
    research_reply,
    research_reply_id,
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


class _SearchGateway(Protocol):
    """The part of a research gateway this module calls directly."""

    def search(self, query: str, *, max_items: int) -> list[dict[str, Any]]: ...


def _gateway_search(
    gateway: _SearchGateway, query: str, *, max_items: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run one search and return its results together with its own trace.

    The trace has to travel with the call. Fetching it from the gateway
    afterwards is a second read of shared state: another run can search on the
    same gateway in between and its evidence would be persisted against this
    run's answer. Gateways that cannot describe a search report no trace rather
    than borrowing one.
    """

    reader = getattr(gateway, "search_with_trace", None)
    if callable(reader):
        results, trace = reader(query, max_items=max_items)
        return list(results), dict(trace) if isinstance(trace, dict) else {}
    return list(gateway.search(query, max_items=max_items)), {}


def _usable_read_count(records: list[dict[str, Any]]) -> int:
    """Sources whose body was read and whose topic actually matches the query.

    Read success alone is not usable content: a dictionary page or a navigation
    page reads fine and answers nothing. The assessor already classifies that in
    ``directness`` (``weak``/``unmatched``/``unknown`` mean the source shares no
    meaningful topic with the query), so this reuses its judgement instead of
    inventing a second relevance scorer.
    """

    usable = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        raw_read = record.get("read")
        read = raw_read if isinstance(raw_read, dict) else {}
        if str(read.get("status") or "") != "read":
            continue
        raw_assessment = record.get("assessment")
        assessment = raw_assessment if isinstance(raw_assessment, dict) else {}
        if str(assessment.get("directness") or "") in {
            "",
            "weak",
            "unmatched",
            "unknown",
        }:
            continue
        usable += 1
    return usable


def _next_unused_variant(
    context: dict[str, Any], query_attempts: list[dict[str, Any]]
) -> str:
    """The first planned variant this run has not searched yet."""

    variants = [
        str(value)
        for value in context.get("query_variants", []) or []
        if str(value).strip()
    ]
    attempted = {
        str(attempt.get("query") or "")
        for attempt in query_attempts
        if isinstance(attempt, dict)
    }
    for variant in variants:
        if variant not in attempted:
            return variant
    return ""


def _ask_backup_query(
    planner: Callable[[str], str],
    query: str,
    query_attempts: list[dict[str, Any]],
    warnings: list[str],
) -> tuple[str, str]:
    """Ask the semantic planner for one different query; never re-search a used one."""

    attempted = {
        str(attempt.get("query") or "").strip().casefold()
        for attempt in query_attempts
        if isinstance(attempt, dict)
    }
    try:
        candidate = " ".join(str(planner(query) or "").split())
    except Exception as exc:  # noqa: BLE001 - planning is optional, not authoritative
        warnings.append(f"backup query planning failed: {type(exc).__name__}: {exc}")
        return "", ""
    if not candidate or len(candidate) > 400:
        return "", ""
    if candidate.casefold() in attempted:
        return "", ""
    return candidate, "backup_planner"


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


def _observe_lookup_shadow(query: str) -> None:
    """Best-effort, non-blocking, read-only B-Search shadow for the Lookup phase.

    Submitted, never awaited, and its result cannot be read by the research below.
    Flag OFF makes this a no-op, so the production path stays unchanged.
    """
    if not shadow_enabled("lookup"):
        return
    try:
        observe_shadow(phase="lookup", query=query, telemetry=shadow_telemetry())
    except Exception:  # noqa: BLE001 - shadow must never break the main chain
        return


class WebLookupService:
    def __init__(
        self,
        repository: WebLookupRepository,
        gateway: WebLookupGateway | None = None,
        planner: Any = None,
        compute_registry: Any = None,
        backup_query: Callable[[str], str] | None = None,
    ):
        self.repository = repository
        self.gateway = gateway or ResearchWebGateway()
        # Slice B: compute tools reuse the shared tool registry; built lazily so
        # a service without computation never pays for it.
        self._compute_registry = compute_registry
        # G18: optional deep-research planner. Two callables are expected on
        # the object: ``plan(query, context) -> [sub_question]`` for initial
        # decomposition and ``revise(memo, notes, remaining) ->
        # {"done": bool, "additional": [sub_question]}`` for per-round gap
        # analysis. When absent, deterministic fallbacks are used.
        self.planner = planner
        # Search-3A: the deterministic normalizer often yields one query, so a
        # failed first batch can leave nothing to retry. This callable asks the
        # existing semantic planner for one different query wording. It is only
        # called when the retry gate fires, so the normal path spends nothing.
        self.backup_query = backup_query

    @property
    def compute_registry(self) -> Any:
        if self._compute_registry is None:
            from src.tools.registry import create_default_tool_registry

            self._compute_registry = create_default_tool_registry()
        return self._compute_registry

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
        attachment_material: list[dict[str, Any]] | None = None,
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
        # Message-level attachment material: user-provided task material only.
        # It never becomes web evidence and never enters the source block.
        if attachment_material:
            context["attachments"] = [
                {
                    "attachment_id": str(item.get("attachment_id", "")),
                    "filename": str(item.get("filename", "")),
                    "content_hash": str(item.get("content_hash", "")),
                    "text": str(item.get("text", ""))[:4_000],
                }
                for item in attachment_material[:4]
                if str(item.get("text", "")).strip()
            ]
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
        # Research opening ("研究开场"): project the *lookup query plan* into a
        # short, honest direction and persist it with the run so the everyday
        # Lookup path actually shows an opening.  Deterministic, no model call,
        # display-only; a failure keeps the pending seed and never blocks
        # research.  See src/web/research/research_approach.py.
        from src.web.research.research_approach import (
            seed_approach,
            summarize_lookup_query,
        )

        try:
            context["approach"] = summarize_lookup_query(
                query=normalized,
                canonical_query=context.get("canonical_query", ""),
                query_variants=context.get("query_variants") or (),
                entity_aliases=context.get("entity_aliases") or (),
                freshness_requested=bool(context.get("freshness_requested")),
                mode=research_mode,
                turn_id=owner_turn_id or "",
            )
        except Exception:
            context["approach"] = seed_approach(
                mode=research_mode, turn_id=owner_turn_id or ""
            )
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
        # Follow-up children project their **own** query plan into an opening
        # (never the parent's possibly-stale text) so the child run is
        # self-describing; failure keeps the pending seed.
        from src.web.research.research_approach import (
            seed_approach,
            summarize_lookup_query,
        )

        try:
            context["approach"] = summarize_lookup_query(
                query=query,
                canonical_query=context.get("canonical_query", ""),
                query_variants=context.get("query_variants") or (),
                entity_aliases=context.get("entity_aliases") or (),
                freshness_requested=bool(context.get("freshness_requested")),
                mode="standard",
                turn_id=owner_turn_id or "",
            )
        except Exception:
            context["approach"] = seed_approach(
                mode="standard", turn_id=owner_turn_id or ""
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
        semantic_episode: dict[str, Any] | None = None,
        semantic_events: list[dict[str, Any]] | None = None,
    ) -> WebLookupRun:
        explicit_operation = operation_id is not None
        operation_id = operation_id or new_id("web_tool")
        run = self.get(run_id)
        if run.status != "running" or run.active_operation_id != operation_id:
            if explicit_operation:
                raise ResearchCancelled("Stale tool trace operation")
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
            "candidate_dispositions": (recovery_summary(calls) or {}).get("candidate_dispositions", []),
            "candidate_funnel": candidate_funnel(calls, (recovery_summary(calls) or {}).get("candidate_dispositions", [])),
            "tool_trace": {
                "calls": display_calls,
                "evidence_calls": evidence_calls,
                "recovery": recovery_summary(calls),
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
        if semantic_episode is not None:
            from dataclasses import replace
            from src.web.semantic_recovery import ResearchEpisode

            episode = ResearchEpisode.parse(semantic_episode, thread_id=run.owner_thread_id or "")
            if episode.task_id != run.id:
                parent = self.get(episode.source_run_id)
                prior = parent.research_context.get("semantic_episode")
                if parent.owner_thread_id != run.owner_thread_id or parent.version != episode.source_run_version:
                    raise ValueError("Episode source owner/version mismatch")
                if not isinstance(prior, dict) or prior.get("task_id") != episode.task_id or prior.get("original_sha256") != semantic_episode["original_sha256"]:
                    raise ValueError("Episode original identity mismatch")
            context["semantic_episode"] = replace(episode, source_run_id=run.id,
                                                   source_run_version=run.version + 1).to_dict()
        # Absence is a barrier: never revive an older episode behind a newer turn.
        context["semantic_episode_barrier"] = semantic_events is not None
        if semantic_events is not None:
            context["semantic_events"] = semantic_events
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

    def active_semantic_episode(self, thread_id: str):
        from src.web.semantic_recovery import ResearchEpisode

        if not thread_id:
            return None
        for run in self.repository.list_by_owner_thread(thread_id, limit=20):
            if run.research_context.get("run_kind") != "chat_tool_loop":
                continue
            raw = run.research_context.get("semantic_episode")
            if raw is None:
                return None
            try:
                episode = ResearchEpisode.parse(raw, thread_id=thread_id)
                if episode.source_run_id != run.id or episode.source_run_version != run.version:
                    return None
                return episode
            except ValueError:
                return None
        return None

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

    def latest_owned_by_thread(self, thread_id: str) -> WebLookupRun | None:
        """Newest run for a thread.

        Lets the chat stream surface an opening during preparation (before the
        turn id is known to the client) instead of only after the research ends.
        """

        normalized = thread_id.strip()
        if not normalized:
            return None
        runs = self.repository.list_by_owner_thread(normalized, limit=1)
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
            # One paid unit of work: every planner/model call inside this run is
            # charged to this run/operation, so an experiment cap covers the
            # whole sample instead of only the calls that happened to name a key.
            with spend_scope(
                run_id=run_id,
                operation_id=operation_id,
                purpose="deep_research",
                experiment=experiment_id(),
            ):
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

        # M4-B read-only shadow for the Lookup phase: submitted, never awaited, and
        # its result cannot be read by the research below. Flag OFF makes this a no-op.
        _observe_lookup_shadow(run.query)

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
                        results, trace = _gateway_search(
                            self.gateway,
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
                        if trace:
                            # Persisted with the attempt it describes. Read from
                            # the call, never from the gateway: a shared gateway
                            # can serve another run between the search and a
                            # later read.
                            payload["search_trace"] = trace
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
                        failure_trace = getattr(exc, "search_trace", None)
                        if isinstance(failure_trace, dict) and failure_trace:
                            payload["search_trace"] = dict(failure_trace)
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

                def read_source(index: int) -> None:
                    """Read one selected source, inside the run's read budget."""

                    ensure_active()
                    reader = read_method
                    if reader is None:  # pragma: no cover - caller checked
                        return
                    record = selected_sources[index]
                    assessment = dict(record.get("assessment") or {})
                    existing_read = record.get("read")
                    if (
                        isinstance(existing_read, dict)
                        and existing_read.get("status") == "read"
                    ):
                        return
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
                        return
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
                        return
                    remaining = budget.max_total_chars - int(summary["used_chars"])
                    source_limit = min(budget.max_chars_per_source, remaining)
                    try:
                        raw_result = reader(url, max_chars=source_limit)
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
                    from src.web.research.read_evidence import (
                        normalize_read_result,
                        with_attempt_recorded,
                    )

                    read_round = int(context.get("run_round") or 0)
                    read_result = normalize_read_result(
                        read_result,
                        run_id=run_id,
                        url=url,
                        round_index=read_round,
                        record=record,
                        at=utc_now(),
                    )
                    updated_record = with_attempt_recorded(
                        {
                            **record,
                            "item": dict(record.get("item") or {}),
                            "assessment": assessment,
                        },
                        read_result,
                    )
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
                    self._record_read_event(
                        context,
                        run_id=run_id,
                        records=selected_sources,
                        record=updated_record,
                        round_index=int(context.get("run_round") or 0),
                    )
                    context["read_summary"] = _read_summary(
                        selected_sources,
                        budget,
                    )
                    checkpoint()
                    ensure_active()

                if callable(read_method):
                    for index in range(len(list(selected_sources))):
                        read_source(index)

                    # Search-3A: a non-empty result set is not an answer. When
                    # the first query's batch produced no usable content (every
                    # read failed, was skipped as irrelevant, or only reached an
                    # unrelated page), spend one unused query variant instead of
                    # synthesising from junk. Once per run, and only while the
                    # read budget still allows a read: this moves a wasted
                    # opportunity to a better query instead of adding queries.
                    retry_summary = _read_summary(selected_sources, budget)
                    if (
                        not context.get("search_retry")
                        and selected_sources
                        and _usable_read_count(selected_sources) == 0
                        and int(retry_summary["attempted"]) < budget.max_reads
                        and int(retry_summary["used_chars"]) < budget.max_total_chars
                    ):
                        retry_query = _next_unused_variant(context, query_attempts)
                        retry_source = "planned_variant"
                        if not retry_query and self.backup_query is not None:
                            retry_query, retry_source = _ask_backup_query(
                                self.backup_query,
                                run.query,
                                query_attempts,
                                warnings,
                            )
                        if retry_query:
                            context["search_retry"] = {
                                "used": True,
                                "variant": retry_query,
                                "source": retry_source,
                                "reason": "no_usable_read_content",
                            }
                            ensure_active()
                            retry_results: list[dict[str, Any]] = []
                            try:
                                retry_results, retry_trace = _gateway_search(
                                    self.gateway,
                                    retry_query,
                                    max_items=run.max_items,
                                )
                                retry_payload = successful_attempt(
                                    retry_query, len(retry_results)
                                ).to_dict()
                                if retry_trace:
                                    retry_payload["search_trace"] = retry_trace
                            except Exception as exc:
                                retry_payload = failed_attempt(
                                    retry_query, exc
                                ).to_dict()
                                failure_trace = getattr(exc, "search_trace", None)
                                if isinstance(failure_trace, dict) and failure_trace:
                                    retry_payload["search_trace"] = dict(failure_trace)
                                warnings.append(
                                    f"research query failed ({retry_query}): {exc}"
                                )
                            retry_payload.update(
                                {
                                    "run_attempt": context["run_attempt"],
                                    "operation_id": operation_id,
                                }
                            )
                            query_attempts.append(retry_payload)
                            warnings.extend(
                                _gateway_warning_text(self.gateway.warnings())
                            )
                            if retry_results:
                                retry_items = [dict(item) for item in retry_results]
                                context["candidate_items"] = [
                                    dict(item)
                                    for item in context.get("candidate_items", [])
                                    if isinstance(item, dict)
                                ] + retry_items
                                retry_selected, retry_rejected = assess_sources(
                                    retry_items,
                                    canonical_query=str(
                                        context.get("canonical_query") or run.query
                                    ),
                                )
                                first_retry_index = len(selected_sources)
                                existing_urls = {
                                    _canonical_source_url(_source_url(record))
                                    for record in selected_sources
                                }
                                for record in retry_selected:
                                    url_key = _canonical_source_url(_source_url(record))
                                    if url_key and url_key in existing_urls:
                                        continue
                                    selected_sources.append(
                                        {**record, "evidence_state": "new"}
                                    )
                                    if url_key:
                                        existing_urls.add(url_key)
                                rejected_sources.extend(retry_rejected)
                                checkpoint()
                                for index in range(
                                    first_retry_index, len(selected_sources)
                                ):
                                    read_source(index)
                            checkpoint()
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

    def steer(
        self,
        run_id: str,
        *,
        content: str,
        request_id: str | None = None,
        attachment_refs: list[dict[str, Any]] | None = None,
        attachment_material: list[dict[str, Any]] | None = None,
    ) -> WebLookupRun:
        """G18 decision 12: inject a mid-run steering message.

        Text and attachments share one ``request_id`` so a retry is idempotent
        and the attachment can never arrive on an unrelated path.
        """

        steered = self.repository.append_steering(
            run_id,
            content=content,
            request_id=request_id,
            attachment_refs=attachment_refs,
            attachment_material=attachment_material,
        )
        if steered is None:
            raise ValueError(
                f"WebLookupRun cannot be steered (not running): {run_id}"
            )
        return steered

    def _deep_log(self, deep: dict[str, Any], kind: str, text: str) -> None:
        steps = [
            dict(item) for item in deep.get("steps", []) if isinstance(item, dict)
        ]
        # A sequence is durable, so an SSE client can resume from the last id it
        # saw instead of replaying the whole run. It is separate from the list
        # position because the tail is capped.
        next_seq = max((int(item.get("seq") or 0) for item in steps), default=0) + 1
        steps.append(
            {
                "seq": next_seq,
                "at": utc_now(),
                "kind": kind,
                "text": text[:300],
            }
        )
        deep["steps"] = steps[-self._DEEP_STEPS_CAP :]

    def _deep_apply_computation(
        self,
        deep: dict[str, Any],
        *,
        run_id: str,
        round_index: int,
        compute_raw: Any,
        notes: list[dict[str, Any]],
    ) -> None:
        """Run one bounded planner compute decision and bind its result."""

        from src.web.research.computation_step import (
            MAX_COMPUTATIONS,
            ComputeRequestError,
            bind_source_refs,
            execute_compute,
            parse_compute_request,
        )

        try:
            parsed = parse_compute_request(compute_raw)
        except ComputeRequestError as exc:
            self._deep_log(deep, "compute", f"计算请求被拒绝：{exc}")
            return
        if parsed is None:
            return
        if parsed["engine"] == "isolated_python" and incremental_remaining(deep, "python_runs") == 0:
            self._deep_log(deep, "compute", "计算预算不足，隔离 Python 未执行。")
            return
        payload = execute_compute(
            parsed,
            registry=self.compute_registry,
            run_id=run_id,
            tool_run_id=new_id("tool"),
            input_revision=round_index,
            source_refs=bind_source_refs(notes),
        )
        # An execution attempt occupies the compute quota even when it fails or
        # times out; a request that never started (isolation unavailable) does
        # not count as an execution.
        if parsed["engine"] == "isolated_python" and payload.get("status") in {"succeeded", "failed"}:
            consume_incremental_budget(deep, "python_runs")
        entries = [item for item in deep.get("computations", []) if isinstance(item, dict)]
        entries.append({**payload, "round": round_index, "at": utc_now()})
        deep["computations"] = entries[-MAX_COMPUTATIONS:]
        # A recompute supplement is executed *by* the successful computation, so
        # record that execution fact here instead of leaving a false "incorporated
        # but never executed" receipt.
        if payload.get("status") == "succeeded":
            for entry in deep.get("steering", []):
                if (
                    isinstance(entry, dict)
                    and entry.get("kind") == "recompute"
                    and entry.get("incorporated_in_round") == round_index
                    and entry.get("executed_in_round") is None
                ):
                    entry["executed_in_round"] = round_index
        self._deep_log(deep, "compute", f"已执行计算（{payload.get('engine')}）：{payload.get('status')}")

    def _deep_unexecuted_steering(self, deep: dict[str, Any]) -> bool:
        """True when an accepted supplement still has no executed work."""

        return any(
            isinstance(entry, dict)
            and entry.get("incorporated_in_round") is not None
            and entry.get("executed_in_round") is None
            for entry in deep.get("steering", [])
        )

    def _deep_revise_context(
        self, deep: dict[str, Any], context: dict[str, Any], round_index: int
    ) -> dict[str, Any]:
        """Bounded, identity-only context for one revise decision.

        The planner must be able to recognise an accepted supplement (e.g. the
        E1/S1 -> E2/S5 correction) and its material, and see which computation
        versions already exist, without being handed page bodies or answer text.
        """

        steering = []
        understood = {
            str(item.get("steering_id") or "")
            for item in (context.get("steering_replies") or [])
            if isinstance(item, dict) and item.get("analysis_state") == "ready"
        }
        entries = [entry for entry in (deep.get("steering") or []) if isinstance(entry, dict)]
        # Supplements the model has not explained yet come first: a run that
        # accepted four supplements must never silently drop the fourth.
        uncovered = [entry for entry in entries if str(entry.get("id") or "") not in understood]
        # Oldest first: a burst of supplements must not starve the earliest one.
        for entry in (uncovered[:4] if uncovered else entries[-3:]):
            steering.append(
                {
                    "id": str(entry.get("id") or ""),
                    "content": str(entry.get("content", ""))[:300],
                    "kind": entry.get("kind"),
                    "task_id": entry.get("task_id"),
                    "incorporated_in_round": entry.get("incorporated_in_round"),
                    "executed_in_round": entry.get("executed_in_round"),
                    "attachment_ids": [
                        str(item.get("attachment_id"))
                        for item in (entry.get("attachment_material") or [])
                        if isinstance(item, dict) and item.get("attachment_id")
                    ][:4],
                }
            )
        attachments = [
            {
                "attachment_id": str(item.get("attachment_id")),
                "filename": str(item.get("filename"))[:120],
                "content_hash": str(item.get("content_hash"))[:80],
            }
            for item in (context.get("attachments") or [])[:4]
            if isinstance(item, dict) and item.get("attachment_id")
        ]
        computations = [
            {
                "engine": item.get("engine"),
                "status": item.get("status"),
                "input_revision": item.get("input_revision"),
                "tool_run_id": item.get("tool_run_id"),
                "superseded_by_revision": item.get("superseded_by_revision"),
            }
            for item in (deep.get("computations") or [])[-4:]
            if isinstance(item, dict)
        ]
        return {
            "round": round_index,
            "original_query": str(deep.get("original_query") or "")[:400],
            "effective_query": str(deep.get("effective_query") or "")[:400],
            "steering": steering,
            "attachments": attachments,
            "computations": computations,
        }

    def _deep_call_revise(
        self,
        revise: Any,
        memo: str,
        notes: list[dict[str, Any]],
        remaining: list[str],
        revise_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Call revise with the bounded context when the planner accepts it."""

        import inspect

        parameters: dict[str, Any]
        try:
            parameters = dict(inspect.signature(revise).parameters)
        except (TypeError, ValueError):
            parameters = {}
        accepts_context = "context" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        if accepts_context:
            return revise(memo, notes, remaining, context=revise_context) or {}
        return revise(memo, notes, remaining) or {}

    def _deep_consume_steering(
        self, context: dict[str, Any], deep: dict[str, Any], round_index: int, run_id: str
    ) -> bool:
        """Mark pending steering as incorporated; True when anything consumed."""
        consumed = False
        merged_attachments = False
        # Only what this pass really incorporated may affect existing replies:
        # replaying every historical addition would make earlier and later
        # supplements invalidate each other.
        incorporated: list[dict[str, Any]] = []
        for entry in deep.get("steering", []):
            if isinstance(entry, dict) and entry.get("incorporated_in_round") is None:
                # A receipt is applied only when it changes actual future work.
                # Keep existing sources/notes and use the same round/read budgets.
                from src.web.research.steering_plan import revise_deep_plan

                if not revise_deep_plan(deep, entry, query=str(deep.get("original_query") or ""), cap=self._DEEP_PLAN_CAP):
                    continue
                entry["budget_grant"] = authorize_goal(deep, steering_id=str(entry.get("id") or entry.get("received_at")), task_id=entry["task_id"])
                entry["incorporated_in_round"] = round_index
                incorporated.append(
                    {
                        "id": str(entry.get("id") or entry.get("received_at") or ""),
                        "kind": str(entry.get("kind") or ""),
                        "round": round_index,
                    }
                )
                consumed = True
                # Mid-run attachments become task material for the same round,
                # deduped by identity; they never become web evidence.
                material = [
                    item for item in (entry.get("attachment_material") or []) if isinstance(item, dict)
                ]
                if material:
                    existing = context.setdefault("attachments", [])
                    known = {str(item.get("attachment_id") or "") for item in existing}
                    for item in material:
                        if str(item.get("attachment_id") or "") not in known:
                            existing.append(item)
                            known.add(str(item.get("attachment_id") or ""))
                    merged_attachments = True
                self._deep_log(
                    deep,
                    "steering",
                    f"研究方向已更新：{str(entry.get('content', ''))[:120]}",
                )
        if merged_attachments:
            self._deep_log(deep, "attachment", "补充消息中的附件已并入本轮任务材料")
        if consumed:
            self._deep_update_steering_replies(context, deep, run_id, incorporated)
        return consumed

    def _record_read_event(
        self,
        context: dict[str, Any],
        *,
        run_id: str,
        records: list[dict[str, Any]],
        record: dict[str, Any],
        round_index: int,
    ) -> None:
        """Record what one read attempt actually produced.

        One event per attempt: the movement layer must be able to say which read
        brought which material. A skipped page produced no attempt and gets no
        event, and the event never claims the read changed a conclusion.
        """

        from src.web.research.motion_events import record_event
        from src.web.research.read_evidence import build_read_event

        interim = (
            context.get("interim_state")
            if isinstance(context.get("interim_state"), dict)
            else {}
        )
        event = build_read_event(
            run_id=run_id,
            records=records,
            record=record,
            round_index=round_index,
            notes=len((context.get("deep") or {}).get("notes") or [])
            if isinstance(context.get("deep"), dict)
            else 0,
            revision=str(interim.get("revision") or ""),
            at=utc_now(),
        )
        if event is not None:
            record_event(context, event)

    def _apply_motion_conflicts(
        self,
        context: dict[str, Any],
        deep: dict[str, Any],
        verdict: dict[str, Any],
        run_id: str,
        records: list[dict[str, Any]],
    ) -> None:
        """Route the planner's conflict claims through the verified producer.

        The planner may report `conflict_claims`: "these two texts disagree, and
        here is the sentence each side comes from". The shell cannot invent that
        judgement and does not try; it can only refuse it. A claim whose old side
        is not the answer's own text, whose new side does not name a real read, or
        which contradicts an older read produces no event at all.

        Only a verified event withdraws a statement, and it never writes a new
        one: a conflict means "we do not know which is right", which is the
        opposite of a replacement.

        Refusals are kept in the bounded diagnostic trace so a silent no-op can be
        told from a rejected claim.
        """

        claims = verdict.get("conflict_claims") if isinstance(verdict, dict) else None
        if not isinstance(claims, list) or not claims:
            return
        replies = [item for item in (context.get("steering_replies") or []) if isinstance(item, dict)]
        if not replies or not run_id:
            return
        from src.web.research.answer_coordinator import coordinate
        from src.web.research.conflict_producer import ConflictClaim, build_conflict_event
        from src.web.research.motion_events import record_event
        from src.web.research.read_evidence import read_evidence_from_records

        evidence = read_evidence_from_records(records)
        round_index = int(context.get("run_round") or 0)
        notes_count = len(deep.get("notes") or [])
        interim_state = context.get("interim_state")
        revision = (
            str(interim_state.get("revision") or "")
            if isinstance(interim_state, dict)
            else ""
        )
        turn_id = str((context.get("owner") or {}).get("turn_id") or "")
        refusals = [
            item for item in (context.get("motion_refusals") or []) if isinstance(item, dict)
        ]
        for item in claims:
            if not isinstance(item, dict):
                continue
            binding = item.get("source_binding")
            claim = ConflictClaim(
                target_reply_id=str(item.get("target_reply_id") or ""),
                claim=str(item.get("claim") or ""),
                old_quote=str(item.get("old_quote") or ""),
                new_quote=str(item.get("new_quote") or ""),
                new_binding=binding if isinstance(binding, dict) else {},
                old_source_url=str(item.get("old_source_url") or ""),
                condition=str(item.get("condition") or ""),
            )
            event, refusal = build_conflict_event(
                claim,
                replies=replies,
                evidence=evidence,
                run_id=run_id,
                at=utc_now(),
                round_index=round_index,
                notes=notes_count,
                revision=revision,
            )
            if event is None:
                refusals.append(
                    {"target": claim.target_reply_id[:80], "refusal": refusal}
                )
                continue
            result = coordinate(
                replies,
                event,
                now=utc_now(),
                run_id=run_id,
                turn_id=turn_id,
                read_evidence=evidence,
            )
            replies = list(result.replies)
            record_event(context, event)
        context["steering_replies"] = replies
        context["motion_refusals"] = refusals[-20:]

    def _deep_update_steering_replies(
        self,
        context: dict[str, Any],
        deep: dict[str, Any],
        run_id: str,
        incorporated: list[dict[str, Any]],
    ) -> None:
        """Apply the supplements *this pass* incorporated to their replies.

        An addition only marks judgments older than its own round as not covering
        the new condition; a correction supersedes the judgments that spoke about
        the term it replaced.  Classification happens here, where the plan change
        is real, never at receipt time, and history is never replayed.
        """
        replies = list(context.get("steering_replies") or [])
        if not run_id or not replies or not incorporated:
            return
        incorporated_ids = {item["id"] for item in incorporated if item.get("id")}
        corrections = [
            item
            for item in (deep.get("corrections") or [])
            if isinstance(item, dict)
            and str(item.get("steering_id") or "") in incorporated_ids
        ]
        # One writer: the coordinator performs the transition and records the
        # event. It reproduces the legacy result field by field (pairing tests in
        # tests/test_answer_coordinator.py), so this is a convergence, not a
        # semantic change.
        from src.web.research.answer_coordinator import coordinate
        from src.web.research.motion_events import (
            CONDITION_ADDED,
            CONDITION_CORRECTED,
            MotionEvent,
            record_event,
        )

        turn_id = str((context.get("owner") or {}).get("turn_id") or "")
        revision_state = (
            context.get("interim_state") if isinstance(context.get("interim_state"), dict) else {}
        )
        revision = str(revision_state.get("revision") or "")
        notes_count = len(deep.get("notes") or [])
        if corrections:
            event = MotionEvent(
                kind=CONDITION_CORRECTED,
                at=utc_now(),
                round=int(corrections[0].get("round") or 0),
                notes=notes_count,
                revision=revision,
                cause="用户纠正了被替换的术语",
                detail={"old_terms": [str(item.get("old") or "") for item in corrections]},
            )
            result = coordinate(
                replies,
                event,
                now=utc_now(),
                run_id=run_id,
                turn_id=turn_id,
            )
            replies = list(result.replies)
            record_event(context, event)
        for item in incorporated:
            if item.get("kind") != "addition" or not item.get("id"):
                continue
            event = MotionEvent(
                kind=CONDITION_ADDED,
                at=utc_now(),
                round=int(item.get("round") or 0),
                notes=notes_count,
                revision=revision,
                cause="用户追加了新的研究条件",
                detail={
                    "keep_reply_id": reply_id_for_steering(run_id, str(item["id"])),
                    "condition": str(item.get("id") or ""),
                },
            )
            result = coordinate(
                replies,
                event,
                now=utc_now(),
                run_id=run_id,
                turn_id=turn_id,
            )
            replies = list(result.replies)
            record_event(context, event)
        # Record the motion events that caused these state changes. The trace is
        # The events were recorded by the coordinator above, in the same pass that
        # produced the replies; recording them again here would double the trace.
        context["steering_replies"] = replies

    def _deep_publish_steering_replies(
        self,
        context: dict[str, Any],
        deep: dict[str, Any],
        verdict: Mapping[str, Any],
        run_id: str,
        round_index: int,
    ) -> bool:
        """Publish the model's task understanding and sourced provisional judgment.

        Nothing here is authority: the task understanding may only describe the
        task, and a sourced judgment is bound to a supplement only when every
        citation was really read for a question that supplement created.
        """
        turn_id = str((context.get("owner") or {}).get("turn_id") or "")
        if not run_id:
            return False
        now = utc_now()
        replies = list(context.get("steering_replies") or [])
        changed = False
        for understanding in verdict.get("steering_understandings") or []:
            if not isinstance(understanding, dict):
                continue
            reply_id = reply_id_for_steering(
                run_id, str(understanding.get("steering_id") or "")
            )
            current = find_reply(replies, reply_id)
            if current is None or current.get("lifecycle") != LIFECYCLE_OPEN:
                continue
            replies = apply_analysis(
                replies,
                reply_id=reply_id,
                understanding=understanding,
                now=now,
                version=next_content_version(current),
                state=content_state(round_index=round_index, notes=len(deep.get("notes") or [])),
                based_on=int(current.get("content_version") or 0),
            )
            changed = True
        analysis = deep.get("interim_analysis")
        if isinstance(analysis, dict) and str(analysis.get("text") or "").strip():
            target = research_reply_id(run_id)
            for entry in deep.get("steering") or []:
                if not isinstance(entry, dict):
                    continue
                if attribute_analysis(analysis, plan=deep.get("plan") or [], entry=entry):
                    target = reply_id_for_steering(run_id, str(entry.get("id") or ""))
                    break
            current = find_reply(replies, target)
            if current is None and target == research_reply_id(run_id):
                replies.append(research_reply(run_id=run_id, turn_id=turn_id, now=now))
                current = find_reply(replies, target)
            if current is not None and current.get("lifecycle") == LIFECYCLE_OPEN:
                replies = apply_evidence(
                    replies,
                    reply_id=target,
                    analysis=analysis,
                    now=now,
                    version=next_content_version(current),
                    state=content_state(
                        round_index=round_index,
                        notes=len(deep.get("notes") or []),
                        revision=str(analysis.get("revision") or ""),
                    ),
                    based_on=int(current.get("content_version") or 0),
                )
                changed = True
        if changed:
            context["steering_replies"] = replies
        return changed

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
        tasks, _ = self._deep_planner_plan_with_opening(query, context)
        return tasks

    def _deep_planner_plan_with_opening(
        self, query: str, context: dict[str, Any]
    ) -> tuple[list[dict[str, Any]] | None, str]:
        """The plan and the planner's optional general opening (one call)."""

        opening_planner = getattr(self.planner, "plan_with_opening", None)
        plan_callable = getattr(self.planner, "plan", None)
        if callable(opening_planner):
            result, opening = opening_planner(query, context)
        elif callable(plan_callable):
            result, opening = plan_callable(query, context), ""
        else:
            return None, ""
        return self._deep_plan_tasks(result), str(opening or "")

    @staticmethod
    def _deep_plan_tasks(result: Any) -> list[dict[str, Any]] | None:
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

    def _deep_publish_opening(
        self, context: dict[str, Any], run_id: str, text: str
    ) -> None:
        """Publish the planner's general opening as the research reply."""

        from src.web.research.steering_replies import apply_knowledge

        if not run_id or not str(text or "").strip():
            return
        turn_id = str((context.get("owner") or {}).get("turn_id") or "")
        replies = [
            dict(item)
            for item in (context.get("steering_replies") or [])
            if isinstance(item, dict)
        ]
        context["steering_replies"] = apply_knowledge(
            replies, run_id=run_id, turn_id=turn_id, text=text, now=utc_now()
        )

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
        deep["original_query"] = run.query
        context["deep"] = deep
        budget_clock = time.monotonic()
        plan = [dict(task) for task in deep.get("plan", []) if isinstance(task, dict)]
        notes = [dict(n) for n in deep.get("notes", []) if isinstance(n, dict)]
        memo = str(deep.get("memo") or "")
        # Message-level attachments are user-provided task material, not web
        # evidence.  They stay on the research context so planning can use them,
        # but they must never enter the memo/source block or the Evidence Gate.
        attachments = [
            item for item in (context.get("attachments") or []) if isinstance(item, dict)
        ]
        if attachments:
            self._deep_log(
                deep,
                "attachment",
                f"已读取 {len(attachments)} 个消息附件作为任务材料（非网页证据）",
            )
        round_index = int(deep.get("round_index") or 0)
        # A second execution of the same run resumes durable work. The first
        # round of a resumed run has to finish reads an interrupted attempt had
        # already queued (see the reading phase below).
        resumed = int(context.get("run_attempt") or 0) > 1

        def persist() -> WebLookupRun:
            # Local working copies (plan/notes/memo/steps) are rebound or
            # mutated independently; fold them back before every durable
            # checkpoint so nothing accumulated during a round is lost.
            deep["notes"] = notes
            deep["memo"] = memo
            deep["round_index"] = round_index
            deep["plan"] = plan
            context["deep"] = deep
            # Research opening ("研究开场"): project the *real* plan sub-questions
            # into a direction update, persisted inside this same checkpoint so no
            # steering/observation data is lost and a terminal state cannot be
            # overwritten by a late update.
            try:
                from src.web.research.research_approach import summarize_deep_plan

                updated = summarize_deep_plan(
                    query=run.query,
                    sub_questions=[
                        task.get("sub_question")
                        for task in plan
                        if isinstance(task, dict)
                    ],
                    previous=context.get("approach"),
                    turn_id=str((context.get("owner") or {}).get("turn_id") or ""),
                )
                if updated is not None:
                    context["approach"] = updated
            except Exception:
                pass
            saved = self.repository.checkpoint(
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
            # The checkpoint merges steering appended concurrently and returns the
            # post-write row; refresh this executor's local view from it.
            merged_deep = saved.research_context.get("deep")
            if isinstance(merged_deep, dict) and isinstance(
                merged_deep.get("steering"), list
            ):
                deep["steering"] = merged_deep["steering"]
                context["deep"] = deep
            # The checkpoint merges replies written by the API thread; adopt the
            # post-write section so the next version is allocated against durable
            # state instead of a stale local copy.
            merged_replies = saved.research_context.get("steering_replies")
            if isinstance(merged_replies, list):
                context["steering_replies"] = merged_replies
            return saved

        def set_stage(next_stage: str) -> None:
            nonlocal stage
            stage = self.repository.set_stage(
                run_id, stage=next_stage, operation_id=operation_id
            ).stage

        def ensure_active() -> None:
            nonlocal budget_clock
            now = time.monotonic()
            consume_incremental_budget(deep, "wall_seconds", max(0.0, now - budget_clock))
            budget_clock = now
            if self.repository.cancel_requested(run_id, operation_id=operation_id):
                raise ResearchCancelled("Research cancelled by user")

        try:
            ensure_active()

            # ---- planning -------------------------------------------------
            initialize_budget(deep, None if "incremental_budget" in deep else load_incremental_policy(python_isolation_available=isolated_python_available()))
            set_stage("planning")
            opening = ""
            if not plan:
                if callable(getattr(self.planner, "plan", None)):
                    if incremental_remaining(deep, "model_calls") == 0:
                        raise ValueError("Initial planning budget is exhausted")
                    consume_incremental_budget(deep, "model_calls")
                planned, opening = self._deep_planner_plan_with_opening(run.query, context)
                plan = planned or self._deep_default_plan(run.query, context)
                deep["plan"] = plan
            self._deep_publish_opening(context, run_id, opening)
            self._deep_log(deep, "planning", f"研究计划已生成（{len(plan)} 个子问题）")
            persist()

            search_method = getattr(self.gateway, "search", None)
            read_method = getattr(self.gateway, "read", None)

            while round_index < max_rounds or (
                isinstance(deep.get("incremental_budget"), dict) and round_index < 5
                and any(isinstance(entry, dict) and entry.get("incorporated_in_round") is None for entry in deep.get("steering", []))
            ):
                ensure_active()
                steered_this_round = self._deep_consume_steering(
                    context, deep, round_index + 1, run_id
                )
                ledger = deep.get("incremental_budget")
                if isinstance(ledger, dict):
                    deep_reads = min(40, int(total_authorized(ledger, "reads")))
                    deep_total_chars = min(400_000, deep_reads * budget.max_chars_per_source)
                    # Extensions buy only the next task batches, within the
                    # existing global five-round ceiling. No round is reset.
                    max_rounds = min(5, max(max_rounds, round_index + (sum(task.get("status") == "pending" for task in plan) + self._DEEP_TASKS_PER_ROUND - 1) // self._DEEP_TASKS_PER_ROUND))
                    if incremental_remaining(deep, "wall_seconds") == 0:
                        self._deep_log(deep, "budget", "本轮时间预算不足，新增要求尚未执行；可排队到下一轮。")
                        break
                # A correction invalidates only affected evidence. Retain its
                # body in the archive, but do not publish it under the new scope.
                corrections = deep.get("corrections", [])
                affected = [note for note in notes if any(
                    str(change["old"]).casefold() in str(note.get("sub_question", "")).casefold()
                    for change in corrections
                )]
                if affected:
                    affected_urls = {str(note.get("url", "")) for note in affected}
                    deep.setdefault("superseded_notes", []).extend(affected)
                    notes = [note for note in notes if note not in affected]
                    superseded = [record for record in selected_sources if _source_url(record) in affected_urls]
                    deep.setdefault("superseded_sources", []).extend(superseded)
                    selected_sources = [record for record in selected_sources if _source_url(record) not in affected_urls]
                    memo = "\n\n".join(f"[R{note['round']}] {note['title']}: {str(note['facts'])[:300]}" for note in notes)
                pending_tasks = [
                    task
                    for task in plan
                    if isinstance(task, dict) and task.get("status") == "pending"
                ]
                batch = pending_tasks[: self._DEEP_TASKS_PER_ROUND]
                # A steering round must still reach the gap-analysis/compute step
                # even when the supplement adds no new search task (e.g. a pure
                # recompute); otherwise the correction could never take effect.
                if not batch and not steered_this_round:
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
                used_chars = max(int(read_state.get("used_chars") or 0), int(deep.get("consumed_chars") or 0))
                attempted_reads = max(int(read_state.get("attempted") or 0), int(deep.get("consumed_reads") or 0))

                for task in batch:
                    ensure_active()
                    sub_question = str(task.get("sub_question", ""))
                    influenced = bool(task.get("steering_ids"))
                    queries = [sub_question]
                    rewritten = self._deep_rewrite_query(sub_question)
                    # Decision 15: always retry once, even when the rewrite is
                    # identical (covers transient provider failures).
                    queries.append(rewritten)

                    found_any = False
                    for candidate_query in queries:
                        ensure_active()
                        if incremental_remaining(deep, "searches") == 0 or incremental_remaining(deep, "wall_seconds") == 0:
                            self._deep_log(deep, "budget", "检索预算不足，这个研究目标未完成。")
                            break
                        if not callable(search_method):
                            break
                        try:
                            consume_incremental_budget(deep, "searches")
                            for entry in deep.get("steering", []):
                                if str(entry.get("id") or entry.get("received_at")) in task.get("steering_ids", []):
                                    entry["executed_in_round"] = round_index
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
                                "influenced_by_steering": influenced,
                                "steering_ids": list(task.get("steering_ids", [])),
                            }
                        )
                        query_attempts.append(payload)
                        if results:
                            found_any = True
                            for item in results:
                                candidate = dict(item)
                                candidate["round"] = round_index
                                if influenced:
                                    candidate["influenced_by_steering"] = True
                                    candidate["steering_ids"] = list(task.get("steering_ids", []))
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
                        canonical_query=str(deep.get("effective_query") or context.get("canonical_query") or run.query),
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
                        read_targets = list(fresh)
                        if resumed:
                            # A cancelled attempt can persist its selection and
                            # stop before the read. Those records are already in
                            # selected_sources, so the URL de-duplication above
                            # would never queue them again and the retry would
                            # finish knowing only candidate titles.
                            queued = {_source_url(record) for record in read_targets}
                            read_targets.extend(
                                record
                                for record in selected_sources
                                if _source_url(record)
                                and _source_url(record) not in queued
                                and isinstance(record.get("assessment"), dict)
                                and record["assessment"].get("worth_reading") is True
                                and not isinstance(record.get("read"), dict)
                            )
                        for record in read_targets:
                            ensure_active()
                            if incremental_remaining(deep, "reads") == 0 or incremental_remaining(deep, "wall_seconds") == 0:
                                break
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
                                consume_incremental_budget(deep, "reads")
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
                            deep["consumed_reads"] = attempted_reads
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
                                    or influenced
                                ),
                            }
                            note["steering_ids"] = list(task.get("steering_ids", []))
                            if read_result.get("status") == "read":
                                notes.append(note)
                                used_chars += len(facts)
                                deep["consumed_chars"] = used_chars
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
                            from src.web.research.read_evidence import (
                                normalize_read_result,
                                with_attempt_recorded,
                            )

                            read_result = normalize_read_result(
                                read_result,
                                run_id=run_id,
                                url=url,
                                round_index=round_index,
                                record=record,
                                at=utc_now(),
                            )
                            record_read = with_attempt_recorded(dict(record), read_result)
                            for position, existing_record in enumerate(
                                selected_sources
                            ):
                                if _source_url(existing_record) == url:
                                    selected_sources[position] = record_read
                                    break
                            self._record_read_event(
                                context,
                                run_id=run_id,
                                records=selected_sources,
                                record=record_read,
                                round_index=round_index,
                            )
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
                    if incremental_remaining(deep, "model_calls") == 0:
                        self._deep_log(deep, "budget", "规划调用预算不足，保留未完成的研究目标。")
                        break
                    consume_incremental_budget(deep, "model_calls")
                    verdict = self._deep_call_revise(
                        revise,
                        memo,
                        notes,
                        [
                            str(task.get("sub_question", ""))
                            for task in plan
                            if isinstance(task, dict) and task.get("status") == "pending"
                        ],
                        self._deep_revise_context(deep, context, round_index),
                    )
                    analysis = validate_interim_analysis(verdict.get("interim_analysis"), analysis_sources(notes))
                    if analysis is not None:
                        deep["interim_analysis"] = {**analysis, "revision": interim_revision(deep)}
                    else:
                        deep.pop("interim_analysis", None)
                    # Provisional replies: the model's task understanding for each
                    # accepted supplement, plus one sourced judgment bound to a
                    # supplement only when its citations really came from that
                    # supplement's own questions. Persisted before synthesis so a
                    # reader sees it while research is still running.
                    self._deep_publish_steering_replies(
                        context, deep, verdict, run_id, round_index
                    )
                    # Only the model's interpretation can claim a conflict; this
                    # turns a backed claim into a verified event and a withdrawal,
                    # and a paraphrase or an unread page into a refusal.
                    self._apply_motion_conflicts(
                        context, deep, verdict, run_id, selected_sources
                    )
                    persist()
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
                    # Slice B: a bounded compute decision from the planner. Only a
                    # declarative request is accepted; never free-form code.
                    if verdict.get("compute"):
                        self._deep_apply_computation(
                            deep,
                            run_id=run_id,
                            round_index=round_index,
                            compute_raw=verdict["compute"],
                            notes=notes,
                        )
                    pending_steering = any(
                        isinstance(entry, dict) and entry.get("incorporated_in_round") is None
                        for entry in deep.get("steering", [])
                    )
                    # An accepted supplement that has not been executed yet keeps
                    # the run alive: the model's "done" must not override work the
                    # user already had accepted.
                    if (
                        verdict.get("done")
                        and not pending_steering
                        and not self._deep_unexecuted_steering(deep)
                    ):
                        break
                remaining_pending = any(
                    task.get("status") == "pending"
                    for task in plan
                    if isinstance(task, dict)
                )
                pending_steering = any(
                    isinstance(entry, dict) and entry.get("incorporated_in_round") is None
                    for entry in deep.get("steering", [])
                )
                if (
                    not remaining_pending
                    and not pending_steering
                    and not self._deep_unexecuted_steering(deep)
                ):
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

            # The honest terminal report (warning + partial status) is derived in
            # WebLookupRepository.complete from the *merged* context, so a
            # supplement accepted in the last moment is reported too.
            # Replies are frozen by the terminal transition itself (see
            # WebLookupRepository.complete): a checkpoint must never persist a
            # closed reply while the run row is still running.
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
                final_status=None,
            )
        except ResearchCancelled:
            return self.repository.finish_cancel(run_id, operation_id=operation_id)
        except Exception as exc:
            latest = self.get(run_id)
            if latest.status == "running" and latest.active_operation_id == operation_id:
                # A failed run is terminal: WebLookupRepository.fail freezes the
                # replies inside the same atomic status transition.
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
