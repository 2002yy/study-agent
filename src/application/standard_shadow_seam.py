"""Compatibility shim for the Standard B-Search shadow.

The implementation is now the generic, phase-aware ``research_shadow_seam``. This
module keeps the M4-A public surface (names and behaviour) so existing imports and
tests keep working unchanged.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from src.application.research_shadow_seam import (
    BSEARCH_SHADOW_BUDGET_SECONDS,
    EVIDENCE_AUTHORITY,
    PHASE_FLAGS,
    SEAM_VERSION,
    SHADOW_EVIDENCE_COMPLETION,
    ShadowInputHashes,
    ShadowResult,
    build_input_hashes,
    canonical_hash,
    grants_evidence_authority,
    observe_shadow,
    shadow_enabled,
    summarize_trace,
)
from src.application.shadow_isolation import BestEffortTelemetry

PHASE = "standard"
SHADOW_FLAG = PHASE_FLAGS[PHASE]

#: Backwards-compatible aliases (the M4-A names).
StandardInputHashes = ShadowInputHashes
StandardShadowResult = ShadowResult
build_standard_input_hashes = build_input_hashes

__all__ = [
    "BSEARCH_SHADOW_BUDGET_SECONDS",
    "EVIDENCE_AUTHORITY",
    "PHASE",
    "PHASE_FLAGS",
    "SEAM_VERSION",
    "SHADOW_EVIDENCE_COMPLETION",
    "SHADOW_FLAG",
    "StandardInputHashes",
    "StandardShadowResult",
    "build_standard_input_hashes",
    "canonical_hash",
    "grants_evidence_authority",
    "observe_shadow",
    "observe_shadow_for_standard",
    "shadow_enabled",
    "standard_shadow_enabled",
    "summarize_trace",
]


def standard_shadow_enabled() -> bool:
    """Default off; unset or unknown keeps the production behaviour unchanged."""
    return shadow_enabled(PHASE)


def observe_shadow_for_standard(
    *,
    query: str,
    handoff: Mapping[str, Any] | None = None,
    telemetry: BestEffortTelemetry | None = None,
    runner: Callable[[str, float], dict[str, Any]] | None = None,
) -> ShadowResult:
    """Standard-phase wrapper over the generic seam. Returns immediately; never raises."""
    return observe_shadow(
        phase=PHASE, query=query, handoff=handoff, telemetry=telemetry, runner=runner
    )
