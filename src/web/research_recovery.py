"""Bounded search/read recovery. Relevance is not semantic support or truth."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
import time
from typing import Any, Callable
from urllib.parse import urlparse

from src.web.source_assessment import assess_sources
from src.web.recovery_candidates import CandidateScheduler
from src.web.tool_evidence import _public_url, evidence_tool_calls


class RecoveryCancelled(RuntimeError):
    pass


class RecoveryDeadline(TimeoutError):
    """The research window ended; provider timeouts are separately recoverable."""


@dataclass(frozen=True)
class RecoveryBudget:
    mode: str
    hard_seconds: float
    finalization_reserve: float
    base_reads: int
    recovery_reads: int
    max_queries: int
    max_source_chars: int
    max_total_chars: int

    @property
    def max_reads(self) -> int:
        return self.base_reads + self.recovery_reads


LOOKUP_BUDGET = RecoveryBudget("lookup", 30, 10, 2, 1, 2, 6000, 16000)
STANDARD_BUDGET = RecoveryBudget("standard", 60, 12, 3, 2, 4, 6000, 24000)


def recovery_summary(calls: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next(
        (
            dict(call["result"])
            for call in reversed(calls)
            if call.get("name") == "research_recovery"
            and isinstance(call.get("result"), dict)
        ),
        None,
    )


def model_targets(query: str) -> list[tuple[str, str]]:
    # Unicode word boundaries would miss names immediately next to Chinese.
    return list(
        dict.fromkeys(
            (m.group(1), m.group(2))
            for m in re.finditer(
                r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z_-]*?)[\s_-]*(\d+(?:\.\d+)+)(?![\d.])",
                query,
            )
        )
    )


def recovery_budget(query: str) -> RecoveryBudget:
    if len(model_targets(query)) > 1 or re.search(
        r"比较|对比|区别|优缺点|多来源|综合|调查|compare|versus|\bvs\b",
        query,
        re.IGNORECASE,
    ):
        return STANDARD_BUDGET
    return LOOKUP_BUDGET


def _target_pattern(target: tuple[str, str]) -> re.Pattern[str]:
    name, version = target
    digits = r"[\s._-]*".join(re.escape(v) for v in version.split("."))
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(name.rstrip('_-'))}[\s._-]*{digits}(?![\d.])",
        re.IGNORECASE,
    )


def _rewrite(query: str) -> tuple[str, tuple[str, ...]]:
    spaced = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", query)
    if re.search(r"opus|claude|sonnet|haiku", spaced, re.IGNORECASE):
        if "claude" not in spaced.casefold():
            spaced = f"Claude {spaced}"
        return spaced, ("anthropic.com", "platform.claude.com")
    return spaced, ()


def recover_public_research(
    gateway: Any,
    query: str,
    *,
    should_cancel: Callable[[], bool] = lambda: False,
    budget: RecoveryBudget | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> list[dict[str, Any]]:
    budget = budget or recovery_budget(query)
    started = monotonic()
    deadline = started + budget.hard_seconds - budget.finalization_reserve
    calls: list[dict[str, Any]] = []
    scheduler = CandidateScheduler()
    body_digests: set[str] = set()
    covered: set[int] = set()
    searches = reads = used_chars = recovery_reads = authority_queries = rewrites = 0
    provider_failures = 0
    rewritten, domains = _rewrite(query)
    markers = [_target_pattern(target) for target in model_targets(rewritten)]
    authority = " OR ".join(f"site:{domain}" for domain in domains)
    authority_query = (
        f"({authority}) {rewritten}"
        if domains
        else f"{rewritten} official documentation"
    )
    # Initial/alternate reads cannot consume the final authority recovery slots.
    phases = (
        [
            ("initial", query, 2),
            (
                "authoritative_domain",
                f"{authority_query} release models documentation",
                1,
            ),
        ]
        if budget.mode == "lookup"
        else [
            ("initial", query, 2),
            ("query_rewrite", f"{rewritten} official", 1),
            ("authoritative_domain", authority_query, 1),
            (
                "page_type_refinement",
                f"{authority_query} models release API documentation",
                1,
            ),
        ]
    )

    def active() -> None:
        if should_cancel():
            raise RecoveryCancelled("Research cancelled by user")
        if monotonic() >= deadline:
            raise RecoveryDeadline("finalization_reserve_preserved")

    def invoke(fn: Callable[[], Any]) -> Any:
        active()
        call_deadline = min(deadline, monotonic() + 8)
        # Only the caller owns trace/persistence. A late network worker cannot
        # publish, and a new request never waits behind an old blocked worker.
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="research-recovery")
        future = pool.submit(fn)
        try:
            while True:
                active()
                remaining = call_deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("provider_call_timeout")
                try:
                    return future.result(timeout=min(0.1, remaining))
                except FutureTimeout:
                    if future.done():
                        raise
        finally:
            future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)

    def checkpoint(state: str, reason: str) -> None:
        calls.append(
            {
                "name": "research_recovery",
                "arguments": {"query": query},
                "result": {
                    "status": state,
                    "reason": reason,
                    "mode": budget.mode,
                    "searches": searches,
                    "reads": reads,
                    "used_chars": used_chars,
                    "recovery_reads": recovery_reads,
                    "query_rewrites": rewrites,
                    "authority_queries": authority_queries,
                    "target_coverage": {
                        "covered": len(covered),
                        "required": len(markers),
                    },
                    "question_coverage": "not_semantically_evaluated",
                    "candidate_scheduler": scheduler.snapshot(),
                    "provider_failures": provider_failures,
                    "stop_reason": {
                        "evidence_saturation": "EVIDENCE_SATURATED",
                        "provider_exhausted": "PROVIDER_EXHAUSTED",
                        "deadline_exhausted": "DEADLINE_EXHAUSTED",
                        "candidate_exhausted": "CANDIDATE_EXHAUSTED",
                        "budget_exhausted": "BUDGET_EXHAUSTED",
                        "hard_tool_failure": "BLOCKED_EXTERNAL",
                        "cancelled": "CANCELLED",
                        "read_backed": "READ_BACKED_PROGRESS",
                    }.get(state, "NEEDS_MORE_RESEARCH"),
                    "limits": {
                        "reads": budget.max_reads,
                        "queries": budget.max_queries,
                        "chars": budget.max_total_chars,
                        "source_chars": budget.max_source_chars,
                        "hard_seconds": budget.hard_seconds,
                        "finalization_reserve": budget.finalization_reserve,
                    },
                    "elapsed_seconds": round(monotonic() - started, 3),
                },
            }
        )

    def reject(url: str, reason: str) -> None:
        calls.append(
            {
                "name": "research_candidate",
                "arguments": {"url": url},
                "result": {"status": "rejected", "reason": reason},
            }
        )

    last_novel = 0
    last_search_ok = False
    try:
        for phase, search_query, phase_cap in phases[: budget.max_queries]:
            active()
            if reads >= budget.max_reads or budget.max_total_chars - used_chars < 500:
                checkpoint("budget_exhausted", "read_or_text_limit")
                return calls
            checkpoint("needs_more_research", phase)
            searches += 1
            if phase in {"authoritative_domain", "page_type_refinement"}:
                authority_queries += 1
            if phase in {"query_rewrite", "page_type_refinement"}:
                rewrites += 1
            try:
                result = invoke(
                    lambda: gateway.search_exact(search_query, max_results=5)
                )
                if not isinstance(result, dict):
                    raise ValueError("invalid_search_result")
            except (RecoveryCancelled, RecoveryDeadline):
                raise
            except Exception as exc:
                result = {
                    "status": "unavailable",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "results": [],
                }
            calls.append(
                {
                    "name": "web_search",
                    "arguments": {
                        "query": search_query,
                        "max_results": 5,
                        "recovery_stage": phase,
                    },
                    "result": result,
                }
            )
            last_search_ok = result.get("status") in {"ok", "empty"}
            if not last_search_ok:
                provider_failures += 1
            if result.get("reason") == "no_search_provider_enabled":
                checkpoint("hard_tool_failure", "no_search_provider_enabled")
                return calls
            if not callable(getattr(gateway, "read", None)):
                checkpoint("hard_tool_failure", "reader_unavailable")
                return calls
            items = result.get("results")
            candidates = (
                [v for v in items if isinstance(v, dict)]
                if isinstance(items, list)
                else []
            )
            selected, rejected = assess_sources(candidates, canonical_query=rewritten)
            for candidate in rejected:
                reject(
                    str(candidate["assessment"].get("url", "")),
                    candidate["assessment"]["rejection_reason"],
                )
            selected = scheduler.order(selected, domains)
            phase_reads = last_novel = 0
            for candidate in selected:
                active()
                assessment = candidate["assessment"]
                url = _public_url(assessment.get("url"))
                if not url or not assessment.get("worth_reading"):
                    reject(url, "unrelated_or_invalid_candidate")
                    continue
                if markers and urlparse(url).path.rstrip("/") in {"", "/en", "/zh-CN"}:
                    reject(url, "generic_homepage_for_version_question")
                    continue
                if rejection := scheduler.rejection(url):
                    reject(url, rejection)
                    continue
                if phase_reads >= phase_cap or reads >= budget.max_reads:
                    break
                limit = min(
                    budget.max_source_chars, budget.max_total_chars - used_chars
                )
                if limit < 500:
                    checkpoint("budget_exhausted", "text_limit")
                    return calls
                if reads >= budget.base_reads:
                    recovery_reads += 1
                scheduler.begin(url)
                reads += 1
                phase_reads += 1
                last_novel += 1
                read_started_at = datetime.now(timezone.utc).isoformat()
                try:
                    body = invoke(
                        lambda: gateway.read(
                            url,
                            max_chars=limit,
                            timeout=min(8, max(0.1, deadline - monotonic())),
                        )
                    )
                    if not isinstance(body, dict):
                        raise ValueError("invalid_read_result")
                except (RecoveryCancelled, RecoveryDeadline):
                    raise
                except Exception as exc:
                    body = {
                        "ok": False,
                        "url": url,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                if scheduler.finish(url, body):
                    provider_failures += 1
                content = body.get("content") or body.get("readme") or ""
                content = content if isinstance(content, str) else ""
                field = "content" if body.get("content") else "readme"
                body = {**body, field: content[:limit]}
                if len(content) > limit:
                    body["truncated"] = True
                content = content[:limit]
                used_chars += len(content)
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                body.update(
                    content_sha256=digest,
                    read_started_at=read_started_at,
                    read_completed_at=datetime.now(timezone.utc).isoformat(),
                )
                matches = {
                    i for i, marker in enumerate(markers) if marker.search(content)
                }
                if markers and not matches:
                    body.update(
                        answer_eligible=False,
                        adequacy_reason="requested_model_version_absent",
                    )
                elif content and digest in body_digests:
                    body.update(answer_eligible=False, adequacy_reason="duplicate_body")
                    last_novel -= 1
                elif not markers:
                    assessed, _ = assess_sources(
                        [{"title": content, "url": url}], canonical_query=query
                    )
                    if not assessed or not assessed[0]["assessment"]["worth_reading"]:
                        body.update(
                            answer_eligible=False, adequacy_reason="unrelated_body"
                        )
                body_digests.add(digest)
                calls.append(
                    {
                        "name": "web_read",
                        "arguments": {"url": url, "max_chars": limit},
                        "result": body,
                    }
                )
                evidence = evidence_tool_calls(calls)
                if evidence and evidence[-1].get("arguments", {}).get("url") == url:
                    covered.update(matches)
                enough_targets = not markers or len(covered) == len(markers)
                # Related reads are progress only, not semantic question coverage.
                if (
                    evidence
                    and enough_targets
                    and (budget.mode == "lookup" or len(evidence) >= 2)
                ):
                    checkpoint("read_backed", "related_discovery_linked_bodies")
                    return calls
    except RecoveryDeadline:
        checkpoint("deadline_exhausted", "finalization_reserve_preserved")
        return calls
    except RecoveryCancelled:
        checkpoint("cancelled", "user_cancelled")
        return calls
    evidence = evidence_tool_calls(calls)
    if not evidence and provider_failures:
        checkpoint("provider_exhausted", "external_paths_failed")
    elif not last_novel and last_search_ok and authority_queries:
        checkpoint(
            "evidence_saturation" if evidence else "candidate_exhausted",
            "bounded_evidence_repeated" if evidence else "no_novel_usable_candidates",
        )
    else:
        checkpoint("budget_exhausted", "query_or_read_limit")
    return calls
