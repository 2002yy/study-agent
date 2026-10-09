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
from src.web.search_query_quality import (
    build_authoritative_query,
    classify_candidate,
    optimize_search_query,
    order_candidates,
)
from src.web.tool_evidence import _public_url, evidence_tool_calls
from src.web.semantic_recovery import ResearchSemanticSession
from src.web.research.official_resolver import official_plan
from src.web.query_normalizer import normalize_web_query


class RecoveryCancelled(RuntimeError):
    pass


class RecoveryDeadline(TimeoutError):
    """The research window ended; provider timeouts are separately recoverable."""


def select_research_queries(
    proposals: list[dict[str, str]], slots: int, official_query: str,
    official_domains: list[str] | tuple[str, ...],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select advice by distinct RQ coverage; reserve the existing official slot.

    Advice is not evidence. Official priority uses known resolver domains,
    never a model's assertion of authority. Stable input order breaks ties.
    """
    def key(query: str) -> str:
        return " ".join(query.casefold().split())

    groups: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(proposals):
        identity = key(row["query"])
        group = groups.setdefault(identity, {
            "query": row["query"], "rq_ids": [], "index": index,
        })
        if row["rq_id"] not in group["rq_ids"]:
            group["rq_ids"].append(row["rq_id"])
    official_key = key(official_query)
    official = groups.pop(official_key, {"rq_ids": []})
    selected = [{"query": official_query, "rq_ids": official["rq_ids"],
                 "phase": "authoritative_domain", "reason": "reserved_official_recovery"}]
    covered = set(official["rq_ids"])

    def priority(group: dict[str, Any]) -> tuple[int, bool, int, int]:
        hosts = re.findall(r"site:([^\s)]+)", group["query"], re.I)
        known_official = any(host.casefold() in official_domains for host in hosts)
        # Deterministic specificity so equal single-RQ coverage does not collapse
        # to input order: prefer queries carrying versions/dates and more tokens.
        compact = optimize_search_query(group["query"])[0]
        tokens = compact.split()
        specificity = 2 * sum(1 for t in tokens if any(c.isdigit() for c in t)) + len(tokens)
        return (len(set(group["rq_ids"]) - covered), known_official, specificity, -group["index"])

    for _ in range(max(0, slots)):
        if not groups:
            break
        identity, group = max(groups.items(), key=lambda item: priority(item[1]))
        groups.pop(identity)
        selected.append({"query": group["query"], "rq_ids": group["rq_ids"],
                         "phase": "semantic_query", "reason": "rq_coverage_then_official_priority"})
        covered.update(group["rq_ids"])
    selected_keys = {key(row["query"]) for row in selected}
    seen: set[str] = set()
    deferred = []
    for row in proposals:
        identity = key(row["query"])
        reason = "duplicate_query" if identity in seen else "execution_slot_limit"
        if identity in seen or identity not in selected_keys:
            deferred.append({**row, "reason": reason})
        seen.add(identity)
    return selected[1:], {"selected": selected, "deferred": deferred,
                         "covered_rq_ids": sorted(covered), "semantic_slots": max(0, slots)}


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
    budget = budget or recovery_budget(query)
    started = monotonic() if started_at is None else started_at
    deadline = min(started + budget.hard_seconds, answer_deadline or float("inf")) - budget.finalization_reserve
    if semantic_session is not None:
        deadline -= 5  # body-batch time is part of research, never writer reserve
    calls: list[dict[str, Any]] = []
    dispositions: dict[str, dict[str, str]] = {}
    quality_records: list[dict[str, Any]] = []

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
    markers = [target_identity_pattern(target) for target in model_targets(rewritten)]
    # A bare short Chinese topic must appear whole in the body. Matching only
    # one character (e.g. a surname dictionary entry) is not topic evidence.
    literal_topic = search_topic.strip() if re.fullmatch(r"[\u3400-\u9fff]{2,4}", search_topic.strip()) else ""
    authority = " OR ".join(f"site:{domain}" for domain in domains)
    compact_topic = optimize_search_query(rewritten)[0]
    authority_query = (
        f"({authority}) {compact_topic}"
        if domains
        else build_authoritative_query(rewritten, ())
    )
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
    query_selection: dict[str, Any] | None = None
    query_rewrite_map: list[dict[str, str]] = []
    if query_plan:
        # Apply the existing entity spelling normalizer to *search advice*, not
        # the immutable original question. Official recovery runs before the
        # comparison tail can consume all remaining reads.
        optimized_plan = []
        for plan_row in query_plan:
            base = _rewrite(normalize_web_query(plan_row["query"]).canonical_query)[0]
            optimized, reason = optimize_search_query(base)
            optimized_plan.append({**plan_row, "query": optimized})
            query_rewrite_map.append(
                {"rq_id": str(plan_row.get("rq_id", "")), "original": plan_row["query"],
                 "optimized": optimized, "reason": reason}
            )
        query_plan = optimized_plan
        official_query = next(
            (row["query"] for row in query_plan if re.match(r"^site:[A-Za-z0-9.-]+\s", row["query"])),
            None,
        )
        if official_query is None:
            # Never paste the whole user question: reuse the model's entity-led
            # proposal (or a compacted entity query) with a known official domain.
            if domains:
                official_query = f"site:{domains[0]} {compact_topic}"
            elif query_plan:
                official_query = f"{query_plan[0]['query']} official documentation"
            else:
                official_query = authority_query
        # The live RSS fallback returned generic homepages when release/date/
        # schedule padding was appended, but found the exact official release
        # for the scoped entity/version. This is a discovery query only: the
        # immutable original question and its requested facets stay intact.
        scope = re.match(r"^(site:[A-Za-z0-9.-]+)\s", official_query)
        if scope and model_targets(query):
            entities = " ".join(f"{name} {version}" for name, version in model_targets(query))
            official_query = _rewrite(f"{scope.group(1)} {entities}")[0]
        planned, query_selection = select_research_queries(
            query_plan, min(3, max(0, budget.max_queries - 1)), official_query, domains,
        )
        phases = ([("semantic_query", planned[0]["query"], 2)] if planned else [])
        phases += [("authoritative_domain", official_query, 1)]
        phases += [("semantic_query", row["query"], 1) for row in planned[1:]]

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
                    "query_selection": query_selection,
                    "query_rewrite_map": query_rewrite_map,
                    "candidate_classification": quality_records,
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
            relevance_map: dict[str, list[str]] = {}
            judged_urls: set[str] = set()
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
                    url = str(row["assessment"].get("url", ""))
                    judged_urls.add(url)
                    related = list(relevance.get(f"candidate-{i}") or [])
                    relevance_map[url] = related
                    if not related:
                        semantic_rejected_urls.add(url)
                        reject(url, "semantic_unrelated_or_unavailable_candidate")
                selected = [row for i, row in enumerate(window) if relevance.get(f"candidate-{i}")]
                for row in selected:
                    row["assessment"]["worth_reading"] = True
            # Composite ordering (relevance strength -> entity/version match ->
            # expected coverage -> original rank); UNKNOWN candidates stay in the
            # pool at lower priority, only explicit off_target was dropped above.
            selected = order_candidates(selected, relevance_by_url=relevance_map, markers=markers)
            for candidate_row in selected:
                candidate_url = str(candidate_row["assessment"].get("url", ""))
                quality_records.append({
                    "candidate_id": candidate_url,
                    "relevance": classify_candidate(
                        related_ids=relevance_map.get(candidate_url, []),
                        judged=candidate_url in judged_urls,
                    ),
                    "matched_rq_ids": relevance_map.get(candidate_url, []),
                    "read_attempted": False,
                    "disposition": "eligible",
                })
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
                for quality_row in quality_records:
                    if quality_row["candidate_id"] == url:
                        quality_row["read_attempted"] = True
                        quality_row["disposition"] = "dispatched"
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
