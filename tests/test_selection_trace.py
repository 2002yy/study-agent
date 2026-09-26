"""§37B-selection: provenance trace unit + integration contract tests."""

from __future__ import annotations

import json

from src.web.research.candidate_pool import (
    CandidatePoolItem,
    execute_candidate_pool_batch,
    merge_candidate_pool,
)
from src.web.research.gap_planner import GapQueryBatch, GapSearchIntent, PlannedGapQuery
from src.web.research.selection_trace import (
    TERMINAL_REASONS,
    SelectionTraceCollector,
)

CASES = "https://docs.docker.com/docker-hub/usage/pulls/"


def _planned(query_id: str = "q1", query: str = "docker pull rate limits") -> PlannedGapQuery:
    return PlannedGapQuery(
        id=query_id,
        gap_id="gap1",
        claim_id="claim1",
        intent=GapSearchIntent.PRIMARY,
        query=query,
    )


def _raw(url: str, title: str = "Title", snippet: str = "Snippet") -> dict:
    return {"url": url, "title": title, "snippet": snippet, "provider": "bing_rss"}


def _payload(urls: list[str]) -> dict:
    return {"results": [_raw(url) for url in urls], "providers_attempted": ["bing_rss"]}


def _batch(urls: list[str], query_id: str = "q1") -> GapQueryBatch:
    return GapQueryBatch(
        gap_id="gap1",
        claim_id="claim1",
        focused_surface="fact",
        queries=(_planned(query_id),),
    )


def _entry(payload: dict, url: str) -> dict:
    for item in payload["entries"]:
        if item["canonical_url"].rstrip("/") == url.rstrip("/"):
            return item
    raise AssertionError(f"missing trace entry for {url}")


# 1 + 2: provider -> normalized, still joinable by canonical URL.
def test_seen_and_normalized_are_recorded_and_joinable() -> None:
    trace = SelectionTraceCollector()
    payload = _payload([CASES])
    result = execute_candidate_pool_batch(
        _batch([CASES]),
        search_exact=lambda query, max_results: payload,
        trace=trace,
    )
    assert len(result.candidates) == 1

    entry = _entry(trace.to_payload(), CASES)
    assert entry["seen_in_provider"] is True
    assert entry["normalized"] is True
    assert entry["materialized"] is True
    assert entry["deduped_survivor"] is True
    assert entry["terminal_reason"] == "unobserved"


# 3: a repeated occurrence merges into its own survivor (merge, not drop).
def test_duplicate_merge_is_not_a_drop() -> None:
    trace = SelectionTraceCollector()
    pool = merge_candidate_pool(
        [
            (_planned("q1"), (_raw(CASES),), ("bing_rss",)),
            (_planned("q2"), (_raw(CASES + "?utm_source=x"),), ("bing_rss",)),
        ],
        max_candidates=10,
        trace=trace,
    )
    assert [item.canonical_url.rstrip("/") for item in pool] == [CASES.rstrip("/")]
    entry = _entry(trace.to_payload(), CASES)
    assert entry["duplicate_merges"] == 1
    assert entry["terminal_reason"] == "unobserved"
    assert entry["deduped_survivor"] is True


# 4: excluded candidates keep the existing reason and never gain a guess.
def test_window_exclusion_keeps_observed_reason() -> None:
    trace = SelectionTraceCollector()
    trace.note_seen(CASES)
    trace.note_normalized(CASES)
    trace.note_materialized(CASES)
    trace.note_window(CASES, selected=False, reason="window_limit_reached")

    entry = _entry(trace.to_payload(), CASES)
    assert entry["filter_decision"] == "rejected"
    assert "window_limit_reached" in entry["filter_reason"]
    assert entry["terminal_reason"] == "candidate_pool_excluded"


# 5: scheduler never saw it -> unobserved, never "rejected".
def test_scheduler_unseen_is_unobserved_not_rejected() -> None:
    trace = SelectionTraceCollector()
    trace.note_seen(CASES)
    trace.note_materialized(CASES)
    trace.note_pool_entered(CASES, pool_class="cluster_x")

    entry = _entry(trace.to_payload(), CASES)
    assert entry["entered_scheduler"] is False
    assert entry["scheduler_decision"] == ""
    assert entry["terminal_reason"] == "unobserved"


# 6: seen by the scheduler but not selected.
def test_scheduler_seen_but_not_selected() -> None:
    trace = SelectionTraceCollector()
    trace.note_seen(CASES)
    trace.note_materialized(CASES)
    trace.note_scheduler_rank(CASES, rank=17)
    trace.note_scheduler(CASES, decision="rejected", reason="covered_cluster")
    trace.note_scheduler_rejected(CASES, stage="covered_cluster")

    entry = _entry(trace.to_payload(), CASES)
    assert entry["entered_scheduler"] is True
    assert entry["scheduler_rank"] == 17
    assert entry["scheduler_decision"] == "rejected"
    assert entry["terminal_reason"] == "scheduler_not_selected"


# 7: an unobserved read outcome stays unobserved; the window skip is named.
def test_unobserved_read_never_guesses_budget() -> None:
    blind = SelectionTraceCollector()
    blind.note_seen(CASES)
    entry = _entry(blind.to_payload(), CASES)
    assert entry["terminal_reason"] == "unobserved"
    assert entry["read_skip_reason"] == ""

    window = SelectionTraceCollector()
    window.note_seen(CASES)
    window.note_read(CASES, dispatched=False, skip_reason="research_window_closed")
    entry = _entry(window.to_payload(), CASES)
    assert entry["terminal_reason"] == "other_observed_reason"
    assert "research_window_closed" in entry["read_skip_reason"]

    budget = SelectionTraceCollector()
    budget.note_seen(CASES)
    budget.note_read(CASES, dispatched=False, skip_reason="read_budget_exhausted")
    assert _entry(budget.to_payload(), CASES)["terminal_reason"] == "read_budget_exhausted"


# 8: first observed drop is stable and never overwritten by later state.
def test_first_drop_reason_is_stable() -> None:
    trace = SelectionTraceCollector()
    trace.note_seen(CASES)
    trace.note_materialized(CASES)
    trace.note_window(CASES, selected=False, reason="window_limit_reached")
    trace.note_scheduler_rank(CASES, rank=1)
    trace.note_scheduler_rejected(CASES, stage="budget")

    entry = _entry(trace.to_payload(), CASES)
    assert entry["terminal_reason"] == "candidate_pool_excluded"
    assert entry["observed_drops"][0] == "candidate_pool_excluded"
    assert entry["observed_drops"][-1] == "read_budget_exhausted"

    read = SelectionTraceCollector()
    read.note_read(CASES, dispatched=True)
    assert _entry(read.to_payload(), CASES)["terminal_reason"] == ""


# 9 + 10: the trace never changes candidate order, caps or batch outcomes.
def test_trace_does_not_change_selection_or_budget() -> None:
    urls = [f"https://example.com/{index}" for index in range(7)]
    first = merge_candidate_pool(
        [(_planned(), tuple(_raw(url) for url in urls), ("bing_rss",))],
        max_candidates=4,
    )
    second = merge_candidate_pool(
        [(_planned(), tuple(_raw(url) for url in urls), ("bing_rss",))],
        max_candidates=4,
        trace=SelectionTraceCollector(),
    )
    assert first == second
    assert [item.canonical_url for item in first] == [
        item.canonical_url for item in second
    ]

    payload = _payload(urls[:2])
    plain = execute_candidate_pool_batch(
        _batch(urls[:2]), search_exact=lambda query, max_results: payload
    )
    traced = execute_candidate_pool_batch(
        _batch(urls[:2]),
        search_exact=lambda query, max_results: payload,
        trace=SelectionTraceCollector(),
    )
    assert plain.candidates == traced.candidates
    assert plain.outcomes == traced.outcomes


# 11: the payload lives in metrics only; it never enters any cursor contract.
def test_payload_stays_out_of_cursor_contract() -> None:
    from src.application.active_research_runtime import _flush_selection_trace

    trace = SelectionTraceCollector()
    trace.note_seen(CASES)
    context: dict = {}
    _flush_selection_trace(context, trace)
    assert set(context) == {"claim_engine_metrics"}
    assert "selection_trace" in context["claim_engine_metrics"]


# 12: same input -> identical payload, and terminal vocabulary is frozen.
def test_deterministic_payload_and_reason_vocabulary() -> None:
    def payload() -> dict:
        trace = SelectionTraceCollector()
        trace.note_seen(CASES)
        trace.note_normalized(CASES)
        trace.note_materialized(CASES)
        trace.note_pool_entered(CASES, pool_class="cluster_x")
        trace.note_scheduler_rank(CASES, rank=2)
        trace.note_scheduler_rejected(CASES, stage="wave")
        return trace.to_payload()

    assert payload() == payload()
    assert TERMINAL_REASONS == (
        "not_materialized",
        "canonical_duplicate",
        "authority_or_policy_filter",
        "candidate_pool_excluded",
        "scheduler_not_selected",
        "read_budget_exhausted",
        "already_read",
        "unsupported_url",
        "other_observed_reason",
        "unobserved",
    )


def test_resume_hydration_preserves_observed_drops() -> None:
    trace = SelectionTraceCollector()
    trace.note_seen(CASES)
    trace.note_window(CASES, selected=False, reason="window_limit_reached")
    payload = trace.to_payload()

    restored = SelectionTraceCollector.from_payload(json.loads(json.dumps(payload)))
    entry = _entry(restored.to_payload(), CASES)
    assert entry["terminal_reason"] == "candidate_pool_excluded"
    assert entry["observed_drops"] == ["candidate_pool_excluded"]


def test_runtime_merge_records_duplicate_and_cap() -> None:
    from src.application.active_research_runtime import _merge_runtime_candidates
    from src.web.research.runtime import RuntimeCandidate

    existing = (
        RuntimeCandidate(
            id="candidate_a",
            url=CASES,
            title="Title",
            snippet="Snippet",
            source="",
            published_at="",
            query_ids=("q1",),
            intents=("fact",),
            providers=("bing_rss",),
            first_seen_rank=1,
        ),
    )
    incoming = (
        CandidatePoolItem(
            id="candidate_a",
            canonical_url=CASES,
            url=CASES,
            title="Longer title here",
            snippet="Snippet",
            source="",
            published_at="",
            query_ids=("q2",),
            intents=(GapSearchIntent.PRIMARY,),
            providers=("bing_rss",),
            first_seen_rank=1,
        ),
        CandidatePoolItem(
            id="candidate_b",
            canonical_url="https://example.com/new",
            url="https://example.com/new",
            title="New",
            snippet="Snippet",
            source="",
            published_at="",
            query_ids=("q2",),
            intents=(GapSearchIntent.PRIMARY,),
            providers=("bing_rss",),
            first_seen_rank=2,
        ),
    )
    trace = SelectionTraceCollector()
    merged = _merge_runtime_candidates(
        existing, incoming, max_candidates=1, trace=trace
    )
    assert [item.url for item in merged] == [CASES]

    duplicate = _entry(trace.to_payload(), CASES)
    assert duplicate["duplicate_merges"] == 1
    assert duplicate["terminal_reason"] == "unobserved"
    capped = _entry(trace.to_payload(), "https://example.com/new")
    assert capped["terminal_reason"] == "candidate_pool_excluded"
    assert "runtime_merge" in capped["filter_reason"]
