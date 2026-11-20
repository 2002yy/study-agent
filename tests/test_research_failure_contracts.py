"""Catalog characterization for the versioned failure-state contracts.

Locks the frozen Batch-A decisions: canonical one-level failure codes,
verbatim registration of current production stop reasons, lower-snake-case
bounded strings, no dynamic exception names, no unobservable P2 reader
reasons, and a closed writer-side validator with a forward-compatible reader.
"""

from __future__ import annotations

import pytest

from src.web.research.failure_contracts import (
    RESEARCH_FAILURE_CATALOG_VERSION,
    RESEARCH_FAILURE_CODES,
    RESEARCH_STOP_REASON_CATALOG_VERSION,
    RESEARCH_STOP_REASONS,
    require_research_failure_code,
)

# Current active-runtime emitters (frozen 5A: registered verbatim, never
# renamed).  ResearchStopGate produces the first five; the executor produces
# the remaining three through its unavailable terminal path.
ACTIVE_RUNTIME_STOP_REASONS = {
    "evidence_gate_pass",
    "evidence_budget_exhausted",
    "evidence_gap_open",
    "evidence_saturated",
    "wave_limit_exhausted",
    "claim_planning_blocked_by_policy",
    "claim_plan_unavailable",
    "active_runtime_unavailable",
}

# Durable compatibility writers outside the active runtime must remain in the
# catalog too.  Migration 15 writes this value into web_lookup_runs when an old
# running row is recovered during schema upgrade.
LEGACY_DURABLE_STOP_REASONS = {"legacy_run_interrupted"}

P1_CANONICAL_FAILURE_CODES = {
    "policy_blocked",
    "claim_planning_failed",
    "search_failed",
    "assessment_failed",
    "read_failed",
    "extraction_failed",
    "model_attempts_exhausted",
    "runtime_internal_failed",
}


def test_failure_catalog_v1_is_exact_and_unique() -> None:
    assert RESEARCH_FAILURE_CATALOG_VERSION == "research-failure-catalog-v1"
    assert RESEARCH_FAILURE_CODES == P1_CANONICAL_FAILURE_CODES
    assert len(RESEARCH_FAILURE_CODES) == len(P1_CANONICAL_FAILURE_CODES)


def test_literal_and_frozenset_catalogs_stay_in_lockstep() -> None:
    from src.web.research.failure_contracts import (
        ResearchFailureCode,
        ResearchStopReason,
    )

    # Runtime guard: mypy cannot see Literal.__args__, so the explicit sets
    # must agree with the literals or the mismatch fails here immediately.
    assert frozenset(ResearchFailureCode.__args__) == RESEARCH_FAILURE_CODES
    assert frozenset(ResearchStopReason.__args__) == RESEARCH_STOP_REASONS


def test_stop_reason_catalog_contains_current_production_reasons() -> None:
    assert RESEARCH_STOP_REASON_CATALOG_VERSION == "research-stop-reason-catalog-v1"
    assert ACTIVE_RUNTIME_STOP_REASONS <= RESEARCH_STOP_REASONS
    assert LEGACY_DURABLE_STOP_REASONS <= RESEARCH_STOP_REASONS


def test_failure_codes_are_lower_snake_case() -> None:
    for code in RESEARCH_FAILURE_CODES:
        assert code == code.strip()
        assert "_" in code, code
        assert code.replace("_", "").isalnum(), code
        assert code.islower(), code


def test_failure_codes_are_bounded_and_stable_strings() -> None:
    for code in RESEARCH_FAILURE_CODES:
        assert isinstance(code, str)
        assert 0 < len(code) < 64, code
        assert code == code.lower()


def test_dynamic_exception_names_are_not_catalog_codes() -> None:
    for leaked in ("TimeoutError", "JSONDecodeError", "ConnectionError"):
        assert leaked not in RESEARCH_FAILURE_CODES
    assert "type(exc).__name__" not in RESEARCH_FAILURE_CODES


def test_p1_catalog_does_not_claim_unobservable_p2_reader_failures() -> None:
    for p2_only in ("read_login_required", "read_js_required", "read_paywall"):
        assert p2_only not in RESEARCH_FAILURE_CODES


def test_require_failure_code_accepts_catalog_value() -> None:
    assert require_research_failure_code("read_failed") == "read_failed"


def test_require_failure_code_rejects_unknown_new_writer_value() -> None:
    for value in ("TimeoutError", "read_login_required", "provider_timeout", ""):
        with pytest.raises(ValueError):
            require_research_failure_code(value)
