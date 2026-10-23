"""Batch-baseline resolution must never let the last slice stand in for the batch.

G1-B exists because a main push that carries one merge commit diffs against its immediate
parent. Five merges become five pushes; the concurrency group cancels the first four; the
surviving run sees ``files: 1`` and is nevertheless treated as the integration verdict for
the whole batch.
"""

from __future__ import annotations

import subprocess

import pytest

from tools.ci_batch_range import SINGLE, VERIFIED, WIDEN, main, resolve


def _git(cwd, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


def _commit(repo, name: str, content: str, message: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture()
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "ci@example.invalid")
    _git(tmp_path, "config", "user.name", "ci")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    return tmp_path


# --- pure decision table -------------------------------------------------------------


def test_a_proven_ancestor_becomes_the_verified_batch_start():
    assert resolve(
        "aaa", "bbb", candidate_is_commit=True, candidate_is_ancestor=True
    ) == (VERIFIED, "aaa", "ok")


def test_a_candidate_that_is_the_head_falls_back_to_incremental():
    mode, start, reason = resolve(
        "bbb",
        "bbb",
        candidate_is_commit=True,
        candidate_is_ancestor=True,
        fallback="aaa",
        fallback_is_commit=True,
        fallback_is_ancestor=True,
    )
    assert (mode, start) == (SINGLE, "aaa")
    assert "batch-start-is-head" in reason


def test_a_non_ancestor_candidate_is_never_used():
    mode, start, _ = resolve(
        "ccc",
        "bbb",
        candidate_is_commit=True,
        candidate_is_ancestor=False,
        fallback="aaa",
        fallback_is_commit=True,
        fallback_is_ancestor=True,
    )
    assert (mode, start) == (SINGLE, "aaa")


def test_a_missing_commit_object_is_never_used():
    mode, _, _ = resolve(
        "ccc", "bbb", candidate_is_commit=False, candidate_is_ancestor=True
    )
    assert mode == WIDEN


def test_nothing_provable_widens_instead_of_guessing():
    mode, start, reason = resolve(
        "", "bbb", candidate_is_commit=False, candidate_is_ancestor=False
    )
    assert (mode, start) == (WIDEN, None)
    assert "no-incremental-range" in reason


def test_no_head_widens():
    assert resolve("aaa", "", candidate_is_commit=True, candidate_is_ancestor=True)[0] == WIDEN


# --- against a real repository -------------------------------------------------------


def test_two_consecutive_merges_are_both_inside_the_batch_range(repo, monkeypatch):
    """The #229 -> #281 shape: two merges, and the surviving run must see both files."""
    base = _commit(repo, "base.txt", "base\n", "base")

    _git(repo, "checkout", "-q", "-b", "slice-a")
    _commit(repo, "chat.txt", "chat\n", "slice a")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "slice-a", "-m", "merge slice a")

    _git(repo, "checkout", "-q", "-b", "slice-b")
    _commit(repo, "reader.txt", "reader\n", "slice b")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "slice-b", "-m", "merge slice b")

    head = _git(repo, "rev-parse", "HEAD").strip()
    incremental_base = _git(repo, "rev-parse", "HEAD^1").strip()

    monkeypatch.chdir(repo)
    code = main(["--candidate", base, "--head", head, "--fallback", incremental_base])
    assert code == 0

    batch_files = set(_git(repo, "diff", "--name-only", base, head).split())
    assert batch_files == {"chat.txt", "reader.txt"}

    incremental_files = set(_git(repo, "diff", "--name-only", incremental_base, head).split())
    assert incremental_files == {"reader.txt"}
    # This is the gap G1-B closes: the incremental range alone misses the earlier slice.
    assert incremental_files < batch_files


@pytest.fixture()
def divergent_repo(repo):
    """A repo whose candidate start sits on a branch that never merged into head."""

    _commit(repo, "base.txt", "base\n", "base")
    _git(repo, "checkout", "-q", "-b", "side")
    divergent = _commit(repo, "side.txt", "side\n", "side")
    _git(repo, "checkout", "-q", "main")
    head = _commit(repo, "main.txt", "main\n", "main line")
    return repo, head, divergent


def test_a_divergent_candidate_widens(divergent_repo, monkeypatch):
    working, head, divergent = divergent_repo
    monkeypatch.chdir(working)
    assert main(["--candidate", divergent, "--head", head]) == 3


def test_without_any_usable_base_the_result_widens(repo, monkeypatch):
    head = _commit(repo, "only.txt", "x\n", "only")
    monkeypatch.chdir(repo)
    assert main(["--head", head]) == 3
