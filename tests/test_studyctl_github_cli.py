"""Live reads require explicit identity; dry-run and bad input never call GitHub."""

import json
import subprocess
import sys
from unittest.mock import Mock

import pytest

from tests.test_studyctl import invoke, repo as repo
from tools import studyctl, studyctl_github

HEAD = "a" * 40


def command(capsys, repo, *extra, name="collect"):
    args = [
        "--repo",
        str(repo),
        "ci",
        name,
        "--github-repo",
        "example/project",
        "--exact-head",
        HEAD,
    ]
    if name == "collect":
        args += ["--pr", "7"]
    return invoke(capsys, *args, *extra)


@pytest.mark.parametrize("name", ["collect", "main"])
def test_cli_live_identity_output_and_attribution(monkeypatch, repo, capsys, name):
    collect = Mock(
        return_value=dict(status="PASS", exit_code=0, errors=[], merge_authorized=False)
    )
    monkeypatch.setattr(studyctl_github, "collect", collect)
    result = command(capsys, repo, "--required-check", "test", name=name)
    assert result["exit_code"] == 0
    assert result["data"]["merge_authorized"] is False
    assert result["head_sha"] == studyctl.repository(studyctl.ROOT)[1]
    assert result["data"]["requested_repo_head_sha"] == studyctl.repository(repo)[1]
    collect.assert_called_once_with(
        "example/project",
        HEAD,
        pr=7 if name == "collect" else None,
        project_checks=["test"],
    )


@pytest.mark.parametrize("name", ["collect", "main"])
def test_dry_run_has_no_network_no_report_and_no_verification(
    monkeypatch, repo, capsys, tmp_path, name
):
    collect = Mock(side_effect=AssertionError("network called"))
    monkeypatch.setattr(studyctl_github, "collect", collect)
    output = tmp_path / "receipt.json"
    result = command(capsys, repo, "--dry-run", "--output", str(output), name=name)
    assert result["exit_code"] == 3 and result["data"]["network"] == "not_requested"
    assert not output.exists()
    collect.assert_not_called()


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--github-repo", "example/project"],
        ["--github-repo", "example/project", "--exact-head", HEAD],
        ["--github-repo", "../project", "--exact-head", HEAD, "--pr", "7"],
        ["--github-repo", "example/project", "--exact-head", HEAD, "--pr", "0"],
    ],
)
def test_invalid_selector_does_not_start_transport(monkeypatch, repo, capsys, args):
    collect = Mock()
    monkeypatch.setattr(studyctl_github, "collect", collect)
    assert invoke(capsys, "--repo", str(repo), "ci", "collect", *args)["exit_code"] == 2
    collect.assert_not_called()


def test_errors_are_sanitized_and_preserve_no_partial_authority(
    monkeypatch, repo, capsys
):
    monkeypatch.setattr(
        studyctl_github, "collect", Mock(side_effect=ValueError("private-credential"))
    )
    result = command(capsys, repo)
    assert result["exit_code"] == 3
    assert "private-credential" not in json.dumps(result)


def test_existing_output_prevents_network(monkeypatch, repo, capsys, tmp_path):
    collect = Mock()
    monkeypatch.setattr(studyctl_github, "collect", collect)
    output = tmp_path / "receipt.json"
    output.write_text("preserve", encoding="utf-8")
    assert command(capsys, repo, "--output", str(output))["exit_code"] == 3
    assert output.read_text() == "preserve"
    collect.assert_not_called()


def test_failed_required_check_is_cli_failure(monkeypatch, repo, capsys):
    monkeypatch.setattr(
        studyctl_github,
        "collect",
        Mock(
            return_value=dict(
                status="FAIL",
                exit_code=4,
                errors=[dict(code="required_check_failed")],
                merge_authorized=False,
            )
        ),
    )
    result = command(capsys, repo)
    assert result["status"] == "FAIL" and result["exit_code"] == 4


def test_actual_entrypoint_dry_run_is_one_json_and_no_stderr(repo):
    result = subprocess.run(
        [
            sys.executable,
            str(studyctl.ROOT / "tools/studyctl.py"),
            "--repo",
            str(repo),
            "ci",
            "main",
            "--github-repo",
            "example/project",
            "--exact-head",
            HEAD,
            "--dry-run",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 3
    assert len(result.stdout.splitlines()) == 1 and not result.stderr
    assert json.loads(result.stdout)["data"]["network"] == "not_requested"
