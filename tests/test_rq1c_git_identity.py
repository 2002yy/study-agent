from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.rq1c_git_identity as identity


HEAD = "a" * 40
OTHER = "b" * 40


def _completed(stdout: str = "") -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout)


def _git_run(*, head: str = HEAD, status: str = ""):
    def fake_run(command, *args, **kwargs):
        if command == ["git", "rev-parse", "HEAD"]:
            return _completed(head + "\n")
        if command == ["git", "status", "--porcelain=v1", "--untracked-files=no"]:
            return _completed(status)
        raise AssertionError(f"unexpected git command: {command!r}")

    return fake_run


def test_exact_checkout_sha_uses_git_head_when_ci_sha_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setattr(identity.subprocess, "run", _git_run())

    assert identity.exact_checkout_git_sha(Path(".")) == HEAD


def test_exact_checkout_sha_accepts_matching_ci_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_SHA", HEAD)
    monkeypatch.setattr(identity.subprocess, "run", _git_run())

    assert identity.exact_checkout_git_sha(Path(".")) == HEAD


def test_exact_checkout_sha_rejects_well_formed_but_stale_ci_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_SHA", OTHER)
    monkeypatch.setattr(identity.subprocess, "run", _git_run())

    with pytest.raises(RuntimeError, match="does not match"):
        identity.exact_checkout_git_sha(Path("."))


def test_exact_checkout_sha_rejects_malformed_ci_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_SHA", "not-a-sha")
    monkeypatch.setattr(identity.subprocess, "run", _git_run())

    with pytest.raises(RuntimeError, match="not an exact git sha"):
        identity.exact_checkout_git_sha(Path("."))


def test_exact_checkout_sha_rejects_malformed_checkout_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setattr(identity.subprocess, "run", _git_run(head="not-a-checkout-sha"))

    with pytest.raises(RuntimeError, match="checkout HEAD"):
        identity.exact_checkout_git_sha(Path("."))


def test_exact_checkout_sha_rejects_dirty_tracked_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_SHA", HEAD)
    monkeypatch.setattr(
        identity.subprocess,
        "run",
        _git_run(status=" M tools/rq1c_qualification_guardrails.py\n"),
    )

    with pytest.raises(RuntimeError, match="clean tracked checkout"):
        identity.exact_checkout_git_sha(Path("."))


def test_exact_checkout_sha_ignores_untracked_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_SHA", HEAD)
    monkeypatch.setattr(identity.subprocess, "run", _git_run(status=""))

    assert identity.exact_checkout_git_sha(Path(".")) == HEAD


def test_exact_checkout_sha_fails_closed_when_git_status_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_SHA", HEAD)

    def fake_run(command, *args, **kwargs):
        if command == ["git", "rev-parse", "HEAD"]:
            return _completed(HEAD + "\n")
        if command == ["git", "status", "--porcelain=v1", "--untracked-files=no"]:
            raise subprocess.CalledProcessError(1, command)
        raise AssertionError(f"unexpected git command: {command!r}")

    monkeypatch.setattr(identity.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="readable git checkout"):
        identity.exact_checkout_git_sha(Path("."))
