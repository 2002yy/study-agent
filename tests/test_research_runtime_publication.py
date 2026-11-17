"""Freeze terminal evidence payloads without a real repository or model call."""

from __future__ import annotations

from typing import Any, cast

import pytest

from src.application import research_runtime_publication as publication
from src.application.research_runtime_checkpoint import ActiveResearchResultBuffers
from src.application.research_runtime_publication import ActiveResearchPublisher
from src.application.research_stop_gate import ResearchStopDecision
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.contracts import ResearchState


class _RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def complete(self, run_id: str, **kwargs: Any) -> Any:
        self.calls.append((run_id, kwargs))
        return kwargs


def _publisher() -> tuple[ActiveResearchPublisher, _RecordingRepository]:
    repository = _RecordingRepository()
    buffers = ActiveResearchResultBuffers(
        query_attempts=[{"query": "original"}],
        selected_sources=[],
        rejected_sources=[{"candidate_id": "rejected"}],
        warnings=["duplicate", "duplicate", "  "],
    )
    return (
        ActiveResearchPublisher(
            repository=cast(WebLookupRepository, repository),
            run_id="run-a",
            operation_id="lease-a",
            buffers=buffers,
        ),
        repository,
    )


def _stop() -> ResearchStopDecision:
    return ResearchStopDecision(
        decision="success",
        reason="evidence_gate_pass",
        provider_status="found",
        answer_confidence="high",
        final_status="completed",
    )


def test_completion_uses_current_context_and_shared_result_lists() -> None:
    publisher, repository = _publisher()
    publisher.buffers.selected_sources.append(
        {"item": {"url": "https://read.example"}, "extraction": {"status": "eligible"}}
    )
    latest_context = {"run_attempt": 2}
    returned = publisher.complete(
        context=latest_context,
        brief={"gate_status": "pass", "answer_instruction": "cite the read page"},
        stop=_stop(),
    )
    assert len(repository.calls) == 1
    assert repository.calls[0][0] == "run-a"
    assert returned["operation_id"] == "lease-a"
    assert returned["research_context"] is latest_context
    assert returned["query_attempts"] is publisher.buffers.query_attempts
    assert returned["selected_sources"] is publisher.buffers.selected_sources
    assert returned["rejected_sources"] is publisher.buffers.rejected_sources
    assert returned["items"] == [{"url": "https://read.example"}]
    assert returned["warnings"] == ["duplicate"]
    assert "Evidence Gate: pass" in returned["source_block"]
    assert returned["stop_reason"] == "evidence_gate_pass"
    assert returned["answer_confidence"] == "high"
    assert returned["final_status"] == "completed"


def test_hard_budget_keeps_exception_path_confidence_override() -> None:
    publisher, _ = _publisher()
    stop = ResearchStopDecision(
        decision="partial",
        reason="evidence_budget_exhausted",
        provider_status="insufficient",
        answer_confidence="partial",
        final_status="partial",
    )
    returned = publisher.complete(
        context={"run_attempt": 1},
        stop=stop,
        brief={"gate_status": "insufficient"},
        answer_confidence="none",
    )
    assert returned["answer_confidence"] == "none"
    assert returned["provider_status"] == "insufficient"
    assert returned["stop_reason"] == "evidence_budget_exhausted"
    assert returned["final_status"] == "partial"


def test_exception_evidence_projection_keeps_argument_order(monkeypatch) -> None:
    publisher, repository = _publisher()
    stop = ResearchStopDecision(
        decision="unavailable",
        reason="active_runtime_unavailable",
        provider_status="unavailable",
        final_status="failed",
    )
    steps: list[str] = []
    old_items = publication._eligible_items
    old_format = publication._format_evidence_brief
    old_dedupe = publication._dedupe

    def items(records):
        steps.append("items")
        return old_items(records)

    def evidence(state, gate, records):
        steps.append("brief")
        assert gate is None
        assert records is publisher.buffers.selected_sources
        return {"gate_status": "unavailable"}

    def formatted(brief):
        steps.append("source_block")
        return old_format(brief)

    def warnings(values):
        steps.append("warnings")
        return old_dedupe(values)

    monkeypatch.setattr(publication, "_eligible_items", items)
    monkeypatch.setattr(publication, "_evidence_brief", evidence)
    monkeypatch.setattr(publication, "_format_evidence_brief", formatted)
    monkeypatch.setattr(publication, "_dedupe", warnings)
    returned = publisher.complete(
        context={"run_attempt": 1},
        stop=stop,
        state_for_exception=cast(ResearchState, object()),
        extra_warning="active research became unavailable",
        answer_confidence="partial",
        final_status="partial",
    )
    assert steps == ["items", "brief", "source_block", "warnings"]
    assert returned["warnings"] == ["duplicate", "active research became unavailable"]
    assert returned["answer_confidence"] == "partial"
    assert returned["final_status"] == "partial"
    assert returned["stop_reason"] == "active_runtime_unavailable"
    assert len(repository.calls) == 1


def test_missing_evidence_brief_fails_without_terminal_write() -> None:
    publisher, repository = _publisher()
    with pytest.raises(ValueError, match="terminal evidence brief is unavailable"):
        publisher.complete(context={}, stop=_stop())
    assert repository.calls == []
