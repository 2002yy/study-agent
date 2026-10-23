"""Resolve which integration range a main push actually represents.

A main push that carries one merge commit diffs only against its immediate parent. A batch
of five merges therefore lands as five pushes, and each run classifies one slice. Because
the concurrency group cancels superseded runs, the only surviving run verifies the *last*
slice and then stands in for the batch - which is how a batch of frontend interaction
changes can be reported green while the browser gates never ran.

The fix is not "diff from some older fixed commit". It is to resolve a *trusted batch
start* and prove the range:

    start must be a real commit
    start must be an ancestor of head
    start must not be head itself

When all three hold, ``start..head`` is a superset of the single-push diff and is safe to
classify. When they cannot be proven, this falls back to the ordinary single-push range -
never to "the last slice is good enough". When even that fallback is unusable the caller
must widen to the full scope.

The decision is a pure function so it can be tested without git or a runner; the git calls
live in the CLI wrapper only.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess

GIT = shutil.which("git") or "git"

VERIFIED = "verified"
SINGLE = "single"
WIDEN = "widen"


def resolve(
    candidate: str | None,
    head: str | None,
    *,
    candidate_is_commit: bool,
    candidate_is_ancestor: bool,
    fallback: str | None = None,
    fallback_is_commit: bool = False,
    fallback_is_ancestor: bool = False,
) -> tuple[str, str | None, str]:
    """Return ``(mode, start, reason)``.

    ``verified``  a proven batch start; classify ``start..head``
    ``single``    the ordinary incremental range; classify ``start..head`` too
    ``widen``     nothing usable; the caller must widen to the full scope
    """

    head = (head or "").strip()
    candidate = (candidate or "").strip()
    fallback = (fallback or "").strip()

    if not head:
        return WIDEN, None, "no-head"

    if candidate and candidate != head:
        if not candidate_is_commit:
            reason = "batch-start-not-a-commit"
        elif not candidate_is_ancestor:
            reason = "batch-start-not-ancestor"
        else:
            return VERIFIED, candidate, "ok"
    elif candidate and candidate == head:
        reason = "batch-start-is-head"
    else:
        reason = "no-batch-start"

    if fallback and fallback != head and fallback_is_commit and fallback_is_ancestor:
        return SINGLE, fallback, f"{reason};incremental"

    return WIDEN, None, f"{reason};no-incremental-range"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([GIT, *args], capture_output=True, text=True, encoding="utf-8")


def _is_commit(rev: str) -> bool:
    return bool(rev) and _git("cat-file", "-e", f"{rev}^{{commit}}").returncode == 0


def _is_ancestor(rev: str, head: str) -> bool:
    if not rev:
        return False
    return _git("merge-base", "--is-ancestor", rev, head).returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve the integration range a main push should be classified over"
    )
    parser.add_argument("--candidate", default="", help="trusted batch start, e.g. last green main head")
    parser.add_argument("--head", default="HEAD", help="the pushed commit")
    parser.add_argument("--fallback", default="", help="ordinary single-push base")
    args = parser.parse_args(argv)

    head = _git("rev-parse", args.head).stdout.strip()
    if not head:
        print(f"batch_mode={WIDEN}")
        print("batch_from=")
        print("batch_reason=unreadable-head")
        return 3

    candidate = _git("rev-parse", args.candidate).stdout.strip() if args.candidate else ""
    fallback = _git("rev-parse", args.fallback).stdout.strip() if args.fallback else ""

    mode, start, reason = resolve(
        candidate,
        head,
        candidate_is_commit=_is_commit(candidate),
        candidate_is_ancestor=_is_ancestor(candidate, head),
        fallback=fallback,
        fallback_is_commit=_is_commit(fallback),
        fallback_is_ancestor=_is_ancestor(fallback, head),
    )
    print(f"batch_mode={mode}")
    print(f"batch_from={start or ''}")
    print(f"batch_reason={reason}")
    # A non-zero exit on ``widen`` lets the workflow take the conservative branch without
    # parsing prose, while still printing the machine-stable keys above.
    return 0 if mode != WIDEN else 3


if __name__ == "__main__":
    raise SystemExit(main())
