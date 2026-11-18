"""The search boundary observes results but never settles durable attempts."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import Mock

import pytest

from src.application.research_runtime_search_execution import (
    ActiveSearchQueryExecution,
)
from src.web.research.active_adapter import ActiveResearchGateway
from src.web.research.runtime import (
    ResearchRuntimeCursor,
    RuntimeCandidate,
    RuntimePlannedQuery,
)
from src.web.research.timing_ledger import RuntimePhaseTiming, TimingLedger


@pytest.fixture
def search_case() -> tuple[ActiveSearchQueryExecution, Mock, dict[str, Any]]:
    """Share the same deadline, phase and diagnostics setup across outcomes."""

    gateway = Mock(spec=ActiveResearchGateway)
    gateway.last_search_audit.return_value = {"providers_attempted": ["provider-1"]}
    context: dict[str, Any] = {
        "claim_engine_metrics": {
            "deeper_targeting": {
                "recent": [
                    {
                        "page_intent": {"kind": "official", "path_terms": ["report"]},
                        "query_variants": ["first report", "second report"],
                    }
                ]
            }
        }
    }
    timing = RuntimePhaseTiming(ledger=TimingLedger(lambda: 0.0), now=lambda: 5.0)
    timing.ledger.start_wave(1)
    execution = ActiveSearchQueryExecution(
        gateway=cast(ActiveResearchGateway, gateway),
        monotonic=lambda: 100.0,
        hard_seconds_left=lambda: 15.0,
        reserve_seconds=4.0,
        phase_timing=timing,
        context=context,
        claim_id="claim-1",
        cursor=ResearchRuntimeCursor(
            planned_queries=(
                RuntimePlannedQuery(
                    id="query-1",
                    gap_id="gap-1",
                    claim_id="claim-1",
                    intent="discovery",
                    query="first report",
                ),
            ),
            candidates=(
                RuntimeCandidate(
                    id="candidate-1",
                    url="https://official.example/report",
                    title="Report",
                    query_ids=("query-1",),
                ),
            ),
            evidence_lead_followups=(
                {
                    "source_candidate_id": "candidate-1",
                    "trusted_primary_domain": "official.example",
                    "hint_terms": ["report"],
                },
            ),
        ),
    )
    return execution, gateway, context


def test_search_context_preserves_deadline_audit_and_observation(
    search_case: tuple[ActiveSearchQueryExecution, Mock, dict[str, Any]],
) -> None:
    execution, gateway, context = search_case
    payload = {
        "status": "ok",
        "results": [
            {"url": "https://official.example/report", "title": "First report"}
        ],
    }
    gateway.search_detailed.return_value = payload

    assert execution.search_exact("first report", max_results=3) is payload
    gateway.search_detailed.assert_called_once_with(
        "first report", max_items=3, deadline=111.0
    )
    assert execution.audit == {"providers_attempted": ["provider-1"]}
    metrics = context["claim_engine_metrics"]
    record = metrics["search_discovery"]["queries"][0]
    assert record["slot_index"] == 1
    assert record["claim_id"] == "claim-1"
    assert record["hint_terms"] == ["report"]
    assert record["generated_query_variants"] == ["first report", "second report"]
    assert record["result_count"] == 1
    assert metrics["phase_seconds"]["search"]["calls"] == 1
    assert execution.phase_timing.started == {}

    execution.search_exact("second report")
    assert metrics["search_discovery"]["queries"][-1]["slot_index"] == 2


def test_failed_search_context_ends_phase_without_fabricating_audit(
    search_case: tuple[ActiveSearchQueryExecution, Mock, dict[str, Any]],
) -> None:
    execution, gateway, context = search_case
    gateway.search_detailed.side_effect = TimeoutError("provider timeout")

    with pytest.raises(TimeoutError, match="provider timeout"):
        execution.search_exact("first report")

    assert execution.audit is None
    assert gateway.last_search_audit.call_count == 0
    assert "search_discovery" not in context["claim_engine_metrics"]
    assert context["claim_engine_metrics"]["phase_seconds"]["search"]["calls"] == 1
    assert execution.phase_timing.started == {}
