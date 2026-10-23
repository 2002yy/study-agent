"""Batch-baseline resolution must never let the last slice stand in for the batch.

G1-B exists because a main push that carries one merge commit diffs against its immediate
parent. Five merges become five pushes; the concurrency group cancels the first four; the
surviving run sees ``files: 1`` and is nevertheless treated as the integration verdict for
the whole batch.

The contract has two halves and both are load-bearing:

* a *provable* batch start wins and defines ``start..head``;
* an *unprovable* batch start widens to the full scope. It does not silently degrade to the
  single-push range, because that range is precisely the thing that can hide an
  unaccepted intermediate merge.

The single-push range survives only as an explicitly justified exception: the push range
must be *proven merge-free*, so there is provably no intermediate slice for it to hide.
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


def test_a_proven_batch_start_ignores_the_fallback_entirely():
    """A verified batch range is strictly better than the incremental one."""
    mode, start, _ = resolve(
        "aaa",
        "bbb",
        candidate_is_commit=True,
        candidate_is_ancestor=True,
        fallback="ccc",
        fallback_is_commit=True,
        fallback_is_ancestor=True,
        fallback_range_merge_free=True,
    )
    assert (mode, start) == (VERIFIED, "aaa")


def test_a_candidate_that_is_the_head_widens_unless_the_push_is_proven_merge_free():
    """``candidate == head`` proves nothing about what landed in between."""
    mode, start, reason = resolve(
        "bbb",
        "bbb",
        candidate_is_commit=True,
        candidate_is_ancestor=True,
        fallback="aaa",
        fallback_is_commit=True,
        fallback_is_ancestor=True,
        fallback_range_merge_free=None,
    )
    assert (mode, start) == (WIDEN, None)
    assert "batch-start-is-head" in reason
    assert "unproven" in reason


def test_a_non_ancestor_candidate_with_a_merge_containing_push_widens():
    """The negative control the contract was missing.

    The batch start is junk, but the ordinary push base is perfectly valid. Previously the
    resolver accepted that base and classified one slice; the merge inside the push range is
    exactly the unaccepted intermediate work that must not be skipped.
    """
    mode, start, reason = resolve(
        "ccc",
        "bbb",
        candidate_is_commit=True,
        candidate_is_ancestor=False,
        fallback="aaa",
        fallback_is_commit=True,
        fallback_is_ancestor=True,
        fallback_range_merge_free=False,
    )
    assert (mode, start) == (WIDEN, None)
    assert "batch-start-not-ancestor" in reason
    assert "has-merges" in reason


def test_an_unprovable_batch_start_with_an_unprovable_push_range_widens():
    mode, start, reason = resolve(
        "ccc",
        "bbb",
        candidate_is_commit=False,
        candidate_is_ancestor=False,
        fallback="aaa",
        fallback_is_commit=True,
        fallback_is_ancestor=True,
        fallback_range_merge_free=None,
    )
    assert (mode, start) == (WIDEN, None)
    assert "unproven" in reason


def test_an_unprovable_batch_start_with_a_proven_merge_free_push_stays_incremental():
    """The one justified exception: the push provably introduced no merge of its own."""
    mode, start, reason = resolve(
        "ccc",
        "bbb",
        candidate_is_commit=True,
        candidate_is_ancestor=False,
        fallback="aaa",
        fallback_is_commit=True,
        fallback_is_ancestor=True,
        fallback_range_merge_free=True,
    )
    assert (mode, start) == (SINGLE, "aaa")
    assert "incremental-merge-free" in reason


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


@pytest.fixture()
def two_merge_repo(repo):
    """The #229 -> #281 shape: two merges, each landing as its own push."""
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
    return repo, base, head, incremental_base


def test_two_consecutive_merges_are_both_inside_the_batch_range(two_merge_repo, monkeypatch):
    """The surviving run must see both files, not just the last slice."""
    repo, base, head, incremental_base = two_merge_repo

    monkeypatch.chdir(repo)
    code = main(["--candidate", base, "--head", head, "--fallback", incremental_base])
    assert code == 0

    batch_files = set(_git(repo, "diff", "--name-only", base, head).split())
    assert batch_files == {"chat.txt", "reader.txt"}

    incremental_files = set(_git(repo, "diff", "--name-only", incremental_base, head).split())
    assert incremental_files == {"reader.txt"}
    # This is the gap G1-B closes: the incremental range alone misses the earlier slice.
    assert incremental_files < batch_files


def test_invalid_batch_start_with_a_valid_push_base_still_widens(two_merge_repo, monkeypatch):
    """Negative control against the real CLI.

    ``--candidate`` is a commit that exists but never merged into head, and ``--fallback`` is
    the perfectly valid single-push base whose range *does* contain a merge. The resolver must
    refuse to classify that slice and widen instead.
    """
    repo, _base, head, incremental_base = two_merge_repo
    _git(repo, "checkout", "-q", "-b", "never-merged", head)
    divergent = _commit(repo, "divergent.txt", "x\n", "divergent")
    _git(repo, "checkout", "-q", "main")

    monkeypatch.chdir(repo)
    assert main(["--candidate", divergent, "--head", head, "--fallback", incremental_base]) == 3


def test_invalid_batch_start_with_a_merge_free_push_base_stays_incremental(repo, monkeypatch):
    """Positive control: the exception still works when it is actually provable."""
    base = _commit(repo, "base.txt", "base\n", "base")
    _git(repo, "checkout", "-q", "-b", "side")
    divergent = _commit(repo, "side.txt", "side\n", "side")
    _git(repo, "checkout", "-q", "main")
    head = _commit(repo, "only.txt", "x\n", "only")

    monkeypatch.chdir(repo)
    assert main(["--candidate", divergent, "--head", head, "--fallback", base]) == 0
    assert set(_git(repo, "diff", "--name-only", base, head).split()) == {"only.txt"}


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
