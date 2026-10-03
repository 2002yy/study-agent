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
    for name in BROWSER_STEPS:
        assert "workflow_dispatch" in by_id[name]["if"]
        assert "refs/heads/main" in by_id[name]["if"]
    assert "steps.mypy.outcome" in by_id["mypy_baseline"]["env"]["MYPY_OUTCOME"]
