"""Discovery audit counters always target the latest live persistence context."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

from src.application.research_runtime_discovery_diagnostics import (
    ActiveDiscoveryDiagnosticsContext,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.web.research.contracts import ResearchState
from src.web.research.deeper_targeting import AUTHORITY_OFFICIAL, GapHint
from src.web.research.page_intent import infer_page_intent
from src.web.research.runtime import RuntimeCandidate
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


def _live(context: dict) -> ActiveRuntimeLiveValues:
    return ActiveRuntimeLiveValues(state=cast(ResearchState, object()), context=context)


def test_lead_counters_keep_nonnegative_amounts_and_follow_context_rebind() -> None:
    first = {ACTIVE_RESEARCH_METRICS_KEY: {"lead_discovery": {"attempts": 2}}}
    live = _live(first)
    audit = ActiveDiscoveryDiagnosticsContext(live)

    audit.bump_lead("attempts", 3)
    audit.bump_lead("attempts", -8)
    assert first[ACTIVE_RESEARCH_METRICS_KEY]["lead_discovery"] == {"attempts": 5}

    # Steering/checkpoint may replace the whole persisted context. The audit
    # context must not keep the previous metrics mapping alive as its owner.
    second: dict = {ACTIVE_RESEARCH_METRICS_KEY: {"lead_discovery": "invalid"}}
    live.context = second
    audit.bump_lead("attempts")
    assert second[ACTIVE_RESEARCH_METRICS_KEY]["lead_discovery"] == {"attempts": 1}
    assert first[ACTIVE_RESEARCH_METRICS_KEY]["lead_discovery"] == {"attempts": 5}


def test_lead_candidate_projection_reads_latest_cursor_and_context_only() -> None:
    first: dict = {ACTIVE_RESEARCH_METRICS_KEY: {"untouched": 1}}
    live = _live(first)
    audit = ActiveDiscoveryDiagnosticsContext(live)
    ordinary = RuntimeCandidate(
        id="ordinary", url="https://example.org", title="Original"
    )
    found = RuntimeCandidate(
        id="lead-1",
        url="https://example.org/lead",
        title="New",
        discovery_method="lead_url",
    )
    live.cursor = replace(live.cursor, candidates=(ordinary, found))
    before_projection = live.cursor

    audit.record_lead_candidate_ids()
    assert first[ACTIVE_RESEARCH_METRICS_KEY] == {
        "untouched": 1,
        "lead_discovered_candidate_ids": ["lead-1"],
    }
    assert live.cursor is before_projection

    # A resumed wave replaces both values; the same audit object must never
    # append IDs into the old context or project the old cursor.
    resumed_context: dict = {}
    resumed_candidate = replace(found, id="lead-2")
    live.context = resumed_context
    live.cursor = replace(live.cursor, candidates=(ordinary, resumed_candidate))
    audit.record_lead_candidate_ids()
    assert resumed_context[ACTIVE_RESEARCH_METRICS_KEY] == {
        "lead_discovered_candidate_ids": ["lead-2"]
    }
    assert first[ACTIVE_RESEARCH_METRICS_KEY]["lead_discovered_candidate_ids"] == [
        "lead-1"
    ]


def test_targeting_keeps_bounded_audit_fields_and_does_not_touch_cursor() -> None:
    live = _live({})
    audit = ActiveDiscoveryDiagnosticsContext(live)
    original_cursor = live.cursor
    gap = GapHint(
        source_url="https://example.org/",
        source_authority_class=AUTHORITY_OFFICIAL,
        relation="lead",
        locator="summary",
        anchors=("missing support details",),
        caveat="does not provide support dates",
        missing_fact_terms=("support", "dates"),
        targeting_strategy="authoritative_deep_page",
    )
    intent = infer_page_intent(
        claim_terms=("product",), missing_fact_terms=("support", "dates")
    )

    for i in range(9):
        audit.record_targeting(
            gap=gap,
            source_url="https://example.org/",
            selected_url=f"https://example.org/docs/{i}",
            selected_depth=i,
            intent=intent,
            variants=("support dates", "official support"),
        )

    metrics = live.context[ACTIVE_RESEARCH_METRICS_KEY]["deeper_targeting"]
    assert metrics["strategy_counts"] == {"authoritative_deep_page": 9}
    assert metrics["page_intent_counts"] == {intent.kind: 9}
    assert len(metrics["recent"]) == 8
    assert metrics["recent"][0]["selected_candidate_depth"] == 1
    assert metrics["recent"][-1]["selected_candidate_depth"] == 8
    assert metrics["recent"][-1]["selected_query_variant"] == "support dates"
    assert metrics["recent"][-1]["gap_hint"] == gap.to_dict()
    assert live.cursor is original_cursor


def test_targeting_missing_gap_uses_current_context_without_old_metrics() -> None:
    first: dict = {}
    live = _live(first)
    audit = ActiveDiscoveryDiagnosticsContext(live)
    audit.record_targeting(
        gap=None, source_url="https://first", selected_url="", selected_depth=0
    )
    first_record = first[ACTIVE_RESEARCH_METRICS_KEY]["deeper_targeting"]
    assert first_record["gap_unavailable"] == 1
    assert first_record["recent"][0]["followup_reason"] == "lead_without_usable_gap"

    live.context = {}
    audit.record_targeting(
        gap=None, source_url="https://second", selected_url="", selected_depth=0
    )
    second_record = live.context[ACTIVE_RESEARCH_METRICS_KEY]["deeper_targeting"]
    assert second_record["gap_unavailable"] == 1
    assert second_record["recent"][0]["source_candidate_url"] == "https://second"
    assert first_record["recent"][0]["source_candidate_url"] == "https://first"
