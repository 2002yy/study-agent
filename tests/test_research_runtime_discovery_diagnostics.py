"""Discovery audit counters always target the latest live persistence context."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any, cast

import pytest

from src.application.research_runtime_assessment_results import ACTIVE_RESEARCH_ASSESSMENTS_KEY

from src.application.research_runtime_discovery_diagnostics import (
    ActiveDiscoveryDiagnosticsContext,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.web.research.contracts import ResearchState
from src.web.research.deeper_targeting import AUTHORITY_OFFICIAL, GapHint
from src.web.research.page_intent import infer_page_intent
from src.web.research.runtime import RuntimeCandidate, RuntimeReadOutcome
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


def test_tier2_funnel_joins_current_inputs_after_context_and_cursor_rebind() -> None:
    first = {
        ACTIVE_RESEARCH_METRICS_KEY: {
            "tier2_proposal": [{"claim_id": "old", "added_candidate_ids": ["old-id"]}],
        },
    }
    live = _live(first)
    audit = ActiveDiscoveryDiagnosticsContext(live)
    audit.record_tier2_funnel(brief={}, selected_sources=[])
    snapshot = deepcopy(first)

    live.context = {
        ACTIVE_RESEARCH_METRICS_KEY: {
            "tier2_proposal": [
                None,
                {"claim_id": "one", "added_candidate_ids": ["proposed"]},
            ],
            "domain_targeted": [
                {"claim_id": "two", "added_candidate_ids": ["targeted"]},
            ],
            "unrelated": "preserved",
        },
        ACTIVE_RESEARCH_ASSESSMENTS_KEY: {
            "one": [
                {
                    "candidate": {"id": "proposed"},
                    "assessment": {"relevance": "answer_relevant"},
                }
            ],
            "two": "unreadable",
        },
    }
    live.cursor = replace(
        live.cursor,
        read_outcomes=(
            RuntimeReadOutcome(
                candidate_id="proposed", status="success", evidence_id="e-proposed"
            ),
            RuntimeReadOutcome(candidate_id="targeted", status="failed"),
        ),
    )
    rebound_cursor = live.cursor
    sources = [
        {
            "candidate_id": "proposed",
            "extractions": {
                "one": {"relation": "supports"},
                "two": {"relation": "lead"},
                "three": {"relation": "supports"},
            },
        },
        {"candidate_id": "targeted", "extractions": {}},
    ]
    brief = {"eligible_evidence": [{"evidence_id": "e-proposed"}, {"evidence_id": "unrelated"}]}
    sources_before, brief_before = deepcopy(sources), deepcopy(brief)

    audit.record_tier2_funnel(brief=brief, selected_sources=sources)

    metrics = live.context[ACTIVE_RESEARCH_METRICS_KEY]
    assert metrics["discovery_funnel"] == {
        "proposed_candidates": 2,
        "by_discovery_method": {"domain_targeted": 1, "llm_proposed": 1},
        "assessed_answer_relevant": 1,
        "read": 1,
        "extracted_supports": 1,
        "gate_eligible": 1,
        "rows": [
            {
                "claim_id": "one",
                "candidate_id": "proposed",
                "discovery_method": "llm_proposed",
                "proposed": True,
                "assessed_answer_relevant": True,
                "read": True,
                "extraction_relations": ["lead", "supports"],
                "gate_eligible": True,
            },
            {
                "claim_id": "two",
                "candidate_id": "targeted",
                "discovery_method": "domain_targeted",
                "proposed": True,
                "assessed_answer_relevant": False,
                "read": False,
                "extraction_relations": [],
                "gate_eligible": False,
            },
        ],
    }
    assert metrics["unrelated"] == "preserved"
    assert first == snapshot
    assert live.cursor is rebound_cursor
    assert sources == sources_before and brief == brief_before


@pytest.mark.parametrize(
    "metrics",
    [
        None,
        "malformed",
        {"discovery_funnel": {"previous": True}, "tier2_proposal": [None]},
    ],
)
def test_tier2_funnel_leaves_context_unchanged_without_proposals(metrics: Any) -> None:
    context = {} if metrics is None else {ACTIVE_RESEARCH_METRICS_KEY: metrics}
    initial = deepcopy(context)
    audit = ActiveDiscoveryDiagnosticsContext(_live(context))

    audit.record_tier2_funnel(brief={}, selected_sources=[])

    assert context == initial
