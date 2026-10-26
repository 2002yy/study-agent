"""The CI workflow must take its routing from ci_scope, never re-derive it from the event.

CI-2 made ``tools/ci_scope.py`` the single source of truth and said so in the workflow. The
browser steps then re-derived "main push means browser" anyway, so a backend merge on main
launched Playwright without frontend dependencies (exit 127) and enforcement demanded browser
gates the classifier never asked for. These tests pin the single-authority rule.

M1 split the single job into ``classify`` / ``backend`` / ``frontend`` / ``browser`` plus the
aggregate ``test``. Routing is now expressed as job-level conditions reading
``needs.classify.outputs``, so the assertions moved with it.
"""

from __future__ import annotations

import io
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"

# YAML 1.1 parses the bare key "on" as the boolean True.
EVENT_TYPE_ROUTING = "github.event_name"


def _workflow() -> dict:
    return yaml.safe_load(io.open(WORKFLOW, encoding="utf-8"))


def _jobs() -> dict:
    return _workflow()["jobs"]


def _steps(job: str) -> list[dict]:
    return _jobs()[job]["steps"]


def _by_id(job: str, step_id: str) -> dict:
    for step in _steps(job):
        if step.get("id") == step_id:
            return step
    raise AssertionError(f"step {step_id!r} not found in {job}")


def test_the_split_jobs_and_the_single_required_check_exist():
    jobs = _jobs()

    assert set(jobs) == {"classify", "backend", "frontend", "browser", "test"}
    assert jobs["test"]["name"] == "test"
    # Only the aggregate may own the required name.
    assert sum(1 for job in jobs.values() if job.get("name") == "test") == 1


def test_the_aggregate_runs_even_when_a_dependency_fails_and_judges_every_job():
    aggregate = _jobs()["test"]

    assert sorted(aggregate["needs"]) == ["backend", "browser", "classify", "frontend"]
    # Without always(), a failed dependency skips the aggregate, and a skipped
    # required check reads as a pass to most protection configurations.
    assert aggregate["if"] == "always()"

    judge = aggregate["steps"][-1]
    assert "--mode jobs" in judge["run"]
    assert judge["env"]["CI_NEEDS"] == "${{ toJSON(needs) }}"
    assert judge["env"]["CI_BROWSER_REQUIRED"] == (
        "${{ needs.classify.outputs.frontend_e2e_required }}"
    )
    assert judge["env"]["CI_FRONTEND_REQUIRED"] == (
        "${{ needs.classify.outputs.frontend_required }}"
    )


def test_the_classifier_publishes_what_the_other_jobs_route_on():
    outputs = _jobs()["classify"]["outputs"]

    for key in (
        "frontend_required",
        "frontend_e2e_required",
        "research_browser_required",
        "impact_set",
        "full_scope",
    ):
        assert outputs[key] == f"${{{{ steps.ci_scope.outputs.{key} }}}}"


def test_no_step_routes_on_the_event_type():
    for job_name in _jobs():
        for step in _steps(job_name):
            condition = str(step.get("if") or "")
            assert EVENT_TYPE_ROUTING not in condition, step.get("name") or step.get("id")


def test_the_browser_job_follows_the_classifier_and_stays_separate_from_frontend():
    jobs = _jobs()

    assert "needs.classify.outputs.frontend_e2e_required == 'true'" in jobs["browser"]["if"]
    assert "needs.classify.outputs.frontend_required == 'true'" in jobs["frontend"]["if"]
    # The two cost tiers stay distinct jobs; neither condition implies the other.
    assert jobs["browser"]["if"] != jobs["frontend"]["if"]


def test_the_browser_job_runs_in_the_pinned_playwright_container_without_apt():
    browser = _jobs()["browser"]

    image = browser["container"]["image"]
    assert image.startswith("mcr.microsoft.com/playwright:v1.62.1-noble@sha256:")
    # The image ships the browsers; installing them again would reintroduce the
    # apt stall this split exists to remove.
    for step in browser["steps"]:
        run = str(step.get("run") or "")
        assert "playwright install" not in run, step.get("name")


def test_browser_suites_install_dependencies_first_and_are_judged_separately():
    steps = _steps("browser")
    ids = [step.get("id") for step in steps]

    assert "browser_e2e" in ids and "real_stack_browser_e2e" in ids
    assert ids.index("browser_e2e") < ids.index("real_stack_browser_e2e")
    # npm and Python dependencies are installed before either suite runs.
    install_positions = [
        index
        for index, step in enumerate(steps)
        if "npm ci" in str(step.get("run") or "")
        or "pip install" in str(step.get("run") or "")
    ]
    assert install_positions
    assert max(install_positions) < ids.index("browser_e2e")

    judge = steps[-1]
    assert "--mode steps" in judge["run"]
    assert "--require" in judge["run"]
    assert "browser_e2e,real_stack_browser_e2e" in judge["run"]


def test_each_job_whose_steps_use_continue_on_error_ends_with_a_step_gate():
    """A failed continue-on-error step does not turn the job red by itself."""

    for job_name in ("classify", "backend", "frontend", "browser"):
        steps = _steps(job_name)
        assert any(step.get("continue-on-error") is True for step in steps), job_name
        assert "--mode steps" in str(steps[-1].get("run") or ""), job_name


def test_frontend_gate_does_not_reinstall_dependencies():
    # npm ci belongs to node_deps, so a frontend run installs once.
    assert "npm ci" in str(_by_id("frontend", "node_deps")["run"])
    assert "npm ci" not in str(_by_id("frontend", "frontend")["run"])


def test_main_push_uses_a_proven_batch_range():
    # G1-B: one merge push diffs against its parent, so the surviving run must classify the
    # batch range instead of its own slice.
    run = str(_by_id("classify", "ci_scope")["run"])
    assert "tools/ci_batch_range.py" in run
    assert "batch_mode" in run
    # An unprovable batch widens; it must never fall through to the single-slice range.
    assert "No provable batch range" in run


def test_batch_lookup_failure_widens_instead_of_degrading():
    # A denied lookup is not the same as "there is no earlier run". Collapsing the two is
    # how the batch silently returns to the single-slice range.
    run = str(_by_id("classify", "ci_scope")["run"])
    assert "Batch baseline lookup failed" in run
    assert "batch_lookup" in run


def test_workflow_may_read_actions_to_resolve_the_batch_start():
    data = yaml.safe_load(io.open(WORKFLOW, encoding="utf-8"))
    assert data["permissions"].get("actions") == "read"
