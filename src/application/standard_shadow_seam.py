"""Compatibility shim for the Standard B-Search shadow.

The implementation is now the generic, phase-aware ``research_shadow_seam``. This
module keeps the M4-A public surface (names and behaviour) so existing imports and
tests keep working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from src.application.research_shadow_seam import (
    BSEARCH_SHADOW_BUDGET_SECONDS,
    EVIDENCE_AUTHORITY,
    PHASE_FLAGS,
    SEAM_VERSION,
    SHADOW_EVIDENCE_COMPLETION,
    ShadowInputHashes,
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

#: M4-A name for the (structurally identical) decision-input hashes.
StandardInputHashes = ShadowInputHashes
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


@dataclass(frozen=True)
class StandardShadowResult:
    """The M4-A public result: unchanged fields, no ``phase``.

    Deliberately NOT the generic ``ShadowResult``: adding a constructor field would
    silently change the merged M4-A contract for existing callers.
    """

    enabled: bool
    submitted: bool
    decision_inputs: StandardInputHashes

    @property
    def telemetry_only(self) -> bool:
        """The seam's output is consumed by telemetry and nothing else."""
        return True


def standard_shadow_enabled() -> bool:
    """Default off; unset or unknown keeps the production behaviour unchanged."""
    return shadow_enabled(PHASE)


def observe_shadow_for_standard(
    *,
    query: str,
    handoff: Mapping[str, Any] | None = None,
    telemetry: BestEffortTelemetry | None = None,
    runner: Callable[[str, float], dict[str, Any]] | None = None,
) -> StandardShadowResult:
    """Standard-phase wrapper over the generic seam. Returns immediately; never raises.

    The Standard telemetry record keeps its M4-A schema (see ``PHASE_SCHEMA``).
    """
    result = observe_shadow(
        phase=PHASE, query=query, handoff=handoff, telemetry=telemetry, runner=runner
    )
    return StandardShadowResult(result.enabled, result.submitted, result.decision_inputs)
