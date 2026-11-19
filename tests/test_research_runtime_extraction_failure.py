"""Claim extraction failures retain source-first, live-cursor ordering."""

from __future__ import annotations

from typing import Any, cast

import pytest

import src.application.research_runtime_extraction_failure as failure_module
from src.application.research_runtime_extraction_failure import (
    ExtractionFailureContext,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.web.research.contracts import ResearchState
from src.web.research.failure_contracts import ResearchFailureCode
from src.web.research.runtime import ResearchRuntimeCursor, runtime_failure_id


def _case() -> tuple[ExtractionFailureContext, ActiveRuntimeLiveValues, dict[str, Any]]:
    live = ActiveRuntimeLiveValues(
        state=cast(ResearchState, object()),
        cursor=ResearchRuntimeCursor(),
        context={"run_attempt": 2},
    )
    source = {
        "candidate_id": "source-a",
        "extractions": {"claim-old": {"status": "eligible"}},
        "extraction": {"status": "eligible", "claim_id": "claim-old"},
    }
    return ExtractionFailureContext(live), live, source


@pytest.mark.parametrize(
    ("reason", "code", "logical_id"),
    [
        (
            "blocked_by_policy",
            "policy_blocked",
            "policy:research_evidence_extract:run-a:claim-a:source-a:1",
        ),
        (
            "model_call_attempts_exhausted",
            "model_attempts_exhausted",
            "research_evidence_extract:run-a:claim-a:source-a:1",
        ),
        (
            "malformed_evidence",
            "extraction_failed",
            "research_evidence_extract:run-a:claim-a:source-a:1",
        ),
        (
            "model_call_attempts_exhausted",
            "model_attempts_exhausted",
            "research_evidence_extract:run-a:claim-a:source-a:1:resumed",
        ),
    ],
    ids=["policy", "preflight_exhausted", "extractor_rejected", "extractor_exhausted"],
)
def test_failure_keeps_source_alias_and_canonical_audit(
    reason: str, code: ResearchFailureCode, logical_id: str
) -> None:
    context, live, source = _case()
    selected_sources = [source]
    initial_state, initial_cursor = live.state, live.cursor
    legacy = source["extraction"]
    previous = source["extractions"]["claim-old"]

    context.record(
        source_record=source,
        claim_id="claim-a",
        candidate_id="source-a",
        reason=reason,
        failure_code=code,
        logical_call_id=logical_id,
    )

    assert selected_sources[0] is source
    assert source["extractions"]["claim-old"] is previous
    assert source["extraction"] is legacy
    assert source["extractions"]["claim-a"] == {
        "status": "extractor_failed",
        "reason": reason,
    }
    assert live.state is initial_state and live.cursor is not initial_cursor
    assert len(live.cursor.failures) == 1
    (failure,) = live.cursor.failures
    assert (failure.code, failure.phase, failure.item_id, failure.detail) == (
        code,
        "extracting",
        "source-a",
        reason,
    )
    assert failure.attempt_id == "run-attempt:2"
    assert failure.failure_id == runtime_failure_id(
        logical_call_id=logical_id, code=code
    )

    # The existing failure projection deduplicates a replayed logical failure.
    context.record(
        source_record=source,
        claim_id="claim-a",
        candidate_id="source-a",
        reason=reason,
        failure_code=code,
        logical_call_id=logical_id,
    )
    assert len(live.cursor.failures) == 1


def test_failure_uses_rebound_cursor_and_context() -> None:
    context, live, source = _case()
    stale_cursor = live.cursor
    rebound_cursor = ResearchRuntimeCursor()
    live.cursor = rebound_cursor
    live.context = {"run_attempt": 9}

    context.record(
        source_record=source,
        claim_id="claim-b",
        candidate_id="source-a",
        reason="extractor_unavailable",
        failure_code="extraction_failed",
        logical_call_id="research_evidence_extract:run-a:claim-b:source-a:1",
    )

    assert stale_cursor.failures == ()
    assert rebound_cursor.failures == ()
    assert live.cursor is not rebound_cursor
    assert live.cursor.failures[0].attempt_id == "run-attempt:9"
    assert set(source["extractions"]) == {"claim-old", "claim-b"}


def test_failed_audit_projection_leaves_partial_source_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, live, source = _case()
    original_cursor = live.cursor

    def fail_projection(*args: Any, **kwargs: Any) -> ResearchRuntimeCursor:
        assert source["extractions"]["claim-a"]["reason"] == "extractor_failed"
        raise RuntimeError("cannot append failure")

    monkeypatch.setattr(
        failure_module, "with_appended_runtime_failure", fail_projection
    )
    with pytest.raises(RuntimeError, match="cannot append failure"):
        context.record(
            source_record=source,
            claim_id="claim-a",
            candidate_id="source-a",
            reason="extractor_failed",
            failure_code="extraction_failed",
            logical_call_id="research_evidence_extract:run-a:claim-a:source-a:1",
        )

    assert live.cursor is original_cursor
    assert len(source["extractions"]) == 2
