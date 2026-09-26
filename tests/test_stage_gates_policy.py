"""§109 Staged Regression Policy: the manifest must not rot.

These tests keep ``tests/stage_gates.json`` honest: every referenced path must
exist, the L2 stage gate must be exactly the union of the declared impact sets,
and the escalation triggers must be the frozen ones. Renaming a test file
without updating the policy fails here, which is the point.
"""

from __future__ import annotations

import json

from tools.run_stage_gate import REPO_ROOT, load_manifest, resolve

MANIFEST = REPO_ROOT / "tests" / "stage_gates.json"


def _manifest() -> dict:
    return load_manifest(MANIFEST)


def test_manifest_schema_and_ownership_are_declared() -> None:
    payload = _manifest()
    assert payload["schema_version"] == "staged-regression-policy-v1"
    assert payload["applies_from"] == "P2-A3"
    assert "AGENTS.md" in payload["policy_owner"]
    assert "PROJECT_STATUS" in payload["status_record"]


def test_all_four_layers_are_declared() -> None:
    levels = _manifest()["levels"]
    assert set(levels) == {"L0", "L1", "L2", "L3"}
    for name, level in levels.items():
        assert level["when"], name
    # L0 is the per-commit quick gate
    assert "ruff check src tests tools" in levels["L0"]["commands"]
    assert "git diff --check" in levels["L0"]["commands"]
    assert "git status --short --untracked-files=no" in levels["L0"]["commands"]
    # L3 is the full suite
    assert levels["L3"]["commands"] == ["python -m pytest tests"]


def test_every_impact_set_is_non_empty_and_resolvable() -> None:
    payload = _manifest()
    impact_sets = payload["impact_sets"]
    assert impact_sets, "at least one impact set is required"
    for name in impact_sets:
        paths = resolve(payload, impact_set=name)
        assert paths, name
        for path in paths:
            assert (REPO_ROOT / path).exists(), f"{name}: missing {path}"


def test_every_stage_gate_is_non_empty_and_resolvable() -> None:
    payload = _manifest()
    gates = payload["stage_gates"]
    assert gates, "at least one stage gate is required"
    for name in gates:
        paths = resolve(payload, stage=name)
        assert paths, name
        assert len(paths) == len(set(paths)), f"{name}: duplicate path"
        for path in paths:
            assert (REPO_ROOT / path).exists(), f"{name}: missing {path}"


def test_retrieval_stage_gate_is_the_union_of_the_retrieval_impact_sets() -> None:
    """L2 must not silently drop a layer of the retrieval stack."""

    payload = _manifest()
    expected = set()
    for name in (
        "a0_taxonomy",
        "a1_breaker",
        "a2a_lifecycle",
        "a2b_routing",
        "a2c_scheduling",
        "a2d_chain",
        "a3_browser",
        "read_adequacy",
        "runtime_read_loop",
    ):
        expected.update(payload["impact_sets"][name])
    assert set(payload["stage_gates"]["p2-a-retrieval-stack"]) == expected


def test_stage_gate_excludes_unrelated_subsystems() -> None:
    """L2 is the retrieval stack, not the whole research subsystem."""

    gate = set(_manifest()["stage_gates"]["p2-a-retrieval-stack"])
    for unrelated in (
        "tests/test_deep_research_judge.py",
        "tests/test_research_answer_streaming.py",
        "tests/test_research_quality_runner.py",
    ):
        assert unrelated not in gate, unrelated


def test_force_l3_triggers_are_frozen() -> None:
    payload = _manifest()
    assert set(payload["force_l3_triggers"]) == {
        "shared_core_data_models",
        "production_authority_cutover",
        "persistence_schema_or_cursor_compatibility",
        "broad_cross_layer_refactor",
        "focused_test_failing_for_unknown_reason",
        "uncontained_behaviour_drift",
    }
    assert set(payload["not_forcing_l3"]) == {
        "ordinary_adapter",
        "instrumentation",
        "fixtures",
        "provider_integration",
    }


def test_retro_application_matches_the_status_record() -> None:
    payload = _manifest()
    retro = payload["retro_application"]
    assert set(retro["would_not_have_required_l3"]) == {
        "P2-A2d-1",
        "P2-A2d-2",
        "P2-A2d-3",
        "P2-A3-0",
    }
    assert set(retro["did_require_l3"]) == {"P2-A2d-4", "P2-A2e"}


def test_runner_rejects_ambiguous_and_unknown_selections() -> None:
    payload = _manifest()
    for kwargs in (
        {},
        {"impact_set": "a3_browser", "stage": "p2-a-retrieval-stack"},
        {"impact_set": "does_not_exist"},
        {"stage": "does_not_exist"},
    ):
        try:
            resolve(payload, **kwargs)
        except SystemExit:
            continue
        raise AssertionError(f"expected SystemExit for {kwargs!r}")


def test_manifest_is_valid_json_on_disk() -> None:
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "staged-regression-policy-v1"
