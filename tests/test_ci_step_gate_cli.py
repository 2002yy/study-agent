"""`--mode steps --require` is what catches a failed continue-on-error step.

A job whose steps all use `continue-on-error: true` still reports `success` as a
job. The split workflow therefore ends backend/frontend/browser with this gate;
these cases pin the alternation (`pytest|pytest_impact`) and the fail-closed
paths.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check_ci_outcomes.py"


def run_steps(require: str, steps: dict) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("CI_")}
    env["CI_STEP_RESULTS"] = json.dumps(steps)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "steps", "--require", require],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def test_a_failed_continue_on_error_step_is_caught():
    result = run_steps(
        "pytest|pytest_impact,ruff",
        {"pytest": {"outcome": "failure"}, "ruff": {"outcome": "success"}},
    )

    assert result.returncode == 1
    assert "pytest|pytest_impact" in result.stdout


def test_the_alternative_step_satisfies_the_requirement():
    result = run_steps(
        "pytest|pytest_impact,ruff",
        {"pytest": {"outcome": "skipped"}, "pytest_impact": {"outcome": "success"},
         "ruff": {"outcome": "success"}},
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_a_missing_step_is_not_a_pass():
    result = run_steps("browser_e2e,real_stack_browser_e2e",
                       {"browser_e2e": {"outcome": "success"}})

    assert result.returncode == 1
    assert "real_stack_browser_e2e" in result.stdout


def test_both_browser_suites_are_required_and_reported_separately():
    result = run_steps(
        "browser_e2e,real_stack_browser_e2e",
        {"browser_e2e": {"outcome": "success"},
         "real_stack_browser_e2e": {"outcome": "failure"}},
    )

    assert result.returncode == 1
    reported = result.stdout.split("did not succeed: ", 1)[1].strip().split(", ")
    assert reported == ["real_stack_browser_e2e"]


def test_steps_mode_without_require_fails_closed():
    env = {key: value for key, value in os.environ.items() if not key.startswith("CI_")}
    env["CI_STEP_RESULTS"] = "{}"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "steps"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )

    assert result.returncode == 1
    assert "--require" in result.stdout
