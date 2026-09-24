"""§143-B paired-harness regressions.

These tests lock the harness contract *before* any 30-pair data is produced:

* the default side must be the REAL production read path (the shared
  ``run_single_read_measurement`` entry), never a hand-rolled native->wigolo
  chain;
* the rubric matcher is whitespace-normalized and shared by both sides;
* ``useful`` is a symmetric, rubric-derived task verdict (not the reader's own
  ``usable_content``);
* the §143.38 gain bands stay reachable and mechanical;
* §143.49 + the runtime-origin invariant are machine-checked.

No crawl4ai bridge is needed here; the default-only smoke integration test
drives the fixture server and the production measurement entry.
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS = REPO_ROOT / "tools" / "run_f2_paired.py"
FIXTURE = REPO_ROOT / "tools" / "browser_bakeoff_fixture_server.py"

sys.path.insert(0, str(REPO_ROOT))

from tools.run_f2_paired import (  # noqa: E402
    _classify,
    _norm,
    _smoke_verdict,
    _task_useful,
    _units,
)


def _source() -> str:
    return HARNESS.read_text(encoding="utf-8")


# --------------------------------------------------------- structural guards

def test_default_side_uses_the_production_measurement_entry() -> None:
    src = _source()
    assert "run_single_read_measurement(" in src
    # a re-implemented chain would recreate a "fake default"
    assert "run_chain(" not in src
    assert "NativeHttpBackendExecutor(" not in src
    assert "WigoloHttpBackendExecutor(" not in src
    assert "escalate_read(" not in src
    # no arbitrary read function may be injected
    assert "gateway_read=" not in src
    assert "def gateway_read" not in src


def test_specialist_side_uses_the_existing_executor() -> None:
    src = _source()
    assert "Crawl4AIBrowserBackendExecutor(" in src


# ------------------------------------------------------------- rubric helpers

def test_matcher_normalizes_whitespace_only() -> None:
    assert _norm("  a\n\tb   c ") == "a b c"
    assert _units("Release 2026-08-01\nsupported", ["2026-08-01", "supported"]) == [
        "2026-08-01",
        "supported",
    ]
    # case is preserved: a different case does not match
    assert _units("Supported", ["supported"]) == []


def test_task_useful_is_symmetric_rubric_derived() -> None:
    # task usefulness is decided by the shared rubric, not reader adequacy
    assert _task_useful(3) is True
    assert _task_useful(1) is True
    assert _task_useful(0) is False


# ------------------------------------------------------------------- gain bands

def _pair(d_units, c_units, *, d_wall=100.0, c_wall=200.0):
    expected = ["u1", "u2", "u3", "u4"]
    return {
        "expected_critical_units": expected,
        "default": {
            "unit_set": d_units,
            "useful": _task_useful(len(d_units)),
            "wall_ms": d_wall,
            "backend_path": ["native_http"],
        },
        "crawl4ai": {
            "unit_set": c_units,
            "useful": _task_useful(len(c_units)),
            "wall_ms": c_wall,
        },
    }


def test_gain_bands_are_mechanical_and_reachable() -> None:
    essential = _classify([_pair([], ["u1"])])
    assert essential["classification_status"] == "RESOLVED"
    assert essential["specialist_gain"] == "ESSENTIAL"

    material = _classify([_pair(["u1", "u2", "u3"], ["u1", "u2", "u3", "u4"])])
    assert material["specialist_gain"] == "MATERIAL"

    none = _classify([_pair(["u1", "u2", "u3", "u4"], ["u1", "u2", "u3", "u4"])])
    assert none["specialist_gain"] == "NONE"

    unresolved = _classify([_pair([], [])])
    assert unresolved["classification_status"] == "UNRESOLVED_FOR_TASK"
    assert unresolved["specialist_gain"] is None


def test_gain_bands_flag_instability_instead_of_averaging() -> None:
    stable = _pair(["u1"], ["u1"])
    drifted = _pair([], ["u1"])
    result = _classify([stable, drifted])
    assert result["classification_status"] == "UNSTABLE_OUTCOME"
    assert result["specialist_gain"] is None


# ------------------------------------------------------------ smoke verdict

def _row(default_units, crawl4ai_units, *, d_wall=10.0, c_wall=20.0):
    return {
        "default": {
            "unit_set": default_units,
            "wall_ms": d_wall,
            "runtime_origin": {},
        },
        "crawl4ai": {
            "unit_set": crawl4ai_units,
            "wall_ms": c_wall,
        },
        "_invariants": {
            "default_used_real_run_chain": True,
            "default_backend_path_present": True,
            "default_from_shared_measurement_entry": True,
            "default_backend_path_in_active_chain": True,
            "crawl4ai_used_existing_executor": True,
            "same_expected_units_on_both_sides": True,
            "harness_added_fetches": 0,
            "harness_followed_links_itself": False,
            "default_unit_set": default_units,
            "crawl4ai_unit_set": crawl4ai_units,
            "default_wall_ms_positive": d_wall > 0,
            "crawl4ai_wall_ms_positive": c_wall > 0,
        },
    }


def test_smoke_verdict_passes_on_plumbing_row() -> None:
    verdict = _smoke_verdict(_row(["u1"], []))
    assert verdict["passed"] is True
    # an empty unit set is a *result*, not a plumbing failure
    assert verdict["checks"]["default_unit_set_present"] is True
    assert verdict["checks"]["crawl4ai_unit_set_present"] is True


def test_smoke_verdict_fails_when_specialist_never_ran() -> None:
    verdict = _smoke_verdict(_row(["u1"], [], c_wall=0.0))
    assert verdict["passed"] is False
    assert verdict["checks"]["crawl4ai_wall_ms_positive"] is False


# --------------------------------------------- default-only smoke (integration)

@pytest.fixture()
def fixture_base():
    port = 8799
    server = subprocess.Popen(
        [sys.executable, "-u", "-X", "utf8", str(FIXTURE), "--port", str(port)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    ready = False
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base}/structured-spec.html", timeout=2).read(16)
            ready = True
            break
        except Exception:
            time.sleep(0.3)
    if not ready:
        server.terminate()
        pytest.skip("fixture server did not become ready")
    try:
        yield base
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()


def test_default_smoke_is_production_origin_and_recovers_units(fixture_base) -> None:
    from tools.run_f2_paired import (
        CATEGORIES,
        _allow_local_fixture_reads,
        _run_default,
        _units,
    )

    _allow_local_fixture_reads()
    spec = CATEGORIES[0]
    row = _run_default(f"{fixture_base}{spec['fixture']}", spec["category"])

    assert row["runtime_origin"] == {
        "entry": "run_single_read_measurement",
        "backend_path_in_active_chain": True,
        "steps_are_chain_step_results": True,
    }
    assert row["backend_path"] == ["native_http"]
    assert row["wall_ms"] > 0
    recovered = _units(row["content"], spec["critical_units"])
    assert recovered == spec["critical_units"]
