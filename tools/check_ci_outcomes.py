"""Close CI once, using outcomes rather than continue-on-error conclusions."""

from __future__ import annotations

import json
import os

REQUIRED_STEPS = (
    "pytest", "rag_quality", "ruff", "packaging", "secrets", "mypy_baseline", "frontend"
)
BROWSER_STEPS = ("playwright_install", "browser_e2e", "real_stack_browser_e2e")


def failed_steps(steps: dict, *, browser_required: bool) -> list[str]:
    required = REQUIRED_STEPS + (BROWSER_STEPS if browser_required else ())
    failed = [name for name in required if steps.get(name, {}).get("outcome") != "success"]
    # Optional checks can be skipped, but an executed check must still succeed.
    if not browser_required:
        failed.extend(
            name for name in BROWSER_STEPS
            if steps.get(name, {}).get("outcome", "skipped") not in {"success", "skipped"}
        )
    return failed


def main() -> int:
    try:
        steps = json.loads(os.environ["CI_STEP_RESULTS"])
        browser_required = os.environ["CI_BROWSER_REQUIRED"]
        if not isinstance(steps, dict) or browser_required not in {"true", "false"}:
            raise ValueError("Invalid CI outcomes input")
        failed = failed_steps(steps, browser_required=browser_required == "true")
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        print(f"CI outcome check failed: {exc}")
        return 1
    if failed:
        print("Required CI checks did not succeed: " + ", ".join(failed))
        return 1
    print("All required CI checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
