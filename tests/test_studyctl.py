"""Offline CLI contract: real Git metadata, no user credentials or product runtime."""

import json
from pathlib import Path
import subprocess

import pytest

from tools import studyctl


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "中文 repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for name in studyctl.OWNERS + (
        "tools/ci_scope.py",
        "tools/run_stage_gate.py",
        "tools/l3_preflight.py",
    ):
        path = root / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(
            '{"schema_version":"staged-regression-policy-v1"}'
            if name.endswith(".json")
            else "fixture\n",
            encoding="utf-8",
        )
    subprocess.run(
        ["git", "-C", str(root), "add", *studyctl.OWNERS, "tools"], check=True
    )
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
            "fixture",
        ],
        check=True,
    )
    return root


def invoke(capsys, *args):
    code = studyctl.main(list(args))
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert captured.err == "" and result["exit_code"] == code
    assert len(captured.out.splitlines()) == 1
    return result


@pytest.mark.parametrize("command", ["status", "doctor"])
def test_read_only_real_repo(repo, capsys, command):
    before = (repo / ".git/index").read_bytes()
    result = invoke(capsys, command, "--repo", str(repo), "--json")
    assert result["status"] == "PASS" and len(result["head_sha"]) == 40
    assert (repo / ".git/index").read_bytes() == before


def test_dirty_and_untracked_are_separate(repo, capsys):
    (repo / "AGENTS.md").write_text("dirty", encoding="utf-8")
    (repo / "private.txt").write_text("fake-private-value", encoding="utf-8")
    result = invoke(capsys, "--repo", str(repo), "status")
    assert result["data"]["tracked_changes"] == 1
    assert result["data"]["untracked_entries"] == 1
    assert "fake-private-value" not in json.dumps(result)


@pytest.mark.parametrize(
    "args", [[], ["bad-command"], ["status", "--token", "fake-sensitive-argument"]]
)
def test_bad_arguments_are_json_and_do_not_echo_values(capsys, args):
    result = invoke(capsys, *args)
    assert result["exit_code"] == 2
    assert "fake-sensitive-argument" not in json.dumps(result)


def test_missing_repo_is_blocked(tmp_path, capsys):
    assert (
        invoke(capsys, "status", "--repo", str(tmp_path / "missing"))["exit_code"] == 3
    )


def test_missing_contract_and_bad_json_block_doctor(repo, capsys):
    (repo / "tests/stage_gates.json").write_text("{", encoding="utf-8")
    result = invoke(capsys, "doctor", "--repo", str(repo))
    assert result["exit_code"] == 3 and not result["data"]["checks"]["gate_schema"]


@pytest.mark.parametrize(
    "error,expected",
    [(FileNotFoundError(), 3), (subprocess.TimeoutExpired("git", 5), 5)],
)
def test_git_dependency_and_timeout_are_sanitized(monkeypatch, capsys, error, expected):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(studyctl.subprocess, "run", fail)
    assert invoke(capsys, "status")["exit_code"] == expected


def test_new_output_no_overwrite_and_dry_run(repo, capsys, tmp_path):
    output = tmp_path / "report.json"
    result = invoke(
        capsys, "status", "--repo", str(repo), "--output", str(output), "--dry-run"
    )
    assert result["exit_code"] == 0 and not output.exists()
    result = invoke(capsys, "status", "--repo", str(repo), "--output", str(output))
    original = output.read_bytes()
    assert json.loads(original)["head_sha"] == result["head_sha"]
    assert (
        invoke(capsys, "status", "--repo", str(repo), "--output", str(output))[
            "exit_code"
        ]
        == 3
    )
    assert output.read_bytes() == original


def test_help_json_does_not_need_git(capsys, monkeypatch):
    monkeypatch.setattr(
        studyctl, "repository", lambda _: pytest.fail("help must not read Git")
    )
    assert "doctor" in invoke(capsys, "--help", "--json")["data"]["commands"]


def test_entrypoint_runs_without_global_package(repo):
    result = subprocess.run(
        [
            __import__("sys").executable,
            str(Path(studyctl.__file__)),
            "status",
            "--repo",
            str(repo),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0 and json.loads(result.stdout)["status"] == "PASS"
