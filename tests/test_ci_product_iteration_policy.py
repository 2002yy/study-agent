"""Negative controls for the root-discoverable two-loop iteration policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.check_product_iteration_policy import (
    REPO_ROOT,
    REQUIRED_FILES,
    check_policy,
)


def test_current_product_policy_contract() -> None:
    assert check_policy(REPO_ROOT) == []


@pytest.fixture
def isolated_policy(tmp_path: Path) -> Path:
    for rel in REQUIRED_FILES:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((REPO_ROOT / rel).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def test_missing_cold_start_pointer_is_rejected(isolated_policy: Path) -> None:
    agents = isolated_policy / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace(
            "docs/PRODUCT_ITERATION_POLICY.md", "missing-policy.md"
        ),
        encoding="utf-8",
    )
    assert any("cold-start" in issue for issue in check_policy(isolated_policy))


def test_missing_dynamic_loop_is_rejected(isolated_policy: Path) -> None:
    policy = isolated_policy / "docs/PRODUCT_ITERATION_POLICY.md"
    policy.write_text(
        policy.read_text(encoding="utf-8").replace(
            "## Dynamic Loop (real user task, authorized and budgeted)",
            "## Dynamic Loop deleted",
        ),
        encoding="utf-8",
    )
    assert any("Dynamic Loop" in issue for issue in check_policy(isolated_policy))


def test_reversed_priority_is_rejected(isolated_policy: Path) -> None:
    policy = isolated_policy / "docs/PRODUCT_ITERATION_POLICY.md"
    policy.write_text(
        policy.read_text(encoding="utf-8").replace("**P0**", "**PX**", 1),
        encoding="utf-8",
    )
    assert any("P0 -> P1" in issue for issue in check_policy(isolated_policy))


def test_missing_ci_enforcement_is_rejected(isolated_policy: Path) -> None:
    workflow = isolated_policy / ".github/workflows/ci.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "id: product_policy", "id: policy_missing"
        ),
        encoding="utf-8",
    )
    assert any("always-on" in issue for issue in check_policy(isolated_policy))


def test_missing_document_index_is_rejected(isolated_policy: Path) -> None:
    index = isolated_policy / "docs/README.md"
    index.write_text(
        index.read_text(encoding="utf-8").replace(
            "PRODUCT_ITERATION_POLICY.md", "POLICY_NOT_FOUND.md"
        ),
        encoding="utf-8",
    )
    assert any("index" in issue for issue in check_policy(isolated_policy))


def test_missing_pr_dynamic_evidence_field_is_rejected(isolated_policy: Path) -> None:
    template = isolated_policy / ".github/pull_request_template.md"
    template.write_text(
        template.read_text(encoding="utf-8").replace(
            "## Dynamic evidence (actual or not_run)", "## Dynamic evidence removed"
        ),
        encoding="utf-8",
    )
    assert any("PR template" in issue for issue in check_policy(isolated_policy))
