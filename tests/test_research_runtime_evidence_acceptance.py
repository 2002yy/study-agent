"""Accepted extraction writes retain source aliases and live state ordering."""

from __future__ import annotations

from typing import Any, cast

import pytest

import src.application.research_runtime_evidence_acceptance as acceptance_module
from src.application.research_runtime_evidence_acceptance import (
    ExtractedEvidenceAcceptanceContext,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_result_buffers import ActiveResearchResultBuffers
from src.web.research.active_semantics import ExtractedEvidenceLink
from src.web.research.contracts import ResearchState
from src.web.research.runtime import ResearchRuntimeCursor, RuntimeReadOutcome


def _link(claim_id: str) -> ExtractedEvidenceLink:
    return ExtractedEvidenceLink(
        candidate_id="source-a",
        claim_id=claim_id,
        source_role="primary",
        source_cluster_id="cluster-a",
        relation="supports",
        strength=0.8,
        locator="Section 2",
        anchored_spans=("measured value",),
        caveats=("time limited",),
        published_at="2026-11-20",
    )


def _case() -> tuple[
    ExtractedEvidenceAcceptanceContext, ActiveRuntimeLiveValues, dict[str, Any]
]:
    record: dict[str, Any] = {
        "candidate_id": "source-a",
        "extractions": {},
        "extraction": {"status": "extractor_failed"},
    }
    buffers = ActiveResearchResultBuffers([], [record], [], [])
    live = ActiveRuntimeLiveValues(
        state=cast(ResearchState, object()),
        cursor=ResearchRuntimeCursor(
            read_outcomes=(
                RuntimeReadOutcome(candidate_id="source-a", status="success"),
                RuntimeReadOutcome(candidate_id="source-b", status="failed"),
            ),
        ),
    )
    return ExtractedEvidenceAcceptanceContext("run-a", live, buffers), live, record


def test_acceptance_preserves_source_alias_and_updates_state_before_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, live, record = _case()
    original_state, original_cursor = live.state, live.cursor
    next_state = cast(ResearchState, object())
    events: list[str] = []

    def find_id(run_id: str, source: dict, selected: list, rejected: list) -> str:
        events.append("identity")
        assert run_id == "run-a" and source is record
        assert selected is owner.results.selected_sources and selected[0] is record
        assert rejected is owner.results.rejected_sources
        assert record["extractions"]["claim-1"]["status"] == "eligible"
        assert record["extraction"]["claim_id"] == "claim-1"
        assert live.state is original_state and live.cursor is original_cursor
        return "evidence-a"

    def add(state: ResearchState, *, evidence_id: str, link: Any) -> ResearchState:
        events.append("state")
        assert events == ["identity", "state"]
        assert state is original_state and evidence_id == "evidence-a"
        assert link.claim_id == "claim-1"
        return next_state

    monkeypatch.setattr(acceptance_module, "_evidence_id_for_record", find_id)
    monkeypatch.setattr(acceptance_module, "_add_extracted_evidence", add)
    evidence_id = owner.accept(
        record=record,
        candidate_id="source-a",
        claim_id="claim-1",
        link=_link("claim-1"),
    )

    assert evidence_id == "evidence-a"
    assert live.state is next_state and live.cursor is not original_cursor
    assert [item.evidence_id for item in live.cursor.read_outcomes] == [
        "evidence-a",
        "",
    ]
    assert owner.results.selected_sources[0] is record
    assert record["extractions"]["claim-1"] is not record["extraction"]
    assert record["extractions"]["claim-1"] == record["extraction"]


def test_acceptance_rebinds_state_and_keeps_first_eligible_legacy_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, live, record = _case()
    initial_state = live.state
    states_seen: list[ResearchState] = []
    state_after_first = cast(ResearchState, object())
    recovered_state = cast(ResearchState, object())
    state_after_second = cast(ResearchState, object())

    monkeypatch.setattr(
        acceptance_module, "_evidence_id_for_record", lambda *args: "evidence-a"
    )

    def add(state: ResearchState, *, evidence_id: str, link: Any) -> ResearchState:
        states_seen.append(state)
        return state_after_first if link.claim_id == "claim-1" else state_after_second

    monkeypatch.setattr(acceptance_module, "_add_extracted_evidence", add)
    owner.accept(
        record=record,
        candidate_id="source-a",
        claim_id="claim-1",
        link=_link("claim-1"),
    )
    first_summary = record["extraction"]
    assert live.state is state_after_first

    # A checkpoint/steering rebind must not leave acceptance pointing at the
    # previous state or cursor, and multiple claim bindings share one source.
    live.state = recovered_state
    recovered_cursor = ResearchRuntimeCursor(
        read_outcomes=(RuntimeReadOutcome(candidate_id="source-a", status="success"),)
    )
    live.cursor = recovered_cursor
    owner.accept(
        record=record,
        candidate_id="source-a",
        claim_id="claim-2",
        link=_link("claim-2"),
    )
    assert states_seen == [initial_state, recovered_state]
    assert live.state is state_after_second and live.cursor is not recovered_cursor
    assert live.cursor.read_outcomes[0].evidence_id == "evidence-a"
    assert record["extraction"] is first_summary
    assert set(record["extractions"]) == {"claim-1", "claim-2"}
    assert record["extractions"]["claim-2"]["claim_id"] == "claim-2"


def test_identity_failure_keeps_partial_record_but_does_not_advance_live_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, live, record = _case()
    state, cursor = live.state, live.cursor

    def fail_identity(*args: Any) -> str:
        raise ValueError("identity unavailable")

    monkeypatch.setattr(acceptance_module, "_evidence_id_for_record", fail_identity)
    with pytest.raises(ValueError, match="identity unavailable"):
        owner.accept(
            record=record,
            candidate_id="source-a",
            claim_id="claim-1",
            link=_link("claim-1"),
        )

    assert record["extractions"]["claim-1"]["status"] == "eligible"
    assert record["extraction"]["claim_id"] == "claim-1"
    assert live.state is state and live.cursor is cursor


def test_state_projection_failure_keeps_record_but_not_cursor_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, live, record = _case()
    state, cursor = live.state, live.cursor
    monkeypatch.setattr(
        acceptance_module, "_evidence_id_for_record", lambda *args: "evidence-a"
    )

    def fail_projection(*args: Any, **kwargs: Any) -> ResearchState:
        raise RuntimeError("projection unavailable")

    monkeypatch.setattr(acceptance_module, "_add_extracted_evidence", fail_projection)
    with pytest.raises(RuntimeError, match="projection unavailable"):
        owner.accept(
            record=record,
            candidate_id="source-a",
            claim_id="claim-1",
            link=_link("claim-1"),
        )

    assert record["extractions"]["claim-1"]["status"] == "eligible"
    assert live.state is state and live.cursor is cursor
    assert live.cursor.read_outcomes[0].evidence_id == ""
