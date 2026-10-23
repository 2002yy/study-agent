"""The CI workflow must take its routing from ci_scope, never re-derive it from the event.

CI-2 made ``tools/ci_scope.py`` the single source of truth and said so in the workflow. The
browser steps then re-derived "main push means browser" anyway, so a backend merge on main
launched Playwright without frontend dependencies (exit 127) and enforcement demanded browser
gates the classifier never asked for. These tests pin the single-authority rule.
"""

from __future__ import annotations

import io
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"

# YAML 1.1 parses the bare key "on" as the boolean True.
EVENT_TYPE_ROUTING = "github.event_name"


def _steps() -> list[dict]:
    data = yaml.safe_load(io.open(WORKFLOW, encoding="utf-8"))
    return data["jobs"]["test"]["steps"]


def _by_id(step_id: str) -> dict:
    for step in _steps():
        if step.get("id") == step_id:
            return step
    raise AssertionError(f"step {step_id!r} not found")


def test_enforcement_reads_browser_requirement_from_the_classifier():
    enforcer = _steps()[-1]
    assert enforcer["name"] == "Enforce required CI outcomes"
    assert enforcer["env"]["CI_BROWSER_REQUIRED"] == (
        "${{ steps.ci_scope.outputs.frontend_e2e_required }}"
    )
    assert enforcer["env"]["CI_FRONTEND_REQUIRED"] == (
        "${{ steps.ci_scope.outputs.frontend_required }}"
    )


def test_no_step_routes_on_the_event_type():
    # No step may branch on the event type; the classifier owns that decision.
    for step in _steps():
        condition = str(step.get("if") or "")
        assert EVENT_TYPE_ROUTING not in condition, step.get("name") or step.get("id")


def test_browser_steps_follow_the_classifier():
    for step_id in ("playwright_install", "browser_e2e", "real_stack_browser_e2e"):
        condition = str(_by_id(step_id).get("if") or "")
        assert "steps.ci_scope.outputs.frontend_e2e_required == 'true'" in condition, step_id


def test_browser_gates_depend_on_installed_node_dependencies():
    # browser_required=true must never run against a missing node_modules.
    assert "steps.node_deps.outcome == 'success'" in _by_id("playwright_install")["if"]
    for step_id in ("browser_e2e", "real_stack_browser_e2e"):
        assert "steps.playwright_install.outcome == 'success'" in _by_id(step_id)["if"]


def test_node_toolchain_covers_frontend_or_browser_without_merging_them():
    condition = str(_by_id("node_deps")["if"])
    assert "frontend_required == 'true'" in condition
    assert "frontend_e2e_required == 'true'" in condition
    # The two tiers stay distinct: the toolchain condition is an OR, not a merge of outputs.
    setup_node = next(
        step for step in _steps() if str(step.get("uses") or "").startswith("actions/setup-node")
    )
    assert "frontend_required == 'true'" in setup_node["if"]
    assert "frontend_e2e_required == 'true'" in setup_node["if"]


def test_frontend_gate_does_not_reinstall_dependencies():
    # npm ci belongs to node_deps, so a frontend+browser run installs once.
    frontend_run = str(_by_id("frontend")["run"])
    assert "npm ci" not in frontend_run
    assert "npm ci" in str(_by_id("node_deps")["run"])


def test_main_push_uses_a_proven_batch_range():
    # G1-B: one merge push diffs against its parent, so the surviving run must classify the
    # batch range instead of its own slice.
    classify_step = _by_id("ci_scope")
    run = str(classify_step["run"])
    assert "tools/ci_batch_range.py" in run
    assert 'batch_mode' in run
    # An unprovable batch widens; it must never fall through to the single-slice range.
    assert "No provable batch range" in run


def test_batch_lookup_failure_widens_instead_of_degrading():
    # A denied lookup is not the same as "there is no earlier run". Collapsing the two is
    # how the batch silently returns to the single-slice range.
    run = str(_by_id("ci_scope")["run"])
    assert "Batch baseline lookup failed" in run
    assert "batch_lookup" in run


def test_workflow_may_read_actions_to_resolve_the_batch_start():
    data = yaml.safe_load(io.open(WORKFLOW, encoding="utf-8"))
    assert data["permissions"].get("actions") == "read"
