"""The gate must be reachable through the real CLI, not only by import.

`main()` was reading its parameter instead of `sys.argv`, so
`python tools/check_ci_outcomes.py --mode jobs` ignored the flag and fell back to
the step mode. Import-level tests cannot see that, so these run the script the
way the workflow does.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check_ci_outcomes.py"

ALL_GREEN = json.dumps(
    {
        "classify": {"result": "success"},
        "backend": {"result": "success"},
        "frontend": {"result": "success"},
        "browser": {"result": "success"},
    }
)


def run_gate(**env_overrides: str) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CI_", "GITHUB_"))
    }
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "jobs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def test_the_cli_reaches_jobs_mode_instead_of_falling_back_to_steps():
    """`--mode jobs` must be honoured even when step results are present.

    The step payload says pytest failed. Only the job payload decides here; a
    fallback to step mode would fail this run (or pass it for the wrong reason).
    """

    result = run_gate(
        CI_NEEDS=ALL_GREEN,
        CI_FRONTEND_REQUIRED="true",
        CI_BROWSER_REQUIRED="true",
        CI_STEP_RESULTS='{"pytest": {"outcome": "failure"}}',
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "All required CI jobs passed" in result.stdout


def test_a_required_job_that_is_skipped_fails_through_the_cli():
    needs = json.loads(ALL_GREEN)
    needs["browser"]["result"] = "skipped"

    result = run_gate(
        CI_NEEDS=json.dumps(needs),
        CI_FRONTEND_REQUIRED="false",
        CI_BROWSER_REQUIRED="true",
    )

    assert result.returncode == 1
    assert "browser:skipped" in result.stdout


def test_a_skipped_optional_job_passes_through_the_cli():
    needs = json.loads(ALL_GREEN)
    needs["frontend"]["result"] = "skipped"
    needs["browser"]["result"] = "skipped"

    result = run_gate(
        CI_NEEDS=json.dumps(needs),
        CI_FRONTEND_REQUIRED="false",
        CI_BROWSER_REQUIRED="false",
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_a_missing_requirement_fails_closed_instead_of_downgrading_to_optional():
    """No CI_BROWSER_REQUIRED must not mean "browser is optional"."""

    for missing in ("CI_FRONTEND_REQUIRED", "CI_BROWSER_REQUIRED"):
        env = {
            "CI_NEEDS": ALL_GREEN,
            "CI_FRONTEND_REQUIRED": "true",
            "CI_BROWSER_REQUIRED": "true",
        }
        env.pop(missing)

        result = run_gate(**env)

        assert result.returncode == 1, missing
        assert "CI job gate failed" in result.stdout


def test_an_invalid_requirement_value_fails_closed():
    result = run_gate(
        CI_NEEDS=ALL_GREEN,
        CI_FRONTEND_REQUIRED="yes",
        CI_BROWSER_REQUIRED="true",
    )

    assert result.returncode == 1
    assert "Invalid frontend requirement" in result.stdout


def test_a_missing_needs_payload_fails_closed():
    result = run_gate(
        CI_FRONTEND_REQUIRED="true",
        CI_BROWSER_REQUIRED="true",
    )

    assert result.returncode == 1
