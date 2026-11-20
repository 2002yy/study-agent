from __future__ import annotations

from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.contracts import ResearchBudget, ResearchState, build_research_state
from src.web.research.state import (
    CLAIM_ENGINE_CONTEXT_KEY,
    attach_claim_engine_state,
    load_claim_engine_state,
)


class _UnusedGateway:
    """WebLookupService.create does not call the provider."""


def _budget() -> ResearchBudget:
    return ResearchBudget(
        max_candidates=20,
        max_reads=8,
        soft_timeout_seconds=45,
        hard_timeout_seconds=60,
        max_total_chars=16000,
    )


def _empty_shadow_state() -> ResearchState:
    """Persistence sample; only tests need a synthetic empty shadow state."""
    return build_research_state(
        mode="shadow",
        questions=(),
        claims=(),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=_budget(),
        known_evidence_ids=(),
    )


def test_attach_copies_context_and_loads_valid_state() -> None:
    original = {"research_mode": "deep", "candidate_items": []}
    state = _empty_shadow_state()

    updated = attach_claim_engine_state(
        original,
        state,
        known_evidence_ids=(),
    )
    loaded = load_claim_engine_state(updated, known_evidence_ids=())

    assert CLAIM_ENGINE_CONTEXT_KEY not in original
    assert updated is not original
    assert loaded.available is True
    assert loaded.status == "available"
    assert loaded.effective_mode == "shadow"
    assert loaded.state == state


def test_legacy_context_without_claim_engine_remains_off() -> None:
    result = load_claim_engine_state(
        {"research_mode": "standard", "run_attempt": 2},
        known_evidence_ids=(),
    )

    assert result.status == "absent"
    assert result.effective_mode == "off"
    assert result.state is None
    assert result.reason == "claim_engine_absent"


def test_old_or_invalid_state_degrades_to_bounded_shadow_unavailable() -> None:
    old = load_claim_engine_state(
        {CLAIM_ENGINE_CONTEXT_KEY: {"schema_version": "research-state-v0"}},
        known_evidence_ids=(),
    )
    invalid = load_claim_engine_state(
        {
            CLAIM_ENGINE_CONTEXT_KEY: {
                "schema_version": "research-state-v1",
                "raw_page_body": "must never be replayed",
            }
        },
        known_evidence_ids=(),
    )

    assert (old.status, old.effective_mode, old.reason) == (
        "unavailable",
        "shadow",
        "unsupported_claim_engine_schema",
    )
    assert (invalid.status, invalid.effective_mode, invalid.reason) == (
        "unavailable",
        "shadow",
        "invalid_claim_engine_state",
    )
    assert old.state is None
    assert invalid.state is None


def test_repository_checkpoint_round_trip_keeps_single_owner(tmp_path) -> None:
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = WebLookupRepository(database)
    service = WebLookupService(repository, _UnusedGateway())  # type: ignore[arg-type]
    planned = service.create("persistence adapter audit", research_mode="deep")
    owned = repository.begin_operation(
        planned.id,
        operation_id="op_claim_engine",
        stage="searching",
    )
    context = attach_claim_engine_state(
        owned.research_context,
        _empty_shadow_state(),
        known_evidence_ids=(),
    )

    checkpointed = repository.checkpoint(
        planned.id,
        operation_id="op_claim_engine",
        research_context=context,
        query_attempts=owned.query_attempts,
        selected_sources=owned.selected_sources,
        rejected_sources=owned.rejected_sources,
        items=owned.items,
        warnings=owned.warnings,
    )
    restored = WebLookupRepository(database).get(planned.id)

    assert restored is not None
    assert restored.version == checkpointed.version
    assert restored.active_operation_id == "op_claim_engine"
    loaded = load_claim_engine_state(restored.research_context, known_evidence_ids=())
    assert loaded.available is True
    assert loaded.state == _empty_shadow_state()
