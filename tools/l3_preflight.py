"""L3 preflight: the seconds-scale qualification prerequisites.

Full L3 is a release/authority gate, not an iteration loop. Starting an ~18 minute run
only to discover the checkout is dirty is pure waste, so this runs first and refuses to
let the expensive suite start when a prerequisite is already known to be unmet.

It is deliberately cheap and read-only: no network, no test collection, no mutation.

Exit code 0 means "clear to run L3". Any non-zero code means "do not start L3", with the
specific reason on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
STAGE_GATES = ROOT / "tests" / "stage_gates.json"

EXACT_SHA = re.compile(r"^[0-9a-f]{40}$")

# Top-level keys stage_gates.json must carry for the tiered policy to be enforceable.
REQUIRED_STAGE_GATE_KEYS = (
    "schema_version",
    "levels",
    "impact_sets",
    "stage_gates",
    "force_l3_triggers",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    ).stdout


def check_tracked_clean() -> str:
    """Empty string when the tracked checkout is clean, else a failure reason."""

    status = _git("status", "--porcelain=v1", "--untracked-files=no")
    if status.strip():
        first = status.strip().splitlines()[0]
        return f"dirty_tracked_checkout: {first}"
    return ""


def check_exact_head() -> tuple[str, str]:
    """Return (reason, sha). Reason is empty when HEAD is an exact 40-char SHA."""

    sha = _git("rev-parse", "HEAD").strip()
    if not EXACT_SHA.match(sha):
        return f"head_is_not_exact_sha: {sha!r}", sha
    return "", sha


def check_github_sha(head: str) -> str:
    """Consistency with the CI-provided SHA, when one is present."""

    expected = (os.getenv("GITHUB_SHA") or "").strip()
    if expected and expected != head:
        return f"github_sha_mismatch: expected={expected} head={head}"
    return ""


def check_stage_gates() -> str:
    """The gate configuration must exist, parse, and carry the policy keys."""

    if not STAGE_GATES.exists():
        return f"stage_gates_missing: {STAGE_GATES}"
    try:
        data = json.loads(STAGE_GATES.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"stage_gates_unparseable: {type(exc).__name__}"
    if not isinstance(data, dict):
        return "stage_gates_not_an_object"
    missing = [key for key in REQUIRED_STAGE_GATE_KEYS if key not in data]
    if missing:
        return f"stage_gates_missing_keys: {','.join(missing)}"
    if not isinstance(data.get("impact_sets"), dict) or not data["impact_sets"]:
        return "stage_gates_impact_sets_empty"
    return ""


def run_checks() -> list[str]:
    failures: list[str] = []
    dirty = check_tracked_clean()
    if dirty:
        failures.append(dirty)
    head_reason, head = check_exact_head()
    if head_reason:
        failures.append(head_reason)
    elif head:
        mismatch = check_github_sha(head)
        if mismatch:
            failures.append(mismatch)
    gates = check_stage_gates()
    if gates:
        failures.append(gates)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="L3 preflight (fail fast, do not start L3)")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print only the verdict line",
    )
    args = parser.parse_args(argv)

    failures = run_checks()
    if failures:
        if not args.quiet:
            for failure in failures:
                print(f"L3_PRECHECK_FAIL {failure}")
        print(f"L3_PRECHECK: FAIL ({len(failures)} reason(s)); do not start L3")
        return 1
    if not args.quiet:
        print("L3_PRECHECK_OK clean tracked checkout, exact HEAD, gates valid")
    print("L3_PRECHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
