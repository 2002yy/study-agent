from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "research_quality"
    / "rq1c_bounded_holdout_manifest.json"
)
_STALE_SHA = "0" * 40
_GIT_MISMATCH = "GITHUB_SHA does not match the checked-out RQ1-C qualification HEAD"
_DIRTY_CHECKOUT = "RQ1-C qualification requires a clean tracked checkout at the exact HEAD"


def _stale_sha_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GITHUB_SHA"] = _STALE_SHA
    return env


def _with_repo_pythonpath(env: dict[str, str]) -> dict[str, str]:
    """Make a script-file subprocess able to import ``src`` anywhere.

    Running ``tools/<script>.py`` puts ``tools/`` on ``sys.path``, not the repo
    root, so the guard tests only worked where PYTHONPATH was already set (CI
    sets ``PYTHONPATH=.``). Without it they failed locally with
    ``ModuleNotFoundError: No module named 'src'`` instead of the guard message.
    """

    parts = [part for part in env.get("PYTHONPATH", "").split(os.pathsep) if part]
    if str(REPO_ROOT) not in parts:
        parts.insert(0, str(REPO_ROOT))
    updated = dict(env)
    updated["PYTHONPATH"] = os.pathsep.join(parts)
    return updated


def _run_imported_call(
    *,
    module_name: str,
    call_source: str,
    args: list[str],
    cwd: Path = REPO_ROOT,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    code = (
        "import importlib, sys\n"
        "from pathlib import Path\n"
        "target = importlib.import_module(sys.argv[1])\n"
        f"{call_source}\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code, module_name, *args],
        cwd=cwd,
        env=env if env is not None else _stale_sha_env(),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def _dirty_local_clone(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A dirty *tracked* checkout, cheaply and deterministically.

    The tool under test derives its repo root from ``__file__``, so it must be
    imported from a real checkout: cwd/PYTHONPATH pointing at the pristine repo
    would make the guard read the clean repo instead.

    Hardening (load-dependent flake): the production guard budgets 5s per git
    command and, correctly, reports "readable git checkout" if one exceeds it.
    A cold full clone's first ``git status`` could exceed that under a loaded
    full-suite run. A shallow clone plus a warm-up status here removes the
    timing sensitivity without touching the guard.
    """

    checkout = tmp_path / "dirty-checkout"
    subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--single-branch",
            "--no-hardlinks",
            str(REPO_ROOT),
            str(checkout),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout.strip()

    dirty_target = checkout / "tools" / "rq1c_qualification_guardrails.py"
    dirty_target.write_text(
        dirty_target.read_text(encoding="utf-8") + "\n# dirty-checkout regression\n",
        encoding="utf-8",
    )

    # Warm the clone's git index/status caches and confirm the checkout really is
    # dirty before the guard is asked to judge it.
    warm = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=no"],
        cwd=checkout,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert warm.stdout.strip(), "the cloned checkout must be dirty before the guard runs"

    env = os.environ.copy()
    env["GITHUB_SHA"] = head
    env["PYTHONPATH"] = str(checkout)
    return checkout, env


@pytest.mark.parametrize(
    "script_name",
    [
        "run_rq1c_bounded_qualification_impl.py",
        "run_rq1c_bounded_qualification_core.py",
    ],
)
def test_direct_qualification_internal_execution_cannot_bypass_guard(
    tmp_path: Path,
    script_name: str,
) -> None:
    output = tmp_path / "runtime.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / script_name),
            "--manifest",
            str(MANIFEST),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        env=_stale_sha_env(),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode != 0
    assert _GIT_MISMATCH in completed.stderr
    assert not output.exists()


@pytest.mark.parametrize(
    "module_name",
    [
        "tools.run_rq1c_bounded_qualification_impl",
        "tools.run_rq1c_bounded_qualification_core",
    ],
)
def test_imported_qualification_run_cannot_bypass_exact_head_guard(
    tmp_path: Path,
    module_name: str,
) -> None:
    output = tmp_path / "runtime.json"
    completed = _run_imported_call(
        module_name=module_name,
        call_source=(
            "target.run_qualification("
            "manifest_path=Path(sys.argv[2]), output_path=Path(sys.argv[3]))"
        ),
        args=[str(MANIFEST), str(output)],
    )

    assert completed.returncode != 0
    assert _GIT_MISMATCH in completed.stderr
    assert not output.exists()


@pytest.mark.parametrize(
    "module_name",
    [
        "tools.run_rq1c_bounded_qualification_impl",
        "tools.run_rq1c_bounded_qualification_core",
    ],
)
def test_imported_qualification_case_hook_cannot_bypass_exact_head_guard(
    module_name: str,
) -> None:
    completed = _run_imported_call(
        module_name=module_name,
        call_source=(
            "target._run_case(case={}, repository=None, service=None, "
            "chat_service=None, reference_date='2026-09-05')"
        ),
        args=[],
    )

    assert completed.returncode != 0
    assert _GIT_MISMATCH in completed.stderr


@pytest.mark.parametrize(
    "script_name",
    [
        "run_rq1c_protocol_probes_impl.py",
        "run_rq1c_protocol_probes_core.py",
    ],
)
def test_direct_protocol_internal_execution_cannot_bypass_exact_head_guard(
    tmp_path: Path,
    script_name: str,
) -> None:
    runtime = tmp_path / "runtime.json"
    output = tmp_path / "protocol.json"
    runtime.write_text(
        json.dumps(
            {
                "schema_version": "rq1c-bounded-qualification-runtime-v1",
                "cases": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / script_name),
            "--runtime",
            str(runtime),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        env=_with_repo_pythonpath(_stale_sha_env()),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode != 0
    assert _GIT_MISMATCH in completed.stderr
    assert not output.exists()


@pytest.mark.parametrize(
    "module_name",
    [
        "tools.run_rq1c_protocol_probes_impl",
        "tools.run_rq1c_protocol_probes_core",
    ],
)
def test_imported_protocol_run_cannot_bypass_exact_head_guard(
    tmp_path: Path,
    module_name: str,
) -> None:
    runtime = tmp_path / "runtime.json"
    output = tmp_path / "protocol.json"
    runtime.write_text(
        json.dumps(
            {
                "schema_version": "rq1c-bounded-qualification-runtime-v1",
                "cases": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    completed = _run_imported_call(
        module_name=module_name,
        call_source=(
            "target.run_protocol_probes("
            "runtime_path=Path(sys.argv[2]), output_path=Path(sys.argv[3]))"
        ),
        args=[str(runtime), str(output)],
    )

    assert completed.returncode != 0
    assert _GIT_MISMATCH in completed.stderr
    assert not output.exists()


def test_dirty_tracked_checkout_blocks_imported_internal_artifact_writes(
    tmp_path: Path,
) -> None:
    checkout, env = _dirty_local_clone(tmp_path)
    manifest = (
        checkout
        / "tests"
        / "fixtures"
        / "research_quality"
        / "rq1c_bounded_holdout_manifest.json"
    )

    for module_name in (
        "tools.run_rq1c_bounded_qualification_impl",
        "tools.run_rq1c_bounded_qualification_core",
    ):
        output = tmp_path / f"runtime-{module_name.rsplit('.', 1)[-1]}.json"
        completed = _run_imported_call(
            module_name=module_name,
            call_source=(
                "target.run_qualification("
                "manifest_path=Path(sys.argv[2]), output_path=Path(sys.argv[3]))"
            ),
            args=[str(manifest), str(output)],
            cwd=checkout,
            env=env,
        )
        assert completed.returncode != 0
        assert _DIRTY_CHECKOUT in completed.stderr
        assert not output.exists()

    runtime = tmp_path / "dirty-runtime.json"
    runtime.write_text(
        json.dumps(
            {
                "schema_version": "rq1c-bounded-qualification-runtime-v1",
                "cases": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    for module_name in (
        "tools.run_rq1c_protocol_probes_impl",
        "tools.run_rq1c_protocol_probes_core",
    ):
        output = tmp_path / f"protocol-{module_name.rsplit('.', 1)[-1]}.json"
        completed = _run_imported_call(
            module_name=module_name,
            call_source=(
                "target.run_protocol_probes("
                "runtime_path=Path(sys.argv[2]), output_path=Path(sys.argv[3]))"
            ),
            args=[str(runtime), str(output)],
            cwd=checkout,
            env=env,
        )
        assert completed.returncode != 0
        assert _DIRTY_CHECKOUT in completed.stderr
        assert not output.exists()
