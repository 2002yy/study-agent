"""Plan against real commits; no test, product or provider execution."""

import json
import subprocess
import sys

import pytest

from tests.test_studyctl import invoke, repo as repo
from tools import studyctl


def commit(root, *names):
    subprocess.run(["git", "-C", str(root), "add", *names], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "fixture change",
        ],
        check=True,
    )
    return studyctl.git(root, "rev-parse", "HEAD")


@pytest.fixture
def planned(repo):
    (repo / "tests/test_studyctl.py").write_text("# fixture only\n", encoding="utf-8")
    (repo / "tests/stage_gates.json").write_text(
        json.dumps(
            {
                "schema_version": "staged-regression-policy-v1",
                "impact_sets": {"studyctl": ["tests/test_studyctl.py"]},
            }
        ),
        encoding="utf-8",
    )
    base = commit(repo, "tests/test_studyctl.py", "tests/stage_gates.json")
    (repo / "tools/studyctl.py").write_text("# changed fixture\n", encoding="utf-8")
    head = commit(repo, "tools/studyctl.py")
    return repo, base, head


def call(capsys, planned, *args):
    root, base, _ = planned
    return invoke(capsys, "test", "plan", "--repo", str(root), "--base", base, *args)


def test_named_impact_set_reuses_policy_without_execution(planned, capsys, monkeypatch):
    original = studyctl.subprocess.run

    def guarded(argv, **kwargs):
        assert argv[0] == "git", "plan must never start a test command"
        return original(argv, **kwargs)

    monkeypatch.setattr(studyctl.subprocess, "run", guarded)
    result = call(capsys, planned, "--json", "--dry-run")
    assert result["status"] == "PASS" and result["head_sha"] == planned[2]
    assert result["data"]["scope"]["impact_set"] == "studyctl"
    assert result["data"]["tests"] == ["tests/test_studyctl.py"]
    assert result["data"]["commands"][0][-2:] == ["--impact-set", "studyctl"]
    assert result["data"]["execution"] == "not_started"


def test_unknown_path_is_partial_and_does_not_request_automatic_l3(planned, capsys):
    root, _, _ = planned
    (root / "unknown.dat").write_text("data", encoding="utf-8")
    commit(root, "unknown.dat")
    result = call(capsys, planned)
    assert result["status"] == "PARTIAL" and result["exit_code"] == 3
    assert result["data"]["scope"]["full_scope"]
    assert result["data"]["scope"]["l3_eligible"]
    assert not result["data"]["l3_automatic"] and not result["data"]["commands"]


def test_working_tree_is_explicit_and_untracked_inclusion_is_conservative(
    planned, capsys
):
    root, _, _ = planned
    (root / "private-new.txt").write_text("fake-private-body", encoding="utf-8")
    excluded = call(capsys, planned)
    assert excluded["status"] == "PASS" and excluded["data"]["working_tree_excluded"]
    included = call(capsys, planned, "--include-working-tree")
    assert included["status"] == "PARTIAL"
    assert "private-new.txt" in included["data"]["changed_paths"]
    assert "fake-private-body" not in json.dumps(included)


def test_empty_range_is_l0_only(planned, capsys):
    root, _, head = planned
    result = invoke(capsys, "test", "plan", "--repo", str(root), "--base", head)
    assert result["status"] == "PASS" and result["data"]["changed_paths"] == []
    assert not result["data"]["commands"]


def test_docs_only_range_does_not_invent_an_impact_set(planned, capsys):
    root, _, head = planned
    (root / "README.md").write_text("docs", encoding="utf-8")
    commit(root, "README.md")
    result = invoke(capsys, "test", "plan", "--repo", str(root), "--base", head)
    assert result["status"] == "PASS"
    assert (
        not result["data"]["commands"] and not result["data"]["requires_scope_review"]
    )


@pytest.mark.parametrize("revision", ["missing-ref", "--all"])
def test_invalid_or_option_like_revisions_are_json_errors(planned, capsys, revision):
    result = call(capsys, planned, "--head=" + revision)
    assert result["exit_code"] == 2


def test_reversed_nonancestor_range_is_rejected(planned, capsys):
    root, base, head = planned
    result = invoke(
        capsys, "test", "plan", "--repo", str(root), "--base", head, "--head", base
    )
    assert result["exit_code"] == 2


@pytest.mark.parametrize(
    "change", ["bad-json", "missing-test", "missing-set", "empty-set"]
)
def test_invalid_registration_never_produces_runnable_plan(planned, capsys, change):
    root, _, _ = planned
    if change == "bad-json":
        (root / "tests/stage_gates.json").write_text("{", encoding="utf-8")
    elif change == "missing-test":
        (root / "tests/test_studyctl.py").unlink()
    elif change == "empty-set":
        (root / "tests/stage_gates.json").write_text(
            json.dumps(
                {
                    "schema_version": "staged-regression-policy-v1",
                    "impact_sets": {"studyctl": []},
                }
            ),
            encoding="utf-8",
        )
    else:
        (root / "tests/stage_gates.json").write_text(
            '{"schema_version":"staged-regression-policy-v1"}', encoding="utf-8"
        )
    result = call(capsys, planned)
    assert result["exit_code"] == 3 and result["status"] == "BLOCKED"


def test_direct_entrypoint_plan_imports_own_policy(planned):
    root, base, _ = planned
    result = subprocess.run(
        [
            sys.executable,
            studyctl.__file__,
            "test",
            "plan",
            "--repo",
            str(root),
            "--base",
            base,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert (
        result.returncode == 0
        and json.loads(result.stdout)["data"]["scope"]["impact_set"] == "studyctl"
    )


def test_plan_help_does_not_require_base(capsys):
    assert (
        "test plan"
        in invoke(capsys, "test", "plan", "--help", "--json")["data"]["commands"]
    )


def test_excluded_dirty_policy_cannot_silently_select_fewer_tests(planned, capsys):
    root, _, _ = planned
    (root / "tests/stage_gates.json").write_text(
        json.dumps(
            {
                "schema_version": "staged-regression-policy-v1",
                "impact_sets": {"studyctl": ["tests/test_studyctl.py"]},
                "note": "uncommitted policy",
            }
        ),
        encoding="utf-8",
    )
    result = call(capsys, planned)
    assert result["exit_code"] == 3 and result["errors"][0]["code"] == "policy_modified"


def test_whitespace_path_is_not_trimmed_into_a_registered_path(planned, capsys):
    root, _, _ = planned
    folder = root / " tools"
    folder.mkdir()
    (folder / "studyctl.py").write_text("# odd filename", encoding="utf-8")
    commit(root, " tools/studyctl.py")
    result = call(capsys, planned)
    assert (
        result["exit_code"] == 3 and result["errors"][0]["code"] == "unsupported_path"
    )


def test_historical_head_cannot_label_current_checkout_commands(planned, capsys):
    root, base, _ = planned
    result = call(capsys, planned, "--head", base)
    assert result["exit_code"] == 2
    assert result["errors"][0]["code"] == "plan_head_mismatch"
    assert not result["data"].get("commands")


def test_manifest_tests_are_resolved_in_target_checkout(planned, capsys):
    root, _, _ = planned
    unique = "tests/test_only_in_target_checkout.py"
    (root / unique).write_text("# target-only\n", encoding="utf-8")
    manifest = root / "tests/stage_gates.json"
    data = json.loads(manifest.read_text())
    data["impact_sets"]["studyctl"] = [unique]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    base = commit(root, unique, "tests/stage_gates.json")
    (root / "tools/studyctl.py").write_text("# next CLI revision\n", encoding="utf-8")
    commit(root, "tools/studyctl.py")
    result = invoke(capsys, "test", "plan", "--repo", str(root), "--base", base)
    assert result["exit_code"] == 0 and result["data"]["tests"] == [unique]


def test_l0_checks_cover_committed_whitespace_and_explicit_dirty_changes(
    planned, capsys
):
    root, _, _ = planned
    (root / "tools/studyctl.py").write_text(
        "# committed trailing spaces  \n", encoding="utf-8"
    )
    head = commit(root, "tools/studyctl.py")
    result = call(capsys, planned)
    checks = result["data"]["quick_checks"]
    assert checks[1] == [
        "git",
        "-C",
        str(root),
        "diff",
        "--check",
        planned[1],
        head,
        "--",
    ]
    assert subprocess.run(checks[1], capture_output=True).returncode != 0
    (root / "tools/studyctl.py").write_text(
        "# dirty trailing spaces  \n", encoding="utf-8"
    )
    result = call(capsys, planned, "--include-working-tree")
    checks = result["data"]["quick_checks"]
    assert ["git", "-C", str(root), "diff", "--check", "HEAD", "--"] in checks
    assert subprocess.run(checks[-1], capture_output=True).stdout
    assert result["data"]["quick_checks_require_empty_stdout"]


def test_literal_git_backslash_is_rejected_before_classification(
    planned, capsys, monkeypatch
):
    original = studyctl.git

    def literal_path(root, *args):
        if "diff" in args and "-z" in args:
            return "tools\\studyctl.py\0"
        return original(root, *args)

    monkeypatch.setattr(studyctl, "git", literal_path)
    result = call(capsys, planned)
    assert (
        result["exit_code"] == 3 and result["errors"][0]["code"] == "unsupported_path"
    )
