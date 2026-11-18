"""Reader-chain evidence and diagnostics must not own runtime state."""

import pytest

from src.application.research_runtime_read_observability import (
    _record_read_chain_decision,
)
from src.application.research_runtime_read_projection import project_read_chain
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.chain_executor import ChainRun, ChainStepResult
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


def _candidate() -> CandidatePoolItem:
    return CandidatePoolItem(
        id="candidate-a",
        url="https://example.org/report",
        canonical_url="https://example.org/report",
        title="Report",
        snippet="",
        source="search",
        published_at="",
        query_ids=(),
        intents=(),
        providers=(),
        first_seen_rank=0,
    )


PLAN = {"source_role": "primary", "cluster_id": "cluster-1", "claim_id": "claim-1"}


def _step(
    backend: str, *, usable: bool, adequacy: str, content: str = ""
) -> ChainStepResult:
    return ChainStepResult(
        backend=backend,
        retrieval_state="fetched" if usable else "failed",
        usable_content=usable,
        adequacy_reason=adequacy,
        content=content,
    )


def test_adequate_step_wins_even_when_a_previous_step_had_usable_text() -> None:
    steps = [
        _step("native_http", usable=True, adequacy="too_short", content="intro"),
        _step("wigolo_http", usable=True, adequacy="ok", content="strong-evidence"),
    ]
    projection = project_read_chain(
        candidate=_candidate(), plan_item=PLAN, chain_steps=steps, source_limit=6
    )
    assert projection.ok and projection.content == "strong"
    assert projection.record["read_status"] == "read"
    assert projection.record["read"]["content"] == "strong"
    assert projection.record["final_backend"] == "wigolo_http"
    assert [row["backend"] for row in projection.record["retrieval_attempts"]] == [
        "native_http",
        "wigolo_http",
    ]
    assert len(steps) == 2


def test_without_adequate_step_first_usable_backend_wins() -> None:
    steps = [
        _step("native_http", usable=False, adequacy="failed"),
        _step("wigolo_http", usable=True, adequacy="too_short", content="short"),
        _step("browser", usable=True, adequacy="not_adequate", content="later"),
    ]
    projected = project_read_chain(
        candidate=_candidate(), plan_item=PLAN, chain_steps=steps, source_limit=6000
    )
    assert projected.ok and projected.content == "short"
    assert projected.record["final_backend"] == "wigolo_http"
    assert len(projected.record["retrieval_attempts"]) == 3


def test_all_failed_steps_keep_last_attempt_provenance_and_one_failed_source() -> None:
    projected = project_read_chain(
        candidate=_candidate(),
        plan_item=PLAN,
        chain_steps=[
            _step("native_http", usable=False, adequacy="error"),
            _step("wigolo_http", usable=False, adequacy="blocked"),
        ],
        source_limit=100,
    )
    assert not projected.ok and projected.content == ""
    assert projected.record["final_backend"] == "wigolo_http"
    assert projected.record["retrieval_state"] == "failed"
    assert projected.record["read_status"] == "failed"
    assert projected.record["evidence_state"] == "invalid_or_rejected"


def test_skipped_chain_has_no_source_projection() -> None:
    with pytest.raises(ValueError, match="empty reader chain"):
        project_read_chain(
            candidate=_candidate(), plan_item=PLAN, chain_steps=[], source_limit=100
        )


def test_chain_diagnostics_keeps_skips_and_limits_history_without_changing_route() -> None:
    chain = ChainRun(
        candidate_id="candidate-a",
        steps=(),
        action="defer",
        reason="backend_unavailable",
        attempted_backends=(),
    )
    metrics = {"read_chain": [{"old": i} for i in range(60)]}
    context = {ACTIVE_RESEARCH_METRICS_KEY: metrics}
    _record_read_chain_decision(
        context, candidate_id="candidate-a", chain_run=chain, chain_steps=[]
    )
    assert len(metrics["read_chain"]) == 60
    assert metrics["read_chain"][0] == {"old": 1}
    assert metrics["read_chain"][-1] == {
        "candidate_id": "candidate-a",
        "action": "defer",
        "reason": "backend_unavailable",
        "attempted_backends": [],
        "steps": [],
    }
    assert chain.reason == "backend_unavailable"

    invalid = {ACTIVE_RESEARCH_METRICS_KEY: "not-a-dict"}
    _record_read_chain_decision(
        invalid, candidate_id="candidate-a", chain_run=chain, chain_steps=[]
    )
    assert invalid[ACTIVE_RESEARCH_METRICS_KEY] == "not-a-dict"
