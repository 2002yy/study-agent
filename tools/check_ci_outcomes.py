"""Close CI once, using outcomes rather than continue-on-error conclusions."""

from __future__ import annotations

import json
import os
import sys

REQUIRED_STEPS = (
    "product_policy", "pytest", "rag_quality", "ruff", "packaging", "secrets", "mypy_baseline", "frontend"
)
# The fast tier may run a bounded impact set instead of the full suite. Exactly one of
# these must have succeeded, but which one is the caller's routing decision.
TEST_STEPS = ("pytest", "pytest_impact")
BROWSER_STEPS = ("playwright_install", "browser_e2e", "real_stack_browser_e2e")

# Whole-job results for the split workflow (M1+). The aggregate cannot read step
# outcomes across jobs, so it judges jobs - and it has to distinguish "the
# classifier said this job was not needed" from "the job was needed but never
# ran", which are the same `skipped` string.
JOBS = ("classify", "backend", "frontend", "browser")
VALID_JOB_RESULTS = frozenset({"success", "failure", "cancelled", "skipped"})


def failed_steps(
    steps: dict, *, browser_required: bool, frontend_required: bool = True
) -> list[str]:
    required = REQUIRED_STEPS + (BROWSER_STEPS if browser_required else ())
    failed: list[str] = []
    for name in required:
        outcome = steps.get(name, {}).get("outcome")
        if outcome == "success":
            continue
        # A bounded impact set stands in for the full suite on the fast tier.
        if name == "pytest" and steps.get("pytest_impact", {}).get("outcome") == "success":
            continue
        # The frontend toolchain is optional when the change set does not need it.
        if name == "frontend" and not frontend_required and outcome in (None, "skipped"):
            continue
        failed.append(name)
    # Optional checks can be skipped, but an executed check must still succeed.
    if not browser_required:
        failed.extend(
            name for name in BROWSER_STEPS
            if steps.get(name, {}).get("outcome", "skipped") not in {"success", "skipped"}
        )
    return failed


def judge_jobs(
    needs: object,
    *,
    frontend_required: bool,
    browser_required: bool,
) -> list[str]:
    """Reasons the aggregate gate must fail; empty means it passes.

    Rules:

    * classify and backend are always required;
    * frontend/browser are required only when the classifier says so;
    * a required job must be exactly ``success`` - ``skipped``, ``cancelled``,
      ``failure`` and a missing result all fail;
    * an optional job may be ``skipped``, but if it ran it must have succeeded;
    * an absent or unreadable result is a failure, never "not needed".
    """

    required = {
        "classify": True,
        "backend": True,
        "frontend": bool(frontend_required),
        "browser": bool(browser_required),
    }
    failures: list[str] = []
    for name in JOBS:
        entry = needs.get(name) if isinstance(needs, dict) else None
        result = entry.get("result") if isinstance(entry, dict) else None
        if result not in VALID_JOB_RESULTS:
            failures.append(f"{name}:missing")
            continue
        if result == "success":
            continue
        if result == "skipped" and not required[name]:
            continue
        failures.append(f"{name}:{result}")
    return failures


def _run_jobs_mode() -> int:
    try:
        needs = json.loads(os.environ["CI_NEEDS"])
        # Both requirements must be stated. Defaulting a missing variable to
        # "false" would silently downgrade a required job to optional, which is
        # the false green this mode exists to prevent.
        frontend_required = os.environ["CI_FRONTEND_REQUIRED"]
        browser_required = os.environ["CI_BROWSER_REQUIRED"]
        if frontend_required not in {"true", "false"}:
            raise ValueError(f"Invalid frontend requirement: {frontend_required!r}")
        if browser_required not in {"true", "false"}:
            raise ValueError(f"Invalid browser requirement: {browser_required!r}")
        failures = judge_jobs(
            needs,
            frontend_required=frontend_required == "true",
            browser_required=browser_required == "true",
        )
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        print(f"CI job gate failed: {exc}")
        return 1
    if failures:
        print("Required CI jobs did not succeed: " + ", ".join(failures))
        return 1
    print(
        "All required CI jobs passed"
        f" (frontend_required={frontend_required}, browser_required={browser_required})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    # Real invocations are `python tools/check_ci_outcomes.py --mode jobs`; the
    # entrypoint calls main() with no argument, so reading only the parameter
    # would ignore the flag the workflow passes and quietly run the step mode.
    args = list(sys.argv[1:] if argv is None else argv)
    if "--mode" in args:
        mode = args[args.index("--mode") + 1] if len(args) > args.index("--mode") + 1 else ""
        if mode != "jobs":
            print(f"Unknown CI gate mode: {mode!r}")
            return 1
        return _run_jobs_mode()
    try:
        steps = json.loads(os.environ["CI_STEP_RESULTS"])
        browser_required = os.environ["CI_BROWSER_REQUIRED"]
        frontend_required = os.environ.get("CI_FRONTEND_REQUIRED", "true")
        # Reported, never gated: the research web-fetch tier has no separate workflow step,
        # its coverage lives inside pytest. Keeping it out of the step list is the point of
        # the split - a crawler change must not demand frontend Golden Journeys.
        research_browser = os.environ.get("CI_RESEARCH_BROWSER_REQUIRED")
        if not isinstance(steps, dict) or browser_required not in {"true", "false"}:
            raise ValueError("Invalid CI outcomes input")
        if research_browser is not None and research_browser not in {"true", "false"}:
            raise ValueError("Invalid research browser requirement")
        failed = failed_steps(
            steps,
            browser_required=browser_required == "true",
            frontend_required=frontend_required == "true",
        )
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        print(f"CI outcome check failed: {exc}")
        return 1
    if failed:
        print("Required CI checks did not succeed: " + ", ".join(failed))
        return 1
    print(
        "All required CI checks passed"
        f" (frontend_e2e_required={browser_required}"
        f", research_browser_required={research_browser if research_browser is not None else 'n/a'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
