"""Bounded search-discovery observability (PROJECT_STATUS §37A).

Pure diagnostic sidecar: it answers "what did the provider return, what did we
select, and what did we actually read" without touching search behaviour,
ordering, budgets, eligibility or the frozen runtime contract.

Recorded per actually-issued query (bounded Top-K results):

* ``slot_index`` and the planning inputs (``hint_terms``) plus the generated
  ``query_variants`` - so an audit can prove whether Q2/Q3 ever reach the
  provider or only the first variant influences the issued query;
* ``result_rank / url / title / snippet`` with mechanical targeting signals
  (authority class, title/snippet/intent lexical hits, selection reason);
* nothing about page bodies, and no semantic verdict: the "is this the page that
  carries the fact" judgement stays a human audit field.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from src.web.research.deeper_targeting import authority_class
from src.web.research.page_intent import (
    PageIntent,
    lexical_targeting_score,
    selection_reason as _selection_reason,
    targeting_preference_key,
)

STATE_TRUE = "true"
STATE_FALSE = "false"
STATE_UNOBSERVED = "unobserved"

SCHEMA_VERSION = "rq1c-search-discovery-v1"
DEFAULT_MAX_QUERIES = 24
DEFAULT_TOP_K = 5
_MAX_QUERY_EXCERPT = 160
_MAX_TITLE = 200
_MAX_SNIPPET = 240
_MAX_TERMS = 6
_OUTCOME = "observability_only"


def canonical_for_audit(url: str) -> str:
    """Canonical key for audit dedup (production canonicalizer, audit only)."""

    try:
        from src.news.url_normalizer import canonicalize_url

        canonical = canonicalize_url(str(url or ""))
        if canonical:
            return str(canonical)
    except Exception:  # pragma: no cover - canonicalizer is optional here
        pass
    return str(url or "").strip()


def dedupe_candidates(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[int]]]:
    """Collapse query-result occurrences into unique candidates per case.

    Returns ``(unique_rows, occurrences)`` where ``occurrences`` maps the
    canonical URL to the 1-based occurrence indices that produced it. Human
    labelling happens on ``unique_rows`` and is projected back through this map,
    so a URL recalled by ten queries is not weighted ten times.
    """

    unique_rows: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    occurrences: dict[str, list[int]] = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            continue
        key = canonical_for_audit(str(row.get("url") or ""))
        if not key:
            continue
        occurrences.setdefault(key, []).append(index)
        if key in by_key:
            by_key[key]["occurrence_count"] = int(
                by_key[key].get("occurrence_count") or 1
            ) + 1
            continue
        entry = {
            "canonical_url": key,
            "url": str(row.get("url") or ""),
            "title": row.get("title"),
            "snippet": row.get("snippet"),
            "authority_class": row.get("authority_class"),
            "lexical_targeting_score": row.get("lexical_targeting_score"),
            "selection_reason": row.get("selection_reason"),
            "occurrence_count": 1,
            "first_result_rank": row.get("result_rank"),
            # Three-state accounting: no probe means unobserved, never false.
            "selected_for_harvest": STATE_UNOBSERVED,
            "selected_for_read": STATE_UNOBSERVED,
            "read_status": "",
            "final_relation": "",
            "final_caveat": "",
            # Human fields (candidate level):
            "human_candidate_classification": "",
            "human_target_fact_present_after_read": STATE_UNOBSERVED,
        }
        by_key[key] = entry
        unique_rows.append(entry)
    return unique_rows, occurrences


def saturation_metrics(
    queries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Mechanical result-set saturation: how little new the extra queries find."""

    per_query: list[set[str]] = []
    for item in queries:
        urls = {
            canonical_for_audit(str(row.get("url") or ""))
            for row in (item.get("results") or [])
            if isinstance(row, Mapping)
        }
        urls.discard("")
        per_query.append(urls)
    unique_urls = set().union(*per_query) if per_query else set()
    first = per_query[0] if per_query else set()
    added_after_first = unique_urls - first
    overlap: list[float] = []
    for index in range(1, len(per_query)):
        previous, current = per_query[index - 1], per_query[index]
        union = previous | current
        overlap.append(round(len(previous & current) / len(union), 4) if union else 0.0)
    return {
        "query_count": len(per_query),
        "unique_urls_per_case": len(unique_urls),
        "new_url_gain_after_q1": len(added_after_first),
        "pairwise_result_set_overlap": overlap,
    }

DEFAULT_MAX_QUERIES = 24
DEFAULT_TOP_K = 5
_MAX_QUERY_EXCERPT = 160
_MAX_TITLE = 200
_MAX_SNIPPET = 240
_MAX_TERMS = 6
_OUTCOME = "observability_only"


def _bounded(value: Any, limit: int) -> str:
    return str(value or "")[:limit]


def _sha256(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _terms(value: Any, limit: int = _MAX_TERMS) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    items: list[str] = []
    for item in value:
        clean = str(item).strip()
        if clean and clean not in items:
            items.append(clean)
        if len(items) >= limit:
            break
    return items


def variant_matches(query: str, variants: Sequence[str]) -> list[int]:
    """Indices of generated variants that share >=2 terms with the issued query.

    Mechanical only: it says whether a variant's terms could have influenced the
    issued query, not whether the query is "correct".
    """

    query_terms = {token for token in str(query or "").casefold().split() if token}
    matched: list[int] = []
    for index, variant in enumerate(variants):
        variant_terms = {token for token in str(variant or "").casefold().split() if token}
        if len(query_terms & variant_terms) >= 2:
            matched.append(index)
    return matched


def record_search_call(
    context: dict[str, Any],
    *,
    metrics_key: str,
    slot_index: int,
    query: str,
    claim_id: str,
    intent: PageIntent | None,
    variants: Sequence[str],
    hint_terms: Sequence[str],
    results: object,
    top_k: int = DEFAULT_TOP_K,
    max_queries: int = DEFAULT_MAX_QUERIES,
) -> None:
    """Append one bounded observability record (never raises on odd payloads)."""

    metrics = context.setdefault(metrics_key, {})
    state = metrics.get("search_discovery")
    if not isinstance(state, dict):
        state = {"schema_version": SCHEMA_VERSION, "outcome": _OUTCOME, "queries": []}
        metrics["search_discovery"] = state
    queries = state.get("queries")
    if not isinstance(queries, list):
        queries = []
        state["queries"] = queries

    bounded_variants = _terms(variants, limit=3)
    raw_results = (
        results
        if isinstance(results, Sequence) and not isinstance(results, (str, bytes))
        else ()
    )
    rows: list[dict[str, Any]] = []
    for rank, raw in enumerate(list(raw_results)[: max(1, int(top_k))], start=1):
        if not isinstance(raw, Mapping):
            continue
        url = _bounded(raw.get("url") or raw.get("link"), 300)
        if not url:
            continue
        title = _bounded(raw.get("title"), _MAX_TITLE)
        snippet = _bounded(raw.get("snippet") or raw.get("search_excerpt"), _MAX_SNIPPET)
        lexical = lexical_targeting_score(
            title=title,
            snippet=snippet,
            missing_fact_terms=hint_terms,
            intent=intent,
        )
        key = targeting_preference_key(
            authoritative=False,
            title_match=lexical["candidate_title_match"],
            intent_match=lexical["candidate_intent_match"],
            snippet_match=lexical["candidate_snippet_match"],
        )
        del key
        rows.append(
            {
                "result_rank": rank,
                "url": url,
                "title": title,
                "snippet": snippet,
                "provider": _bounded(raw.get("provider"), 60),
                "providers": _terms(raw.get("providers"), limit=3),
                "authority_class": authority_class(url),
                "lexical_targeting_score": lexical,
                "selection_reason": _selection_reason(
                    authoritative=False,
                    title_match=lexical["candidate_title_match"],
                    intent_match=lexical["candidate_intent_match"],
                ),
                # Filled by the human audit; the tool must not declare a verdict.
                "human_candidate_classification": "",
                "selected_for_harvest": False,
                "selected_for_read": False,
                "read_status": "",
                "final_relation": "",
                "final_caveat": "",
            }
        )

    queries.append(
        {
            "slot_index": int(slot_index),
            "query_sha256": _sha256(query),
            "query_chars": len(str(query or "")),
            "query_excerpt": _bounded(query, _MAX_QUERY_EXCERPT),
            "claim_id": _bounded(claim_id, 120),
            "page_intent": intent.to_dict() if intent is not None else {},
            "generated_query_variants": bounded_variants,
            "variant_matches": variant_matches(query, bounded_variants),
            "hint_terms": _terms(hint_terms),
            "result_count": len(rows),
            "results": rows,
        }
    )
    del queries[:-max(1, int(max_queries))]


def issued_variant_coverage(queries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """How many generated variants ever matched an actually-issued query."""

    generated_total = 0
    matched_total = 0
    per_query: list[dict[str, Any]] = []
    for item in queries:
        variants = item.get("generated_query_variants") or []
        matches = item.get("variant_matches") or []
        generated_total += len(variants)
        matched_total += len(matches)
        per_query.append(
            {
                "slot_index": item.get("slot_index"),
                "generated": len(variants),
                "matched": list(matches),
            }
        )
    return {
        "generated_total": generated_total,
        "matched_total": matched_total,
        "queries": per_query,
        "note": (
            "mechanical term overlap only; low coverage means non-first variants "
            "never influenced an issued query"
        ),
    }
