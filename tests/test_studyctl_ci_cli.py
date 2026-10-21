"""CLI replays saved evidence without contacting GitHub or granting merge authority."""

import json
import subprocess
import sys

import pytest

from tests.test_studyctl import invoke, repo as repo
from tests.test_studyctl_ci import (
    HEAD,
    REPOSITORY,
    change,
    receipt as receipt,
    snapshot as snapshot,
)
from tools import studyctl


def inspect(repo, snapshot, capsys, *args):
    return invoke(
        capsys,
        "--repo",
        str(repo),
        "ci",
        "inspect",
        "--snapshot",
        str(snapshot),
        "--github-repo",
        REPOSITORY,
        "--pr",
        "7",
        "--exact-head",
        HEAD,
        *args,
    )


def outcomes(repo, receipt, capsys, *args):
    return invoke(
        capsys,
        "--repo",
        str(repo),
        "ci",
        "outcomes",
        "--receipt",
        str(receipt),
        "--exact-head",
        HEAD,
        "--run-id",
        "42",
        "--event",
        "pull_request",
        *args,
    )


def test_inspection_keeps_green_recording_blocked_and_binds_tool_head(
    repo, snapshot, capsys
):
    before = snapshot.read_bytes()
    result = inspect(repo, snapshot, capsys)
    assert result["command"] == "ci inspect" and result["status"] == "BLOCKED"
    assert result["data"]["head_matches"] and not result["data"]["merge_authorized"]
    assert result["head_sha"] == studyctl.git(studyctl.ROOT, "rev-parse", "HEAD")
    assert result["data"]["requested_repo_head_sha"] == studyctl.git(
        repo, "rev-parse", "HEAD"
    )
    assert (
        result["data"]["expected_head_sha"] == HEAD and snapshot.read_bytes() == before
    )


def test_outcome_receipt_pass_is_not_full_ci_approval(repo, receipt, capsys):
    result = outcomes(repo, receipt, capsys)
    assert result["command"] == "ci outcomes" and result["exit_code"] == 0
    assert not result["data"]["merge_authorized"]
    assert "do-not-emit" not in json.dumps(result)


def test_failed_raw_outcome_retains_failure_despite_success_conclusion(
    repo, receipt, capsys
):
    change(
        receipt,
        lambda data: data["steps"]["ruff"].update(
            outcome="failure", conclusion="success"
        ),
    )
    result = outcomes(repo, receipt, capsys)
    assert result["exit_code"] == 4 and result["data"]["failed_steps"] == ["ruff"]


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["inspect"],
        ["outcomes"],
        ["inspect", "--exact-head", "abc"],
        ["outcomes", "--exact-head", HEAD, "--run-id", "0"],
    ],
)
def test_missing_or_invalid_selectors_are_sanitized_argument_errors(repo, capsys, args):
    result = invoke(capsys, "--repo", str(repo), "ci", *args)
    assert result["exit_code"] == 2


def test_invalid_source_content_is_not_echoed(repo, snapshot, capsys):
    snapshot.write_text("private-broken-evidence", encoding="utf-8")
    result = inspect(repo, snapshot, capsys)
    assert result["exit_code"] == 3 and "private-broken" not in json.dumps(result)


def test_wrong_workflow_event_is_not_promoted(repo, snapshot, capsys):
    change(snapshot, lambda data: data["checks"][0]["runs"][0].update(event="push"))
    result = inspect(repo, snapshot, capsys)
    assert "workflow_event_mismatch" in result["data"]["missing_evidence"]


def test_dry_run_keeps_output_absent(repo, receipt, capsys, tmp_path):
    output = tmp_path / "no-report.json"
    assert (
        outcomes(repo, receipt, capsys, "--dry-run", "--output", str(output))[
            "exit_code"
        ]
        == 0
    )
    assert not output.exists()


def test_ci_inspection_never_invokes_gh_or_other_processes(
    repo, snapshot, capsys, monkeypatch
):
    original = subprocess.run

    def guarded(argv, **kwargs):
        assert argv[0] == "git", "offline evidence cannot invoke GitHub or runners"
        return original(argv, **kwargs)

    monkeypatch.setattr(studyctl.subprocess, "run", guarded)
    assert inspect(repo, snapshot, capsys)["exit_code"] == 3


def test_direct_entrypoint_has_one_json_and_no_stderr(repo, receipt):
    result = subprocess.run(
        [
            sys.executable,
            studyctl.__file__,
            "--repo",
            str(repo),
            "ci",
            "outcomes",
            "--receipt",
            str(receipt),
            "--exact-head",
            HEAD,
            "--run-id",
            "42",
            "--event",
            "pull_request",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert (
        result.returncode == 0
        and len(result.stdout.splitlines()) == 1
        and result.stderr == ""
    )
    assert json.loads(result.stdout)["data"]["merge_authorized"] is False
