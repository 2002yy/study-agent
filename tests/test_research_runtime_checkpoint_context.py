"""Checkpoint state projections use the current result buffers after recovery."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import Mock

from src.application.research_runtime_checkpoint import ActiveRuntimeCheckpointContext
from src.application.research_runtime_result_buffers import ActiveResearchResultBuffers
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.contracts import ResearchBudget, build_research_state
from src.web.research.runtime import ResearchRuntimeCursor


def test_prepare_derives_evidence_ids_from_live_result_buffers(monkeypatch: Any) -> None:
    import src.application.research_runtime_checkpoint as checkpoint_module

    results = ActiveResearchResultBuffers([], [], [], [])
    ids_at_prepare: list[tuple[str, ...]] = []
    original_attach = checkpoint_module.attach_claim_engine_state

    def capture_evidence_ids(context: Any, state: Any, *, known_evidence_ids: Any) -> Any:
        ids_at_prepare.append(tuple(known_evidence_ids))
        return original_attach(
            context, state, known_evidence_ids=known_evidence_ids
        )

    # Keep this check independent of source-record format: each new result
    # must be visible to the next checkpoint's identity projection.
    monkeypatch.setattr(
        results,
        "known_evidence_ids",
        lambda run_id: tuple(
            f"{run_id}:{record['id']}" for record in results.selected_sources
        ),
    )
    monkeypatch.setattr(
        checkpoint_module, "attach_claim_engine_state", capture_evidence_ids
    )
    checkpoint = ActiveRuntimeCheckpointContext(
        repository=cast(WebLookupRepository, Mock()),
        run_id="research-1",
        operation_id="operation-1",
        context={},
        state=build_research_state(
            mode="active",
            questions=(),
            claims=(),
            evidence=(),
            evidence_links=(),
            source_clusters=(),
            gaps=(),
            conflict_gaps=(),
            budget=ResearchBudget(
                max_candidates=5,
                max_reads=2,
                soft_timeout_seconds=10,
                hard_timeout_seconds=20,
            ),
            known_evidence_ids=(),
        ),
        cursor=ResearchRuntimeCursor(),
        results=results,
    )

    checkpoint.prepare(stage=None, elapsed=lambda: 1.0)
    results.selected_sources.append({"id": "first"})
    checkpoint.prepare(stage=None, elapsed=lambda: 2.0)

    assert ids_at_prepare == [(), ("research-1:first",)]
    assert checkpoint.state.budget.elapsed_seconds == 2.0
