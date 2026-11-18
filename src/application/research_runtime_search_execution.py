"""One admitted search call with its provider audit and diagnostic timing.

The active executor still owns external-attempt markers, budgets, candidate
merging, results and checkpoints. This short-lived context binds the exact
wave/query snapshot *after* its attempt-start checkpoint and performs no
durable writes itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.web.research.active_adapter import ActiveResearchGateway
from src.web.research.discovery_observability import record_search_call
from src.web.research.page_intent import PageIntent
from src.web.research.runtime import ResearchRuntimeCursor
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY, RuntimePhaseTiming


def _deeper_targeting_inputs(
    context: dict[str, Any],
) -> tuple[PageIntent | None, tuple[str, ...]]:
    """Latest §36A/§36B discovery hints, for §37A observability only.

    The linkage from one issued query back to a specific follow-up is
    approximate on purpose: durable cursor records keep their frozen shape,
    so observation reads the latest diagnostics entry instead of adding a
    query-to-follow-up key. ``hint_terms`` at the search call site stay exact.
    """

    metrics = context.get(ACTIVE_RESEARCH_METRICS_KEY)
    if not isinstance(metrics, Mapping):
        return None, ()
    state = metrics.get("deeper_targeting")
    if not isinstance(state, Mapping):
        return None, ()
    recent = state.get("recent")
    if not isinstance(recent, list) or not recent:
        return None, ()
    latest = recent[-1]
    if not isinstance(latest, Mapping):
        return None, ()
    raw_intent = latest.get("page_intent")
    intent: PageIntent | None = None
    if isinstance(raw_intent, Mapping) and raw_intent.get("kind"):
        path_terms = raw_intent.get("path_terms")
        intent = PageIntent(
            kind=str(raw_intent.get("kind") or ""),
            path_terms=tuple(str(item) for item in (path_terms or []) if str(item)),
            matched_terms=tuple(
                str(item) for item in (raw_intent.get("matched_terms") or []) if str(item)
            ),
        )
    raw_variants = latest.get("query_variants")
    variants = (
        tuple(str(item) for item in raw_variants if str(item))
        if isinstance(raw_variants, list)
        else ()
    )
    return intent, variants


def _search_discovery_slot(context: dict[str, Any]) -> int:
    """Execution-order index of the next issued query (deterministic)."""

    metrics = context.get(ACTIVE_RESEARCH_METRICS_KEY)
    if not isinstance(metrics, Mapping):
        return 1
    state = metrics.get("search_discovery")
    if not isinstance(state, Mapping):
        return 1
    queries = state.get("queries")
    return len(queries) + 1 if isinstance(queries, list) else 1


def _lead_hints_for_claim(
    cursor: ResearchRuntimeCursor, claim_id: str
) -> tuple[str, tuple[str, ...]]:
    """Return ``(trusted_domain, hints)`` for one claim.

    ``trusted_domain`` may become a ``site:`` constraint, and only two sources
    are trusted: a domain explicitly *discovered* by a lead read, or a page
    whose server-owned source role is ``primary`` (recorded as
    ``trusted_primary_domain``). A mere source domain - the page we happened to
    read - is never returned as trusted, because locking a follow-up search into
    a mirror/aggregator domain makes primary evidence unreachable.
    """

    claim_query_ids = {
        item.id for item in cursor.planned_queries if item.claim_id == claim_id
    }
    if not claim_query_ids:
        return "", ()
    candidates_by_id = {item.id: item for item in cursor.candidates}
    trusted = ""
    hints: list[str] = []
    for payload in cursor.lead_discoveries:
        parent_id = str(payload.get("source_candidate_id") or "")
        parent = candidates_by_id.get(parent_id)
        if parent is None or not claim_query_ids.intersection(parent.query_ids):
            continue
        if not trusted:
            domains = payload.get("domains")
            if isinstance(domains, list):
                trusted = next(
                    (str(domain).strip() for domain in domains if str(domain).strip()),
                    "",
                )
        for key in ("organizations", "primary_source_hints"):
            values = payload.get(key)
            if isinstance(values, list):
                hints.extend(str(value) for value in values)
    # Evidence-stage lead follow-ups contribute bounded terms; their domain is
    # trusted only when the read page's own role was primary.
    for followup in cursor.evidence_lead_followups:
        parent_id = str(followup.get("source_candidate_id") or "")
        parent = candidates_by_id.get(parent_id)
        if parent is None or not claim_query_ids.intersection(parent.query_ids):
            continue
        if not trusted:
            trusted = str(followup.get("trusted_primary_domain") or "")
        terms = followup.get("hint_terms")
        if isinstance(terms, list):
            hints.extend(str(term) for term in terms[:2])
    return trusted, tuple(dict.fromkeys(hint for hint in hints if hint))


@dataclass(slots=True)
class ActiveSearchQueryExecution:
    """Only search transport and observation, never attempt accounting.

    ``context`` and ``cursor`` are taken at the current attempt boundary;
    the executor may later replace its runtime context at a checkpoint.
    """

    gateway: ActiveResearchGateway
    monotonic: Callable[[], float]
    hard_seconds_left: Callable[[], float]
    reserve_seconds: float
    phase_timing: RuntimePhaseTiming
    context: dict[str, Any]
    claim_id: str
    cursor: ResearchRuntimeCursor
    audit: dict[str, Any] | None = field(default=None, init=False)

    def search_exact(self, query: str, *, max_results: int = 5) -> Mapping[str, Any]:
        remaining = self.hard_seconds_left()
        search_deadline = self.monotonic() + max(0.0, remaining - self.reserve_seconds)
        try:
            self.phase_timing.begin("search")
            payload = self.gateway.search_detailed(
                query,
                max_items=max_results,
                deadline=search_deadline,
            )
            self.audit = self.gateway.last_search_audit()
            search_intent, search_variants = _deeper_targeting_inputs(self.context)
            record_search_call(
                self.context,
                metrics_key=ACTIVE_RESEARCH_METRICS_KEY,
                slot_index=_search_discovery_slot(self.context),
                query=query,
                claim_id=str(self.claim_id or ""),
                intent=search_intent,
                variants=search_variants,
                hint_terms=_lead_hints_for_claim(self.cursor, str(self.claim_id or ""))[1],
                results=(payload.get("results") if isinstance(payload, Mapping) else ()),
            )
            return payload
        finally:
            self.phase_timing.end("search", context=self.context)
