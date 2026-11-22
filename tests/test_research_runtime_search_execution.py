"""The search boundary observes results but never settles durable attempts."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import Mock

import pytest

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_search_execution import (
    ActiveSearchQueryExecution,
)
from src.application.research_runtime_observation import (
    ActiveRuntimeObservationContext,
)
from src.web.research.active_adapter import ActiveResearchGateway
from src.web.research.contracts import ResearchState
from src.web.research.runtime import (
    ResearchRuntimeCursor,
    RuntimeCandidate,
    RuntimePlannedQuery,
)
from src.web.research.timing_ledger import RuntimePhaseTiming, TimingLedger


@pytest.fixture
def search_case() -> tuple[ActiveSearchQueryExecution, Mock, dict[str, Any], ActiveRuntimeLiveValues]:
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
    cursor = ResearchRuntimeCursor(
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
    )
    live = ActiveRuntimeLiveValues(
        state=cast(ResearchState, object()), cursor=cursor, context=context
    )
    observation = ActiveRuntimeObservationContext(
        live=live,
        phase_timing=timing,
        timing_ledger=timing.ledger,
    )
    execution = ActiveSearchQueryExecution(
        gateway=cast(ActiveResearchGateway, gateway),
        monotonic=lambda: 100.0,
        hard_seconds_left=lambda: 15.0,
        reserve_seconds=4.0,
        observation=observation,
        context=context,
        claim_id="claim-1",
        cursor=cursor,
    )
    return execution, gateway, context, live


def test_search_context_preserves_deadline_audit_and_observation(
    search_case: tuple[ActiveSearchQueryExecution, Mock, dict[str, Any], ActiveRuntimeLiveValues],
) -> None:
    execution, gateway, context, _live = search_case
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
    assert execution.observation.phase_timing.started == {}

    execution.search_exact("second report")
    assert metrics["search_discovery"]["queries"][-1]["slot_index"] == 2


def test_failed_search_context_ends_phase_without_fabricating_audit(
    search_case: tuple[ActiveSearchQueryExecution, Mock, dict[str, Any], ActiveRuntimeLiveValues],
) -> None:
    execution, gateway, context, _live = search_case
    gateway.search_detailed.side_effect = TimeoutError("provider timeout")

    with pytest.raises(TimeoutError, match="provider timeout"):
        execution.search_exact("first report")

    assert execution.audit is None
    assert gateway.last_search_audit.call_count == 0
    assert "search_discovery" not in context["claim_engine_metrics"]
    assert context["claim_engine_metrics"]["phase_seconds"]["search"]["calls"] == 1
    assert execution.observation.phase_timing.started == {}


@pytest.mark.parametrize("raises", [False, True], ids=["success", "exception"])
def test_search_attempt_keeps_frozen_attribution_but_times_latest_context(
    search_case: tuple[ActiveSearchQueryExecution, Mock, dict[str, Any], ActiveRuntimeLiveValues],
    raises: bool,
) -> None:
    execution, gateway, attempted_context, live = search_case

    def search_after_rebind(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        # A recovery/steering callback can replace the live object, but it
        # cannot retroactively change this attempt's query and cursor.
        live.context = {"after_checkpoint": True}
        live.cursor = ResearchRuntimeCursor()
        if raises:
            raise TimeoutError("search interrupted")
        return {"status": "ok", "results": []}

    gateway.search_detailed.side_effect = search_after_rebind
    if raises:
        with pytest.raises(TimeoutError, match="search interrupted"):
            execution.search_exact("first report")
    else:
        execution.search_exact("first report")

    old_metrics = attempted_context["claim_engine_metrics"]
    assert "phase_seconds" not in old_metrics
    assert live.context["claim_engine_metrics"]["phase_seconds"]["search"] == {
        "seconds": 0.0,
        "calls": 1,
    }
    assert execution.context is attempted_context
    assert execution.cursor.planned_queries[0].id == "query-1"
    assert execution.observation.phase_timing.started == {}
    if raises:
        assert "search_discovery" not in old_metrics
        assert execution.audit is None
    else:
        record = old_metrics["search_discovery"]["queries"][0]
        assert record["hint_terms"] == ["report"]
        assert record["slot_index"] == 1
        assert execution.audit == {"providers_attempted": ["provider-1"]}
