"""Versioned failure-state contracts for the Claim Engine (frozen 1A-12A).

Two durable axes stay separate and never merge:

- ``RuntimeFailure.code`` describes what happened during the run (process
  failure truth).
- ``WebLookupRun.stop_reason`` describes why the whole run stopped (terminal
  truth).

The catalogs here are stable, versioned string contracts for **new writers**.
They are deliberately not a closed validation gate for **readers**: legacy and
future unknown values must stay readable (frozen 3A/7A/9A), so deserializers
never validate against these catalogs. Writer-side code uses the ``require_*``
guards; legacy/future readers use no catalog validation at all.
"""

from __future__ import annotations

from typing import Final, Literal, cast

RESEARCH_FAILURE_CATALOG_VERSION: Final = "research-failure-catalog-v1"
RESEARCH_STOP_REASON_CATALOG_VERSION: Final = "research-stop-reason-catalog-v1"

# P1 canonical one-level failure codes (frozen 9A).  Provider/Python/HTTP
# specifics must never become one-level codes; they belong in
# provider_code / exception_type / detail (frozen 3A).  P2-only reader causes
# are intentionally absent until a detector can reliably observe them
# (frozen 6A).
ResearchFailureCode = Literal[
    "policy_blocked",
    "claim_planning_failed",
    "search_failed",
    "assessment_failed",
    "read_failed",
    "extraction_failed",
    "model_attempts_exhausted",
    "runtime_internal_failed",
]

# Mirrors ResearchFailureCode; the runtime consistency guard keeps the two in
# lockstep (frozen 2A: stable strings, not a closed enum).
RESEARCH_FAILURE_CODES: Final[frozenset[str]] = frozenset(
    {
        "policy_blocked",
        "claim_planning_failed",
        "search_failed",
        "assessment_failed",
        "read_failed",
        "extraction_failed",
        "model_attempts_exhausted",
        "runtime_internal_failed",
    }
)

# Stop reasons registered verbatim from current production emitters (frozen
# 5A: Batch A never renames an existing value).  The active runtime reasons
# are produced by ResearchStopGate and the executor unavailable paths; the
# legacy service/repository/migration literals are kept so the catalog covers
# every durable stop_reason the product can already write today.
ResearchStopReason = Literal[
    "evidence_gate_pass",
    "evidence_budget_exhausted",
    "evidence_gap_open",
    "evidence_saturated",
    "wave_limit_exhausted",
    "claim_planning_blocked_by_policy",
    "claim_plan_unavailable",
    "active_runtime_unavailable",
    "user_cancelled",
    "providers_failed",
    "providers_returned_no_results",
    "direct_results_found",
    "read_backed_tool_evidence_found",
    "search_candidates_only",
    "no_tool_calls",
    "insufficient_valid_sources",
    "sources_read",
    "sources_partially_read",
    "source_reading_failed",
    "chat_tool_loop_failed",
    "research_stage_failed",
    "legacy_run_interrupted",
]

RESEARCH_STOP_REASONS: Final[frozenset[str]] = frozenset(
    {
        "evidence_gate_pass",
        "evidence_budget_exhausted",
        "evidence_gap_open",
        "evidence_saturated",
        "wave_limit_exhausted",
        "claim_planning_blocked_by_policy",
        "claim_plan_unavailable",
        "active_runtime_unavailable",
        "user_cancelled",
        "providers_failed",
        "providers_returned_no_results",
        "direct_results_found",
        "read_backed_tool_evidence_found",
        "search_candidates_only",
        "no_tool_calls",
        "insufficient_valid_sources",
        "sources_read",
        "sources_partially_read",
        "source_reading_failed",
        "chat_tool_loop_failed",
        "research_stage_failed",
        "legacy_run_interrupted",
    }
)


def require_research_failure_code(value: str) -> str:
    if not isinstance(value, str) or value not in RESEARCH_FAILURE_CODES:
        raise ValueError(f"unknown research failure code: {value!r}")
    return value


def is_research_stop_reason(value: str) -> bool:
    return value in RESEARCH_STOP_REASONS


def require_research_stop_reason(value: str) -> ResearchStopReason:
    """Validate a new writer value without constraining legacy/future readers."""

    if not isinstance(value, str) or value not in RESEARCH_STOP_REASONS:
        raise ValueError(f"unknown research stop reason: {value!r}")
    return cast(ResearchStopReason, value)


__all__ = [
    "RESEARCH_FAILURE_CATALOG_VERSION",
    "RESEARCH_STOP_REASON_CATALOG_VERSION",
    "RESEARCH_FAILURE_CODES",
    "RESEARCH_STOP_REASONS",
    "ResearchFailureCode",
    "ResearchStopReason",
    "is_research_stop_reason",
    "require_research_failure_code",
    "require_research_stop_reason",
]
