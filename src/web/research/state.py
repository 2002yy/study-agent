"""Safe adapter for ResearchState inside WebLookupRun.research_context.

The existing WebLookupRepository remains the only persistence and operation
owner. These helpers copy and validate JSON payloads; they do not write to the
database or activate the claim engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping

from src.domain.evidence import build_evidence_snapshot
from src.domain.runtime_entities import WebLookupRun
from src.web.research.contracts import (
    RESEARCH_STATE_SCHEMA_VERSION,
    ResearchState,
)

CLAIM_ENGINE_CONTEXT_KEY = "claim_engine"

ClaimEngineLoadStatus = Literal["absent", "available", "unavailable"]
ClaimEngineEffectiveMode = Literal["off", "shadow", "active"]


@dataclass(frozen=True)
class ClaimEngineLoadResult:
    status: ClaimEngineLoadStatus
    effective_mode: ClaimEngineEffectiveMode
    state: ResearchState | None = None
    reason: str = ""

    @property
    def available(self) -> bool:
        return self.status == "available" and self.state is not None


def attach_claim_engine_state(
    research_context: Mapping[str, Any],
    state: ResearchState,
    *,
    known_evidence_ids: Iterable[str],
) -> dict[str, Any]:
    """Return a copied context containing one validated Claim Engine state."""

    validated = ResearchState.from_dict(
        state.to_dict(),
        known_evidence_ids=known_evidence_ids,
    )
    updated = dict(research_context)
    updated[CLAIM_ENGINE_CONTEXT_KEY] = validated.to_dict()
    return updated


def known_research_evidence_ids(run: WebLookupRun) -> tuple[str, ...]:
    """Derive allowable evidence IDs from the server-owned run snapshot."""

    snapshot = build_evidence_snapshot(
        rag={
            "research_sources": {
                "run_id": run.id,
                "provider_status": run.provider_status,
                "source_truth_version": int(
                    run.research_context.get("source_truth_version") or 0
                ),
                "selected_sources": run.selected_sources,
                "rejected_sources": run.rejected_sources,
            }
        }
    )
    return tuple(ref.id for ref in snapshot.refs)


def load_claim_engine_state(
    research_context: Mapping[str, Any],
    *,
    known_evidence_ids: Iterable[str],
) -> ClaimEngineLoadResult:
    """Load state without allowing corrupt/old data to affect legacy execution.

    Missing state means the claim engine is off. An old or invalid state becomes
    explicitly unavailable in shadow mode; the reason is a bounded code rather
    than raw parser or persisted content.
    """

    if CLAIM_ENGINE_CONTEXT_KEY not in research_context:
        return ClaimEngineLoadResult(
            status="absent",
            effective_mode="off",
            reason="claim_engine_absent",
        )

    raw = research_context.get(CLAIM_ENGINE_CONTEXT_KEY)
    if not isinstance(raw, Mapping):
        return _unavailable("invalid_claim_engine_state")
    if raw.get("schema_version") != RESEARCH_STATE_SCHEMA_VERSION:
        return _unavailable("unsupported_claim_engine_schema")

    try:
        state = ResearchState.from_dict(
            raw,
            known_evidence_ids=known_evidence_ids,
        )
    except (TypeError, ValueError):
        return _unavailable("invalid_claim_engine_state")
    return ClaimEngineLoadResult(
        status="available",
        effective_mode=state.mode,
        state=state,
    )


def _unavailable(reason: str) -> ClaimEngineLoadResult:
    return ClaimEngineLoadResult(
        status="unavailable",
        effective_mode="shadow",
        reason=reason,
    )
