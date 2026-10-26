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
    jobs = workflow["jobs"]

    backend_ids = {step["id"]: step for step in jobs["backend"]["steps"] if "id" in step}
    browser_ids = {step["id"]: step for step in jobs["browser"]["steps"] if "id" in step}
    # The browser suites live in their own job now; the step ids are unchanged.
    # product_policy moved with the classifier, frontend with its own job.
    assert set(REQUIRED_STEPS) - {"frontend", "product_policy"} <= set(backend_ids)
    assert "product_policy" in {
        step["id"] for step in jobs["classify"]["steps"] if "id" in step
    }
    assert set(BROWSER_STEPS) - {"playwright_install"} <= set(browser_ids)

    # One artifact per job, so a failed backend upload cannot overwrite the browser
    # trace (and vice versa), and every upload runs even on failure.
    uploads = [
        step
        for job in jobs.values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact")
    ]
    assert len(uploads) == 3
    assert all(step["if"] == "always()" for step in uploads)

    for job_name in ("backend", "frontend", "browser"):
        final = jobs[job_name]["steps"][-1]
        assert final["if"] == "always()"
        assert "check_ci_outcomes.py" in final["run"]

    assert "steps.mypy.outcome" in backend_ids["mypy_baseline"]["env"]["MYPY_OUTCOME"]
    # Browser routing is a job-level condition on the classifier, never the event type.
    condition = str(jobs["browser"]["if"])
    assert "needs.classify.outputs.frontend_e2e_required == 'true'" in condition
    assert "workflow_dispatch" not in condition
    assert "refs/heads/main" not in condition


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
