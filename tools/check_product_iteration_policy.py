"""Fast, dependency-free check of the permanent two-loop product policy entrypoints.

This detects accidental deletion or loss of discoverability. It cannot infer
whether a model obeyed the policy; that is an evidence/review responsibility.
"""

from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "AGENTS.md",
    "README.md",
    "docs/README.md",
    "docs/PRODUCT_ITERATION_POLICY.md",
    ".github/workflows/ci.yml",
    ".github/pull_request_template.md",
)
POLICY_LINK = "docs/PRODUCT_ITERATION_POLICY.md"
POLICY_SECTIONS = (
    "## Priority order (binding)",
    "## Static Loop (deterministic, no model/API spending)",
    "## Dynamic Loop (real user task, authorized and budgeted)",
    "## Evidence and release discipline",
    "## Agent startup, branch visibility, and governance",
)
PRIORITIES = ("**P0**", "**P1**", "**P2**", "**P3**")


def check_policy(root: Path) -> list[str]:
    """Return actionable violations; never require extra network or model calls."""
    content: dict[str, str] = {}
    errors: list[str] = []
    for rel in REQUIRED_FILES:
        try:
            content[rel] = (root / rel).read_text(encoding="utf-8")
        except (FileNotFoundError, UnicodeError):
            errors.append(f"missing or unreadable: {rel}")
    if errors:
        return errors

    agents = content["AGENTS.md"]
    if POLICY_LINK not in agents[:3500]:
        errors.append("AGENTS.md must link to policy in its cold-start header")
    if "## 0. Mandatory product priority" not in agents[:3500]:
        errors.append("AGENTS.md must state the mandatory early product priority")
    if "docs/PROJECT_STATUS.md" not in agents[:3500]:
        errors.append("AGENTS.md must preserve Current Handoff as state owner")
    if POLICY_LINK not in content["README.md"]:
        errors.append("README.md must link to product policy")
    if "PRODUCT_ITERATION_POLICY.md" not in content["docs/README.md"]:
        errors.append("docs/README.md must index the product policy")

    policy = content["docs/PRODUCT_ITERATION_POLICY.md"]
    for section in POLICY_SECTIONS:
        if section not in policy:
            errors.append(f"policy missing section: {section}")
    positions = [policy.find(p) for p in PRIORITIES]
    if any(pos < 0 for pos in positions) or positions != sorted(positions):
        errors.append("policy must rank P0 -> P1 -> P2 -> P3 in that order")
    if "not_run" not in policy or "product-no-go" not in policy:
        errors.append("policy must distinguish untested dynamic behavior from GO")
    if "shared durable budget cap" not in policy or "explicit" not in policy:
        errors.append("policy must prohibit unauthorized paid dynamic tests")
    if "assistant_message" not in policy or "ChatGPT" not in policy:
        errors.append("policy must require actual answer and comparison evidence")

    template = content[".github/pull_request_template.md"]
    for heading in (
        "## User task, priority and causal owner",
        "## Static evidence (exact head)",
        "## Dynamic evidence (actual or not_run)",
        "## Safety, cost and decision",
    ):
        if heading not in template:
            errors.append(f"PR template missing product evidence field: {heading}")

    workflow = content[".github/workflows/ci.yml"]
    if "id: product_policy" not in workflow:
        errors.append("CI must include always-on product_policy step")
    if "python tools/check_product_iteration_policy.py" not in workflow:
        errors.append("CI must actually run the discoverability check")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the two-loop policy entrypoints")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    issues = check_policy(args.root)
    for issue in issues:
        print(f"PRODUCT_POLICY_FAIL: {issue}")
    if issues:
        return 1
    print("PRODUCT_POLICY_OK: startup, priorities, dynamic evidence and CI entrypoint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
