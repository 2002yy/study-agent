"""§108 P2-A3-0: frozen browser-backend bakeoff contract.

These tests pin the *contract*: the six fixture classes, the capability demand,
the routing that must precede a browser call, the static-control guard, the
shared budget, the provenance requirement, and the pre-registered winner
criteria. They also pin what A3-0 must **not** do: enter production.

Nothing here installs, imports or exercises a browser backend.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from src.web.research.browser_bakeoff import (
    ALLOWED_ADAPTER_SURFACE,
    BAKEOFF_CLASSES,
    BAKEOFF_DIMENSIONS,
    BAKEOFF_UNIFIED_BUDGET,
    BROWSER_CHAIN_MAX_LENGTH,
    BrowserBakeoffContractError,
    CANDIDATE_BACKENDS,
    CLASS_ANTI_BOT,
    CLASS_CAPABILITY_DEMAND,
    CLASS_DOCUMENT_HEAVY,
    CLASS_EXPECTED_ROUTING,
    CLASS_EXPECTS_BROWSER_CALL,
    CLASS_JS_SHELL,
    CLASS_SESSION_REQUIRED,
    CLASS_SPA_DELAYED_RENDER,
    CLASS_STATIC_CONTROL,
    CLASS_SUCCESS_DEFINITION,
    FORBIDDEN_CORE_CHANGES,
    FROZEN_CAPABILITIES,
    PRODUCTION_CHAIN_AT_A3_0,
    PROVENANCE_REQUIREMENTS,
    REQUIRED_DIMENSIONS,
    ROUTING_ACTIONS,
    SCHEMA_VERSION,
    WINNER_CRITERIA,
    dimension_keys,
    intended_browser_chain,
    load_browser_bakeoff_manifest,
    validate_browser_bakeoff_manifest,
)
from src.web.research.read_escalation import (
    EFFECTIVE_TIMEOUT_FLOOR_SECONDS,
    HTTP_MIN_HARD_SECONDS_DEFAULT,
    HTTP_RUN_ENVELOPE_DEFAULT,
)
from src.web.research.wigolo_backend import WIGOLO_FETCH_MAX_CHARS

MANIFEST = (
    Path("tests/fixtures/research_quality/browser_bakeoff_manifest.json")
)

#: The A2 production modules A3-0 must leave untouched.
PRODUCTION_MODULES = (
    "src/application/active_research_runtime.py",
    "src/web/research/active_adapter.py",
    "src/web/research/chain_executor.py",
    "src/web/research/progressive_routing.py",
    "src/web/research/candidate_resolution.py",
    "src/web/research/wigolo_http_executor.py",
)


def _manifest() -> dict[str, Any]:
    return load_browser_bakeoff_manifest(MANIFEST)


# ---------------------------------------------------------------------------
# The manifest satisfies the contract
# ---------------------------------------------------------------------------


def test_manifest_validates_against_the_frozen_contract() -> None:
    payload = _manifest()
    assert payload["schema_version"] == SCHEMA_VERSION
    # the loader is fail-closed; a second explicit pass proves idempotence
    validate_browser_bakeoff_manifest(payload)


def test_manifest_declares_exactly_the_six_frozen_classes_in_order() -> None:
    payload = _manifest()
    assert tuple(row["class"] for row in payload["classes"]) == BAKEOFF_CLASSES
    assert BAKEOFF_CLASSES == (
        CLASS_STATIC_CONTROL,
        CLASS_JS_SHELL,
        CLASS_SPA_DELAYED_RENDER,
        CLASS_ANTI_BOT,
        CLASS_SESSION_REQUIRED,
        CLASS_DOCUMENT_HEAVY,
    )


def test_static_control_never_starts_a_browser() -> None:
    """Proving rescue is not enough; the backend must also stay out of the way."""

    payload = _manifest()
    control = next(
        row for row in payload["classes"] if row["class"] == CLASS_STATIC_CONTROL
    )
    assert control["expect_browser_call"] is False
    assert control["capability_demand"] == []
    assert control["expected_routing"] == "resolve"
    assert CLASS_EXPECTS_BROWSER_CALL[CLASS_STATIC_CONTROL] is False


def test_every_rescue_class_demands_a_frozen_capability() -> None:
    payload = _manifest()
    for row in payload["classes"]:
        name = row["class"]
        demand = frozenset(row["capability_demand"])
        assert demand <= FROZEN_CAPABILITIES, name
        assert demand == CLASS_CAPABILITY_DEMAND[name], name
        if name == CLASS_STATIC_CONTROL:
            continue
        assert demand, f"{name} must demand a capability"
        assert row["expect_browser_call"] is True, name
        assert row["expected_routing"] == "try_backend", name


def test_expected_routing_uses_the_frozen_action_vocabulary() -> None:
    payload = _manifest()
    for row in payload["classes"]:
        assert row["expected_routing"] in ROUTING_ACTIONS, row["class"]
        assert row["expected_routing"] == CLASS_EXPECTED_ROUTING[row["class"]]


def test_success_definitions_are_machine_checkable() -> None:
    payload = _manifest()
    for row in payload["classes"]:
        definition = row["success_definition"]
        assert definition == CLASS_SUCCESS_DEFINITION[row["class"]]
        assert definition["browser_invocation"] in {"forbidden", "required_once"}
        assert definition["canonical_state_required"] is True
        assert isinstance(definition["usable_content_required"], bool)
    # only the session class may accept an honest canonical failure
    permissive = {
        row["class"]
        for row in payload["classes"]
        if row["success_definition"]["usable_content_required"] is False
    }
    assert permissive == {CLASS_SESSION_REQUIRED}


# ---------------------------------------------------------------------------
# One shared budget, reusing the frozen A2 numbers
# ---------------------------------------------------------------------------


def test_budget_is_shared_and_reuses_the_frozen_a2_constants() -> None:
    payload = _manifest()
    budget = payload["budget"]
    assert budget == BAKEOFF_UNIFIED_BUDGET
    # Reuse, not restatement: a bakeoff can never hand a candidate a larger
    # budget than production already allows.
    assert budget["min_hard_seconds_left"] == HTTP_MIN_HARD_SECONDS_DEFAULT == 3.0
    assert budget["run_envelope_seconds"] == HTTP_RUN_ENVELOPE_DEFAULT == 3.0
    assert (
        budget["effective_timeout_floor_seconds"]
        == EFFECTIVE_TIMEOUT_FLOOR_SECONDS
        == 1.0
    )
    assert budget["max_chars"] == WIGOLO_FETCH_MAX_CHARS == 20_000


def test_budget_is_identical_for_both_candidates() -> None:
    """The comparison is only fair if neither side gets its own numbers."""

    assert tuple(CANDIDATE_BACKENDS) == ("wigolo_browser", "crawl4ai")
    # a single shared mapping, not a per-candidate one
    assert isinstance(BAKEOFF_UNIFIED_BUDGET, dict)
    assert "budget" not in BAKEOFF_UNIFIED_BUDGET


# ---------------------------------------------------------------------------
# Provenance and dimensions
# ---------------------------------------------------------------------------


def test_provenance_requirements_cover_the_a2_artifacts() -> None:
    payload = _manifest()
    assert tuple(payload["provenance_requirements"]) == PROVENANCE_REQUIREMENTS
    assert set(PROVENANCE_REQUIREMENTS) == {
        "runtime_read_outcome",
        "read_timing",
        "read_chain",
        "source_retrieval_attempts",
        "final_backend",
        "failure_attempt_id",
    }


def test_dimensions_cover_the_frozen_comparison_axes() -> None:
    keys = dimension_keys()
    assert len(keys) == len(set(keys)), "dimension keys must be unique"
    required_axes = {
        "js_render_success",
        "shell_rescue",
        "anti_bot_recovery",
        "session_capability",
        "document_support",
        "latency_warm_ms",
        "cold_start_ms",
        "resident_memory_delta_mb",
        "daemon_restarts",
        "failure_transparency",
        "provenance_completeness",
        "budget_boundedness",
        "static_control_silence",
        "integration_complexity",
        "maintenance_burden",
    }
    assert required_axes <= set(keys)
    for dimension in BAKEOFF_DIMENSIONS:
        assert dimension["direction"] in {"higher_better", "lower_better", "required"}


def test_required_dimensions_are_a_subset_of_the_measured_dimensions() -> None:
    assert set(REQUIRED_DIMENSIONS) <= set(dimension_keys())
    assert set(REQUIRED_DIMENSIONS) == set(WINNER_CRITERIA["required_dimensions"])
    # the guard is required, not merely measured
    assert "static_control_silence" in REQUIRED_DIMENSIONS


# ---------------------------------------------------------------------------
# Winner criteria and boundaries
# ---------------------------------------------------------------------------


def test_winner_criteria_are_preregistered() -> None:
    assert set(WINNER_CRITERIA["decision_rules"]) == {
        "wigolo_browser_wins",
        "crawl4ai_wins",
        "complementary",
    }
    assert WINNER_CRITERIA["default_goal"] == "one primary BrowserBackend"
    assert WINNER_CRITERIA["tie_break"]
    disqualifiers = set(WINNER_CRITERIA["disqualifiers"])
    assert {
        "browser_started_on_static_control",
        "budget_exceeded",
        "missing_canonical_retrieval_state",
        "provenance_incomplete",
        "requires_core_semantics_change",
        "chain_longer_than_max",
    } <= disqualifiers


def test_intended_browser_chain_stays_within_the_bound() -> None:
    for winner in CANDIDATE_BACKENDS:
        chain = intended_browser_chain(winner)
        assert chain == (*PRODUCTION_CHAIN_AT_A3_0, winner)
        assert len(chain) <= BROWSER_CHAIN_MAX_LENGTH == 3
        assert len(set(chain)) == len(chain)
        assert chain[-1] == winner, "the browser is always the last step"
    with pytest.raises(BrowserBakeoffContractError):
        intended_browser_chain("not_a_backend")


def test_forbidden_core_semantics_are_named() -> None:
    """A browser backend may register a capability and implement an executor."""

    joined = " ".join(FORBIDDEN_CORE_CHANGES)
    for symbol in (
        "candidate_resolution",
        "progressive_routing.route",
        "progressive_routing.schedulable_now",
        "chain_executor.run_chain",
        "failure_taxonomy.RETRIEVAL_STATES",
    ):
        assert symbol in joined, symbol
    assert set(ALLOWED_ADAPTER_SURFACE) == {
        "register_BackendCapability",
        "implement_BackendExecutor",
        "join_existing_chain",
    }


# ---------------------------------------------------------------------------
# A3-0 does not enter production
# ---------------------------------------------------------------------------


def test_bakeoff_harness_is_production_inert() -> None:
    # A3-0's blanket "no browser tier in production" was superseded by §143-SI,
    # which deliberately added the qualified, default-inert Crawl4AI specialist
    # seam (docs/PROJECT_STATUS.md §143.170-§143.172). The invariant that still
    # holds is that the *bakeoff harness* never enters production.
    for module in PRODUCTION_MODULES:
        text = Path(module).read_text(encoding="utf-8")
        assert "browser_bakeoff" not in text, f"{module} must not import the harness"
        assert "run_browser_bakeoff" not in text, f"{module} must not run the bakeoff"
        assert (
            "wigolo_browser_executor" not in text
        ), f"{module} must not import the browser executor"


def test_no_crawl4ai_backend_is_registered() -> None:
    from src.web.research.progressive_routing import capability_registry

    names = set(capability_registry())
    assert names == {"native_http", "wigolo_http", "wigolo_browser"}
    assert "crawl4ai" not in names


def test_production_chain_is_unchanged_at_a3_0() -> None:
    """The default reader chain is still the two-backend P0 chain.

    §143-SI added an *explicit-hint-only* specialist seam; it must never become
    part of the default chain or the capability registry.
    """

    assert PRODUCTION_CHAIN_AT_A3_0 == ("native_http", "wigolo_http")
    runtime = Path("src/application/active_research_runtime.py").read_text(
        encoding="utf-8"
    )
    match = re.search(
        r"ACTIVE_READER_CHAIN(?:\s*:\s*[^=]+)?\s*=\s*\(([^)]*)\)", runtime
    )
    assert match is not None, "the production reader chain must be declared"
    assert match.group(1).strip() == "NATIVE_HTTP_BACKEND, WIGOLO_HTTP_BACKEND"


# ---------------------------------------------------------------------------
# Negative controls: the validator is fail-closed
# ---------------------------------------------------------------------------


def _tampered(mutate: Any) -> dict[str, Any]:
    payload = copy.deepcopy(json.loads(MANIFEST.read_text(encoding="utf-8")))
    mutate(payload)
    return payload


def _set_class(payload: dict[str, Any], name: str) -> dict[str, Any]:
    return next(row for row in payload["classes"] if row["class"] == name)


def test_validator_rejects_a_browser_call_on_the_static_control() -> None:
    def mutate(payload: dict[str, Any]) -> None:
        _set_class(payload, CLASS_STATIC_CONTROL)["expect_browser_call"] = True

    with pytest.raises(BrowserBakeoffContractError):
        validate_browser_bakeoff_manifest(_tampered(mutate))


def test_validator_rejects_an_inflated_budget() -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["budget"]["run_envelope_seconds"] = 30.0

    with pytest.raises(BrowserBakeoffContractError):
        validate_browser_bakeoff_manifest(_tampered(mutate))


def test_validator_rejects_a_capability_outside_the_frozen_vocabulary() -> None:
    def mutate(payload: dict[str, Any]) -> None:
        _set_class(payload, CLASS_JS_SHELL)["capability_demand"] = ["headless_chrome"]

    with pytest.raises(BrowserBakeoffContractError):
        validate_browser_bakeoff_manifest(_tampered(mutate))


def test_validator_rejects_a_missing_class() -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["classes"] = [
            row for row in payload["classes"] if row["class"] != CLASS_DOCUMENT_HEAVY
        ]

    with pytest.raises(BrowserBakeoffContractError):
        validate_browser_bakeoff_manifest(_tampered(mutate))


def test_validator_rejects_an_unknown_class() -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["classes"].append(dict(payload["classes"][0], **{"class": "webgl"}))

    with pytest.raises(BrowserBakeoffContractError):
        validate_browser_bakeoff_manifest(_tampered(mutate))


def test_validator_rejects_a_duplicate_target_url() -> None:
    def mutate(payload: dict[str, Any]) -> None:
        control = _set_class(payload, CLASS_STATIC_CONTROL)
        control["targets"].append(dict(control["targets"][0]))

    with pytest.raises(BrowserBakeoffContractError):
        validate_browser_bakeoff_manifest(_tampered(mutate))


def test_validator_rejects_a_non_http_target() -> None:
    def mutate(payload: dict[str, Any]) -> None:
        control = _set_class(payload, CLASS_STATIC_CONTROL)
        control["targets"][0]["url"] = "file:///etc/passwd"

    with pytest.raises(BrowserBakeoffContractError):
        validate_browser_bakeoff_manifest(_tampered(mutate))


def test_validator_rejects_a_wrong_schema_version() -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["schema_version"] = "browser-bakeoff-manifest-v2"

    with pytest.raises(BrowserBakeoffContractError):
        validate_browser_bakeoff_manifest(_tampered(mutate))


def test_validator_rejects_a_single_candidate() -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["candidate_backends"] = ["wigolo_browser"]

    with pytest.raises(BrowserBakeoffContractError):
        validate_browser_bakeoff_manifest(_tampered(mutate))


def test_validator_rejects_a_dropped_provenance_requirement() -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["provenance_requirements"] = [
            item
            for item in payload["provenance_requirements"]
            if item != "failure_attempt_id"
        ]

    with pytest.raises(BrowserBakeoffContractError):
        validate_browser_bakeoff_manifest(_tampered(mutate))


def test_validator_rejects_an_empty_class_row() -> None:
    with pytest.raises(BrowserBakeoffContractError):
        validate_browser_bakeoff_manifest({"schema_version": SCHEMA_VERSION})
