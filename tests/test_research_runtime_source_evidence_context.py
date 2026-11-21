"""Order, aliasing and live-value contracts for read-site visual attachment."""

from __future__ import annotations

from typing import Any, cast

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_result_buffers import ActiveResearchResultBuffers
from src.application.research_runtime_source_evidence_context import (
    ReadSourceEvidenceContext,
)
from src.web.research.contracts import ResearchState


def _buffers() -> ActiveResearchResultBuffers:
    return ActiveResearchResultBuffers([], [], [], [])


def test_visual_reader_observes_previously_upserted_record_and_live_values() -> None:
    results = _buffers()
    sources = results.selected_sources
    context: dict[str, Any] = {"wave": 2}
    state = cast(ResearchState, object())
    record: dict[str, Any] = {"candidate_id": "a", "read_status": "read"}
    units = [{"unit_id": "figure-a"}]
    calls: list[tuple[object, object, str]] = []

    def visual_reader(
        *, context: Any, state: Any, canonical_url: str
    ) -> list[dict[str, Any]]:
        # A visual read can observe the source in the live publication buffer.
        assert results.selected_sources is sources
        assert sources == [record]
        assert sources[0] is record
        calls.append((context, state, canonical_url))
        context["visual_reads"] = [{"vision_calls": 1}]
        return units

    live = ActiveRuntimeLiveValues(state=state, context=context)
    owner = ReadSourceEvidenceContext(results, live, visual_reader)
    owner.record_projection(
        record,
        ok=True,
        canonical_url="https://source.example/a",
    )

    assert calls == [(context, state, "https://source.example/a")]
    assert calls[0][0] is context and calls[0][1] is state
    assert sources[0]["visual_units"] is units
    assert context["visual_reads"] == [{"vision_calls": 1}]


def test_failed_text_and_empty_visuals_preserve_record_and_no_visual_call() -> None:
    results = _buffers()
    calls: list[str] = []

    def visual_reader(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs["canonical_url"])
        return []

    live = ActiveRuntimeLiveValues(state=cast(ResearchState, object()))
    owner = ReadSourceEvidenceContext(results, live, visual_reader)
    failed = {"candidate_id": "a", "read_status": "failed"}
    owner.record_projection(failed, ok=False, canonical_url="https://a")
    assert calls == []
    assert results.selected_sources == [failed]

    completed = {"candidate_id": "a", "read_status": "read"}
    owner.record_projection(completed, ok=True, canonical_url="https://a")
    assert calls == ["https://a"]
    assert results.selected_sources == [completed]
    assert results.selected_sources[0] is completed
    assert "visual_units" not in completed


def test_rebound_context_and_state_never_use_the_previous_call_values() -> None:
    results = _buffers()
    received: list[tuple[object, object]] = []

    def visual_reader(
        *, context: Any, state: Any, canonical_url: str
    ) -> list[dict[str, Any]]:
        received.append((context, state))
        return [{"unit_id": canonical_url}]

    first_context, second_context = {"wave": 1}, {"wave": 2}
    first_state, second_state = (
        cast(ResearchState, object()),
        cast(ResearchState, object()),
    )
    live = ActiveRuntimeLiveValues(state=first_state, context=first_context)
    owner = ReadSourceEvidenceContext(results, live, visual_reader)
    first_record = {"candidate_id": "same"}
    second_record = {"candidate_id": "same"}
    owner.record_projection(first_record, ok=True, canonical_url="first")
    # An intervening checkpoint can replace both values, while the result
    # buffers retain their identity for the next source.
    live.context = second_context
    live.state = second_state
    owner.record_projection(second_record, ok=True, canonical_url="second")

    assert received[0][0] is first_context and received[0][1] is first_state
    assert received[1][0] is second_context and received[1][1] is second_state
    assert results.selected_sources == [second_record]
    assert results.selected_sources[0] is second_record
    assert second_record["visual_units"] == [{"unit_id": "second"}]
