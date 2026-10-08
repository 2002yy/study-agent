from pathlib import Path

import pytest
import yaml

from tools.check_ci_outcomes import BROWSER_STEPS, REQUIRED_STEPS, failed_steps, main


def outcomes():
    return {name: {"outcome": "success"} for name in REQUIRED_STEPS}


def test_pr_skips_browser_but_main_requires_it():
    steps = outcomes()
    assert failed_steps(steps, browser_required=False) == []
    assert failed_steps(steps, browser_required=True) == list(BROWSER_STEPS)
    steps.update({name: {"outcome": "success"} for name in BROWSER_STEPS})
    assert failed_steps(steps, browser_required=True) == []


@pytest.mark.parametrize("outcome", ["failure", "cancelled", "skipped", None])
@pytest.mark.parametrize("step", REQUIRED_STEPS)
def test_continue_on_error_cannot_hide_failure_or_missing_check(step, outcome):
    steps = outcomes()
    steps[step] = {"outcome": outcome, "conclusion": "success"}
    assert failed_steps(steps, browser_required=False) == [step]


def test_optional_browser_failure_is_still_failure():
    steps = outcomes()
    steps["browser_e2e"] = {"outcome": "failure"}
    assert failed_steps(steps, browser_required=False) == ["browser_e2e"]


@pytest.mark.parametrize("payload", ["null", "[]", "{", '{"pytest": null}'])
def test_malformed_outcomes_fail_closed(payload, monkeypatch):
    monkeypatch.setenv("CI_STEP_RESULTS", payload)
    monkeypatch.setenv("CI_BROWSER_REQUIRED", "true")
    assert main() == 1


def test_workflow_preserves_gates_and_uploads_diagnostics_once():
    workflow = yaml.safe_load(Path(".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["test"]["steps"]
    by_id = {step["id"]: step for step in steps if "id" in step}
    assert set(REQUIRED_STEPS + BROWSER_STEPS) <= set(by_id)
    uploads = [step for step in steps if step.get("uses", "").startswith("actions/upload-artifact")]
    assert len(uploads) == 1 and uploads[0]["if"] == "always()"
    assert steps[-1]["if"] == "always()"
    assert "check_ci_outcomes.py" in steps[-1]["run"]
    # Browser gates follow the classifier, not the event type (CI-2 push-routing repair).
    for name in BROWSER_STEPS:
        assert "steps.ci_scope.outputs.browser_required == 'true'" in by_id[name]["if"]
        assert "workflow_dispatch" not in by_id[name]["if"]
        assert "refs/heads/main" not in by_id[name]["if"]
    assert "steps.node_deps.outcome == 'success'" in by_id["playwright_install"]["if"]
    for name in ("browser_e2e", "real_stack_browser_e2e"):
        assert "steps.playwright_install.outcome == 'success'" in by_id[name]["if"]
    assert "steps.mypy.outcome" in by_id["mypy_baseline"]["env"]["MYPY_OUTCOME"]


# --- fast tier: a bounded impact set stands in for the full suite ---------------


def test_fast_tier_accepts_impact_set_instead_of_pytest():
    steps = outcomes()
    steps["pytest"] = {"outcome": "skipped"}
    steps["pytest_impact"] = {"outcome": "success"}
    assert failed_steps(steps, browser_required=False, frontend_required=False) == []


def test_fast_tier_still_fails_when_neither_test_step_succeeds():
    steps = outcomes()
    steps["pytest"] = {"outcome": "skipped"}
    steps["pytest_impact"] = {"outcome": "failure"}
    assert "pytest" in failed_steps(steps, browser_required=False, frontend_required=False)


def test_skipped_frontend_is_allowed_when_not_required():
    steps = outcomes()
    steps["frontend"] = {"outcome": "skipped"}
    assert failed_steps(steps, browser_required=False, frontend_required=False) == []


def test_skipped_frontend_still_fails_when_required():
    steps = outcomes()
    steps["frontend"] = {"outcome": "skipped"}
    assert "frontend" in failed_steps(steps, browser_required=False, frontend_required=True)


def test_failed_frontend_fails_even_when_not_required():
    steps = outcomes()
    steps["frontend"] = {"outcome": "failure"}
    assert "frontend" in failed_steps(steps, browser_required=False, frontend_required=False)


def test_l3_workflow_is_explicitly_triggered_only():
    workflow = yaml.safe_load(Path(".github/workflows/ci-l3.yml").read_text(encoding="utf-8"))
    # YAML 1.1 parses the key "on" as the boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert "pull_request" not in triggers or triggers["pull_request"] == {"types": ["labeled"]}
    assert "workflow_dispatch" in triggers
    job = workflow["jobs"]["l3"]
    run_text = " ".join(str(step.get("run", "")) for step in job["steps"])
    assert "l3_preflight.py" in run_text
