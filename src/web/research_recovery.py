"""Bounded search/read recovery. Relevance is not semantic support or truth."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
import re
import time
from typing import Any, Callable
from urllib.parse import urlparse

from src.web.source_assessment import assess_sources
from src.web.recovery_candidates import CandidateScheduler
from src.web.tool_evidence import _public_url, evidence_tool_calls
from src.web.semantic_recovery import ResearchSemanticSession
from src.web.research.official_resolver import official_plan
from src.web.query_normalizer import normalize_web_query


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


def recovery_budget(
    query: str, query_plan: list[dict[str, str]] | None = None
) -> RecoveryBudget:
    if len(model_targets(query)) > 1 or re.search(
        r"比较|对比|区别|优缺点|多来源|综合|调查|compare|versus|\bvs\b",
        query,
        re.IGNORECASE,
    ):
        return STANDARD_BUDGET
    # A question can be multi-facet without naming two versions or saying
    # "compare" ("keep WAL or migrate, and tell me the triggers and steps").
    # The interpreter's own plan is the honest signal: two or more distinct
    # research questions need the standard window, otherwise the second facet
    # is never searched at all.
    if planned_questions(query_plan) >= 2:
        return STANDARD_BUDGET
    return LOOKUP_BUDGET


def _provider_call_seconds(gateway: Any) -> float:
    """Per-call ceiling for one provider invocation.

    The site pool visits several sites inside one call, so the 8s single-provider
    ceiling aborted every pool search with ``provider_call_timeout`` and the turn
    fell back to "no evidence". The ceiling must cover what the pool is allowed to
    spend (its budget plus the fallback reserve), otherwise the outer timer cuts a
    legal search short. Every other strategy keeps 8s.
    """

    seconds = 8.0
    if getattr(gateway, "search_strategy", "") != "browse_sites":
        return seconds
    try:
        pool = float(os.getenv("WEB_SITE_POOL_TOTAL_SECONDS", "20"))
        reserve = float(os.getenv("WEB_SEARCH_FALLBACK_RESERVE_SECONDS", "4"))
    except ValueError:
        pool, reserve = 20.0, 4.0
    return max(seconds, min(30.0, pool + reserve + 1.0))


def planned_questions(query_plan: list[dict[str, str]] | None) -> int:
    """How many distinct research questions a plan actually asks for."""

    if not query_plan:
        return 0
    rows = [row for row in query_plan if isinstance(row, dict)]
    ids = {str(row.get("rq_id") or "").strip() for row in rows}
    ids.discard("")
    if ids:
        return len(ids)
    queries = {str(row.get("query") or "").strip() for row in rows}
    queries.discard("")
    return len(queries)


def target_identity_pattern(target: tuple[str, str]) -> re.Pattern[str]:
    """Match one named version, allowing only a canonical zero-patch alias.

    A two-component target such as Python 3.14 may appear in release material
    as Python 3.14.0. Non-zero patches and adjacent minor versions remain
    distinct identities.
    """
    name, version = target
    parts = version.split(".")
    digits = r"[\s._-]*".join(re.escape(part) for part in parts)
    if len(parts) == 2:
        digits += r"(?:[\s._-]+0)?"
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(name.rstrip('_-'))}[\s._-]*{digits}(?![\d.])",
        re.IGNORECASE,
    )


#: Official documentation homes for technologies a research question names.
#: This is a discovery hint (one scoped query), not an answer: a page still has
#: to be read and judged before it can support anything.
_DOC_DOMAINS: dict[str, str] = {
    "sqlite": "sqlite.org",
    "postgresql": "postgresql.org",
    "postgres": "postgresql.org",
    "fastapi": "fastapi.tiangolo.com",
    "python": "docs.python.org",
    "docker": "docs.docker.com",
    "redis": "redis.io",
    "nginx": "nginx.org",
    "kubernetes": "kubernetes.io",
}

_STOPWORDS = {
    "the", "and", "or", "for", "with", "from", "this", "that", "should", "what",
    "how", "why", "when", "which", "are", "is", "to", "of", "in", "on", "vs",
    "a", "an", "do", "does", "can", "my", "we", "i",
}


def documentation_domains(query: str, rewritten: str = "") -> tuple[str, ...]:
    """Domains worth one scoped query for the technologies this question names."""

    text = f"{query} {rewritten}".casefold()
    found: list[str] = []
    for name, domain in _DOC_DOMAINS.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", text):
            if domain not in found:
                found.append(domain)
    return tuple(found[:2])


def ascii_topics(query: str, limit: int = 6) -> str:
    """English/ASCII tokens of a mixed-language question, for a scoped query.

    A Chinese question sent to ``site:sqlite.org`` finds dictionary pages; the
    product names (SQLite, WAL, FastAPI) are what the engine can match.
    """

    tokens: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9.+#-]{1,}", str(query or "")):
        if token.casefold() in _STOPWORDS or token in tokens:
            continue
        tokens.append(token)
        if len(tokens) >= limit:
            break
    return " ".join(tokens)


#: Names that identify a product rather than the topic being asked about.
_TECH_NAMES = {name.casefold() for name in _DOC_DOMAINS} | {"postgres"}
_GENERIC_TOPICS = {
    "worker", "workers", "app", "application", "database", "index",
    "indexing", "service", "server", "backend",
}


def documentation_query(domain: str, query: str) -> str:
    """A focused ``site:`` query: the product name plus the question's topic.

    ``site:sqlite.org FastAPI SQLite worker WAL PostgreSQL`` returns nothing;
    ``site:sqlite.org SQLite WAL`` returns the WAL page. Everything that names
    *other* products or the deployment shape is noise for a scoped query.
    """

    label = next(
        (name for name, mapped in _DOC_DOMAINS.items() if mapped == domain), ""
    )
    topics = [
        token for token in ascii_topics(query, limit=12).split()
        if token.casefold() not in _TECH_NAMES
        and token.casefold() not in _GENERIC_TOPICS
    ]
    parts = [label.capitalize() if label else "", *topics[:2]]
    return f"site:{domain} {' '.join(part for part in parts if part)}".strip()


def _rewrite(query: str) -> tuple[str, tuple[str, ...]]:
    spaced = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", query)
    if model_targets(spaced):
        # Keep named models/comparison subjects while removing standalone
        # question clauses that swamp a search engine's entity lookup. The
        # full original question remains the answer target and durable query.
        spaced = re.sub(
            r"(?:是什么|性能如何|表现如何|性能怎么样|对比(?:如何)?)"
            r"(?=[？?，,；;。]|$)",
            " ",
            spaced,
        )
        spaced = " ".join(re.sub(r"[？?，,；;。]+", " ", spaced).split())
    if re.search(r"opus|claude|sonnet|haiku", spaced, re.IGNORECASE):
        if "claude" not in spaced.casefold():
            if spaced.startswith("site:") and " " in spaced:
                scope, topic = spaced.split(" ", 1)
                spaced = f"{scope} Claude {topic}"
            else:
                spaced = f"Claude {spaced}"
        return spaced, ("anthropic.com", "platform.claude.com")
    return spaced, ()


def recover_public_research(
    gateway: Any, query: str, *,
    should_cancel: Callable[[], bool] = lambda: False,
    budget: RecoveryBudget | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    started_at: float | None = None, answer_deadline: float | None = None,
    semantic_session: ResearchSemanticSession | None = None,
    query_plan: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    calls = _recover_public_research(
        gateway, query, should_cancel=should_cancel, budget=budget, monotonic=monotonic,
        started_at=started_at, answer_deadline=answer_deadline,
        semantic_session=semantic_session, query_plan=query_plan,
    )
    if semantic_session is None:
        return calls
    if any(call.get("result", {}).get("method") == "official_metadata_http_v2"
           for call in evidence_tool_calls(calls)):
        return calls  # parsed fields bypass relevance advice, never the publication gate
    reads = [call for call in calls if call.get("name") == "web_read"
             and call.get("result", {}).get("ok") is True
             and call["result"].get("answer_eligible") is not False]
    # All provisional bodies stay outside persisted/writer evidence until this
    # one batched read-after-fetch check completes. No model can rescue a body
    # already rejected by deterministic provenance/version/dedup checks.
    for call in reads:
        call["result"]["answer_eligible"] = False
        call["result"]["adequacy_reason"] = "semantic_relevance_pending"
    if reads:
        try:
            decisions = semantic_session.relevance("research_body_relevance", [
                {"id": f"body-{i}", "url": str(call["arguments"]["url"]),
                 "text": str(call["result"].get("content") or call["result"].get("readme") or "")[:1800],
                 "truncated": "true" if len(str(call["result"].get("content") or call["result"].get("readme") or "")) > 1800 else "false"}
                for i, call in enumerate(reads)
            ])
            if should_cancel():
                raise RecoveryCancelled("cancelled")
            for i, call in enumerate(reads):
                rqs = decisions[f"body-{i}"]
                call["result"].update(answer_eligible=bool(rqs), related_rq_ids=rqs,
                                      adequacy_reason="related_to_rq_not_claim_support" if rqs else "semantic_unrelated_body")
                semantic_session.body_questions.update(rqs)
        except Exception:
            for call in reads:
                call["result"]["adequacy_reason"] = "semantic_relevance_unavailable"
    summary = recovery_summary(calls) or {}
    accepted = evidence_tool_calls(calls)
    if should_cancel():
        for call in reads:
            call["result"]["answer_eligible"] = False
        summary.update(status="cancelled", stop_reason="CANCELLED", reason="user_cancelled")
    elif accepted:
        required = {q["id"] for q in semantic_session.episode.questions} if semantic_session.episode else set()
        targets = summary.get("target_coverage", {})
        related_all = required <= semantic_session.body_questions and targets.get("covered", 0) >= targets.get("required", 0)
        summary.update(status="read_backed" if related_all else "partial",
                       stop_reason="READ_BACKED_PROGRESS", reason="rq_related_bodies_not_adequacy")
    elif summary.get("status") in {"read_backed", "evidence_saturation"}:
        summary.update(status="candidate_exhausted", stop_reason="CANDIDATE_EXHAUSTED", reason="no_related_body")
    summary["question_coverage"] = {"related": sorted(semantic_session.body_questions), "kind": "relevance_only"}
    summary["semantic_model_calls"] = len(semantic_session.events)
    calls.append({"name": "research_recovery", "arguments": {"query": query}, "result": summary})
    return calls


def _recover_public_research(
    gateway: Any,
    query: str,
    *,
    should_cancel: Callable[[], bool] = lambda: False,
    budget: RecoveryBudget | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    started_at: float | None = None,
    answer_deadline: float | None = None,
    semantic_session: ResearchSemanticSession | None = None,
    query_plan: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    budget = budget or recovery_budget(query, query_plan)
    started = monotonic() if started_at is None else started_at
    deadline = min(started + budget.hard_seconds, answer_deadline or float("inf")) - budget.finalization_reserve
    if semantic_session is not None:
        deadline -= 5  # body-batch time is part of research, never writer reserve
    calls: list[dict[str, Any]] = []
    dispositions: dict[str, dict[str, str]] = {}

    def disposition(url: str, state: str, reason: str = "") -> None:
        if url and dispositions.get(url, {}).get("state") != "dispatched":
            dispositions[url] = {"candidate_id": url, "state": state, "reason": reason}
    scheduler = CandidateScheduler()
    body_digests: set[str] = set()
    semantic_rejected_urls: set[str] = set()
    pending_candidates: list[dict[str, Any]] = []
    covered: set[int] = set()
    searches = reads = used_chars = recovery_reads = authority_queries = rewrites = 0
    provider_failures = 0
    search_topic = normalize_web_query(query).canonical_query
    rewritten, domains = _rewrite(search_topic)
    doc_domains = () if domains else documentation_domains(query, rewritten)
    markers = [target_identity_pattern(target) for target in model_targets(rewritten)]
    # A bare short Chinese topic must appear whole in the body. Matching only
    # one character (e.g. a surname dictionary entry) is not topic evidence.
    literal_topic = search_topic.strip() if re.fullmatch(r"[\u3400-\u9fff]{2,4}", search_topic.strip()) else ""
    if domains:
        # An official release plan already knows its exact homes; keep the
        # existing OR scope over them.
        authority_query = f"({' OR '.join(f'site:{d}' for d in domains)}) {rewritten}"
    elif doc_domains:
        # A documentation question needs the product name and one topic, not
        # the whole sentence (which may be Chinese).
        authority_query = documentation_query(doc_domains[0], query)
    else:
        authority_query = f"{rewritten} official documentation"
    # Initial/alternate reads cannot consume the final authority recovery slots.
    phases = (
        [
            ("initial", search_topic, 2),
            (
                "authoritative_domain",
                f"{authority_query} release models documentation",
                1,
            ),
        ]
        if budget.mode == "lookup"
        else [
            ("initial", search_topic, 2),
            ("query_rewrite", f"{rewritten} official", 1),
            ("authoritative_domain", authority_query, 1),
            (
                "page_type_refinement",
                f"{authority_query} models release API documentation",
                1,
            ),
        ]
    )
    if query_plan:
        # Apply the existing entity spelling normalizer to *search advice*, not
        # the immutable original question. Official recovery runs before the
        # comparison tail can consume all remaining reads.
        query_plan = [{**row, "query": _rewrite(normalize_web_query(row["query"]).canonical_query)[0]}
                      for row in query_plan]
        planned = query_plan[: min(3, budget.max_queries - 1)]
        official_query = next(
            (row["query"] for row in query_plan if re.match(r"^site:[A-Za-z0-9.-]+\s", row["query"])),
            f"site:{domains[0]} {rewritten}" if domains
            else documentation_query(doc_domains[0], query) if doc_domains
            else authority_query,
        )
        # The live RSS fallback returned generic homepages when release/date/
        # schedule padding was appended, but found the exact official release
        # for the scoped entity/version. This is a discovery query only: the
        # immutable original question and its requested facets stay intact.
        scope = re.match(r"^(site:[A-Za-z0-9.-]+)\s", official_query)
        if scope and model_targets(query):
            entities = " ".join(f"{name} {version}" for name, version in model_targets(query))
            official_query = _rewrite(f"{scope.group(1)} {entities}")[0]
        phases = [("semantic_query", planned[0]["query"], 2),
                  ("authoritative_domain", official_query, 1)] + [
                      ("semantic_query", row["query"], 1) for row in planned[1:]
                      if row["query"] != official_query]

    def active() -> None:
        if should_cancel():
            raise RecoveryCancelled("Research cancelled by user")
        if monotonic() >= deadline:
            raise RecoveryDeadline("finalization_reserve_preserved")

    def invoke(fn: Callable[[], Any]) -> Any:
        active()
        call_deadline = min(deadline, monotonic() + _provider_call_seconds(gateway))
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

    plan = official_plan(query)
    if plan and getattr(gateway, "supports_official_metadata", False) is True:
        phases.insert(0, ("official_resolver", query, 2))

    def checkpoint(state: str, reason: str) -> None:
        if state != "needs_more_research":
            for row in dispositions.values():
                if row["state"] in {"eligible", "discovered"}:
                    row.update(state="run_blocked", reason=reason)
        calls.append(
            {
                "name": "research_recovery",
                "arguments": {"query": query},
                "result": {
                    "query": query,
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
                    "candidate_dispositions": list(dispositions.values()),
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
        disposition(url, "filtered", reason)
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
        bounded_phases = phases[: budget.max_queries]
        for phase_index, (phase, search_query, phase_cap) in enumerate(bounded_phases):
            # Phase caps reserve future opportunities; at the final phase there
            # is no later phase to reserve for. Spend unused slots on novel
            # candidates rather than strand a discovered release behind a
            # regional docs redirect. The run's read/char/deadline caps remain.
            if phase_index == len(bounded_phases) - 1:
                phase_cap = budget.max_reads - reads
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
                if phase == "official_resolver" and plan:
                    result = {"status": "ok", "reason": "known_official_addresses_not_search_results",
                              "results": [{"url": url, "title": f"{plan.entity} {plan.version} official metadata", "snippet": ""}
                                          for url in plan.urls]}
                else:
                    result = invoke(lambda: gateway.search_exact(search_query, max_results=5))
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
                    "name": "official_resolve" if phase == "official_resolver" else "web_search",
                    "arguments": {
                        "query": search_query,
                        "max_results": 5,
                        "recovery_stage": phase,
                        "rq_ids": [row["rq_id"] for row in query_plan or [] if row["query"] == search_query],
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
            for item in candidates:
                disposition(str(item.get("url") or item.get("link") or ""), "discovered")
            selected, rejected = assess_sources(candidates, canonical_query=rewritten)
            for row in selected:
                disposition(str(row["assessment"].get("url") or ""), "eligible")
            for candidate in rejected:
                reject(
                    str(candidate["assessment"].get("url", "")),
                    candidate["assessment"]["rejection_reason"],
                )
            if semantic_session is not None:
                # Discovery survives a phase's read cap. A release page found
                # behind a blocked docs locale must not disappear when the next
                # query returns only homepages or duplicate language variants.
                combined = [*pending_candidates, *selected]
                unique = {str(row["assessment"].get("url", "")): row for row in combined}
                selected = list(unique.values())
            selected = scheduler.order(selected, domains)
            if markers:
                # Exact named versions outrank adjacent versions even when the
                # advisory relevance judge considers the whole family related.
                selected.sort(key=lambda row: not any(marker.search(
                    str(row["item"].get("title", "")) + " " + str(row["item"].get("snippet", ""))
                    + " " + str(row["assessment"].get("url", ""))) for marker in markers))
            if phase != "official_resolver" and semantic_session is not None and selected and "research_candidate_relevance" not in semantic_session.stages:
                window = selected[:5]
                try:
                    relevance = semantic_session.relevance("research_candidate_relevance", [
                        {"id": f"candidate-{i}", "url": str(row["assessment"].get("url", "")),
                         "text": str(row["item"].get("title", ""))[:300] + " " + str(row["item"].get("snippet", ""))[:500]}
                        for i, row in enumerate(window)
                    ])
                except Exception:
                    relevance = {}
                for i, row in enumerate(window):
                    if not relevance.get(f"candidate-{i}"):
                        semantic_rejected_urls.add(str(row["assessment"].get("url", "")))
                        reject(str(row["assessment"].get("url", "")), "semantic_unrelated_or_unavailable_candidate")
                selected = [row for i, row in enumerate(window) if relevance.get(f"candidate-{i}")]
                for row in selected:
                    row["assessment"]["worth_reading"] = True
            if semantic_session is not None:
                pending_candidates = selected[:20]
            phase_reads = last_novel = 0
            for candidate_index, candidate in enumerate(selected):
                active()
                assessment = candidate["assessment"]
                url = _public_url(assessment.get("url"))
                # Registry seeds use exact project/paper identity, not lexical
                # overlap between a human paper title and its numeric arXiv URL.
                if phase == "official_resolver" and plan and url in plan.urls:
                    assessment["worth_reading"] = True
                if url in semantic_rejected_urls:
                    reject(url, "semantic_candidate_already_rejected")
                    continue
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
                    for pending in selected[candidate_index:]:
                        disposition(str(pending["assessment"].get("url") or ""), "run_blocked", "read_cap")
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
                disposition(url, "dispatched")
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
                    calls.append({"name": "web_read", "arguments": {"url": url, "max_chars": limit},
                                  "result": {"ok": False, "url": url, "error_code": "read_interrupted",
                                             "read_started_at": read_started_at,
                                             "read_completed_at": datetime.now(timezone.utc).isoformat()}})
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
                # Preserve reader-owned integrity proof. Rehashing an official
                # result here would erase an invalid/truncated source digest.
                if body.get("method") != "official_metadata_http_v2":
                    body["content_sha256"] = digest
                body.update(
                    read_started_at=read_started_at,
                    read_completed_at=datetime.now(timezone.utc).isoformat(),
                )
                matches = {
                    i for i, marker in enumerate(markers) if marker.search(content)
                }
                from src.web.research.official_resolver import verified_opus_identity, verified_python_identity, verified_release_identity

                verified_python = bool(phase == "official_resolver" and plan
                                       and verified_python_identity(plan, url, body))
                verified_opus = bool(phase == "official_resolver" and plan
                                     and verified_opus_identity(plan, url, body))
                verified_release = bool(phase == "official_resolver" and plan
                                        and verified_release_identity(plan, url, body))
                verified_official = verified_python or verified_opus or verified_release
                if verified_official:
                    matches.update(range(len(markers)))
                if plan and body.get("method") == "official_metadata_http_v2" and plan.version and body.get("source_version") != plan.version and not verified_official:
                    body.update(answer_eligible=False, adequacy_reason="requested_official_version_mismatch")
                elif markers and not matches and not verified_official:
                    body.update(
                        answer_eligible=False,
                        adequacy_reason="requested_model_version_absent",
                    )
                elif literal_topic and literal_topic not in content:
                    body.update(
                        answer_eligible=False, adequacy_reason="literal_topic_absent"
                    )
                elif content and digest in body_digests:
                    body.update(answer_eligible=False, adequacy_reason="duplicate_body")
                    last_novel -= 1
                elif phase != "official_resolver" and not markers and semantic_session is None:
                    assessed, _ = assess_sources(
                        [{"title": content, "url": url}], canonical_query=query
                    )
                    if not assessed or assessed[0]["assessment"]["directness"] not in {
                        "direct_title", "direct_snippet", "contextual"
                    }:
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
                if phase == "official_resolver" and body.get("method") == "official_metadata_http_v2" and evidence:
                    checkpoint("read_backed", "official_fields_read_not_answer_authority")
                    return calls
                enough_targets = not markers or len(covered) == len(markers)
                # Related reads are progress only, not semantic question coverage.
                if (
                    semantic_session is None
                    and
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
