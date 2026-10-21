"""Gate selection and actual bounded children, with explicit fake environments."""

import ctypes
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from tests.test_studyctl import invoke, repo as repo
from tools import studyctl
from tools import studyctl_execution as execution


@pytest.fixture
def registered(repo):
    (repo / "tests/test_studyctl.py").write_text("# no execution\n", encoding="utf-8")
    (repo / "tests/stage_gates.json").write_text(
        json.dumps(
            {
                "schema_version": "staged-regression-policy-v1",
                "impact_sets": {"unit": ["tests/test_studyctl.py"], "empty": []},
                "stage_gates": {"integration": ["tests/test_studyctl.py"]},
            }
        ),
        encoding="utf-8",
    )
    return repo


@pytest.mark.parametrize(
    "level,impact,stage,flag",
    [
        ("L1", "unit", "", "--impact-set"),
        ("L2", "", "integration", "--stage"),
    ],
)
def test_reuses_registered_runner_without_shell(registered, level, impact, stage, flag):
    commands = execution.commands_for(registered, level, impact, stage)
    assert commands[0][1] == str(registered / "tools/run_stage_gate.py")
    assert commands[0][2] == flag and commands[0][-1] == "-q"


@pytest.mark.parametrize(
    "level,impact,stage",
    [
        ("L1", "", ""),
        ("L1", "unit", "integration"),
        ("L2", "unit", ""),
        ("L1", "empty", ""),
        ("L3", "unit", ""),
        ("other", "unit", ""),
    ],
)
def test_invalid_or_empty_selectors_never_run(registered, level, impact, stage):
    with pytest.raises((ValueError, SystemExit)):
        execution.commands_for(registered, level, impact, stage)


def test_explicit_l3_has_preflight_before_full_suite(registered):
    commands = execution.commands_for(registered, "L3", "", "")
    assert commands[0] == [sys.executable, str(registered / "tools/l3_preflight.py")]
    assert commands[1][1:] == ["-m", "pytest", "tests", "-q"]


def test_dry_run_does_not_execute_or_create_logs(registered, capsys, monkeypatch):
    monkeypatch.setattr(studyctl, "ROOT", registered)
    monkeypatch.setattr(
        execution, "execute", lambda *args: pytest.fail("dry run executed")
    )
    result = invoke(
        capsys,
        "test",
        "run",
        "--repo",
        str(registered),
        "--impact-set",
        "unit",
        "--dry-run",
    )
    assert result["status"] == "PASS" and result["data"]["execution"] == "not_started"
    assert result["artifacts"] == []


def test_arbitrary_repository_cannot_supply_executable_tools(registered, capsys):
    result = invoke(
        capsys, "test", "run", "--repo", str(registered), "--impact-set", "unit"
    )
    assert (
        result["exit_code"] == 3
        and result["errors"][0]["code"] == "execution_repo_mismatch"
    )


def test_existing_output_blocks_before_test_execution(registered, capsys, monkeypatch):
    monkeypatch.setattr(studyctl, "ROOT", registered)
    monkeypatch.setattr(
        execution, "execute", lambda *args: pytest.fail("existing output started tests")
    )
    output = registered / "existing.json"
    output.write_text("keep", encoding="utf-8")
    result = invoke(
        capsys,
        "test",
        "run",
        "--repo",
        str(registered),
        "--impact-set",
        "unit",
        "--output",
        str(output),
    )
    assert result["exit_code"] == 3 and output.read_text() == "keep"


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--level", "L2", "--impact-set", "unit"],
        ["--level", "L3", "--stage", "integration"],
    ],
)
def test_level_selector_mismatch_is_argument_error(
    registered, capsys, monkeypatch, args
):
    monkeypatch.setattr(studyctl, "ROOT", registered)
    result = invoke(capsys, "test", "run", "--repo", str(registered), *args)
    assert (
        result["exit_code"] == 2 and result["errors"][0]["code"] == "invalid_selector"
    )


def test_ambient_dotenv_blocks_before_start(registered, capsys, monkeypatch):
    monkeypatch.setattr(studyctl, "ROOT", registered)
    monkeypatch.setattr(
        execution, "execute", lambda *args: pytest.fail("dotenv run executed")
    )
    (registered / ".env").write_text(
        "DEEPSEEK_API_KEY=fake-never-read", encoding="utf-8"
    )
    result = invoke(
        capsys, "test", "run", "--repo", str(registered), "--impact-set", "unit"
    )
    assert result["exit_code"] == 3 and result["errors"][0]["code"] == "ambient_dotenv"
    assert "fake-never-read" not in json.dumps(result)


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf", "3601"])
def test_bad_deadline_is_argument_error(registered, capsys, monkeypatch, timeout):
    monkeypatch.setattr(studyctl, "ROOT", registered)
    result = invoke(
        capsys,
        "test",
        "run",
        "--repo",
        str(registered),
        "--impact-set",
        "unit",
        "--timeout",
        timeout,
    )
    assert result["exit_code"] == 2


def child(code):
    return [sys.executable, "-c", code]


def test_real_failure_preserves_exit_code_and_logs_on_stderr(tmp_path, capsys):
    result = execution.execute(
        tmp_path, [child("print('fixture-log'); raise SystemExit(7)")], 10
    )
    captured = capsys.readouterr()
    assert captured.out == "" and "fixture-log" in captured.err
    assert result["status"] == "FAIL" and result["exit_code"] == 4
    assert result["steps"][0]["child_exit_code"] == 7
    assert all(Path(path).is_file() for path in result["artifacts"])


def test_failed_preflight_never_starts_full_step(tmp_path):
    sentinel = tmp_path / "should-not-exist"
    result = execution.execute(
        tmp_path,
        [child("raise SystemExit(1)"), child(f"open({str(sentinel)!r}, 'w').close()")],
        10,
    )
    assert result["exit_code"] == 3 and len(result["steps"]) == 1
    assert not sentinel.exists()


def test_exhausted_deadline_does_not_start_any_step(tmp_path):
    result = execution.execute(
        tmp_path, [child("raise RuntimeError('must not start')")], 0
    )
    assert result["exit_code"] == 5 and result["steps"][0]["child_exit_code"] is None


def test_real_timeout_stops_owned_process(tmp_path):
    result = execution.execute(tmp_path, [child("import time; time.sleep(20)")], 0.25)
    assert result["exit_code"] == 5 and result["steps"][0]["stop_reason"] == "timeout"
    assert result["steps"][0]["cleanup_complete"]


def test_interrupt_stops_child_and_returns_cancellation(tmp_path, monkeypatch):
    original = subprocess.Popen.wait
    interrupted = []

    def once(process, *args, **kwargs):
        if not interrupted:
            interrupted.append(True)
            raise KeyboardInterrupt
        return original(process, *args, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "wait", once)
    result = execution.execute(tmp_path, [child("import time; time.sleep(20)")], 10)
    assert result["exit_code"] == 5 and result["steps"][0]["stop_reason"] == "cancelled"
    assert result["steps"][0]["cleanup_complete"]


def test_child_does_not_inherit_provider_keys_or_pytest_options(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-do-not-inherit")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-other-provider")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--invalid-fixture-option")
    result = execution.execute(
        tmp_path,
        [
            child(
                "import os; assert 'DEEPSEEK_API_KEY' not in os.environ; assert 'OPENAI_API_KEY' not in os.environ; assert 'PYTEST_ADDOPTS' not in os.environ; print('isolated')"
            )
        ],
        10,
    )
    assert result["exit_code"] == 0 and "isolated" in capsys.readouterr().err


def test_log_budget_is_not_a_false_success(tmp_path, capsys):
    result = execution.execute(
        tmp_path, [child("print('x' * 10000)")], 10, log_limit=1024
    )
    captured = capsys.readouterr()
    assert (
        result["exit_code"] == 5 and result["steps"][0]["stop_reason"] == "log_budget"
    )
    assert len(captured.err.encode()) <= 1024


def alive(pid):
    if sys.platform == "win32":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        try:
            return kernel.WaitForSingleObject(handle, 1000) == 258
        finally:
            kernel.CloseHandle(handle)
    status = Path(f"/proc/{pid}/stat")
    return status.exists() and status.read_text().split()[2] != "Z"


def wait_stopped(pid, timeout=2, clock=time.monotonic):
    # killpg() sends a signal; delivery and /proc's terminal state are asynchronous.
    # Capture the real clock before the deadline-race test patches monotonic.
    deadline = clock() + timeout
    while alive(pid):
        if clock() >= deadline:
            return False
        time.sleep(0.01)
    return True


def test_cleanup_observation_still_rejects_a_live_process():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        assert not wait_stopped(process.pid, timeout=0.1)
    finally:
        process.kill()
        process.wait(timeout=5)
    assert wait_stopped(process.pid)


def test_timeout_stops_runner_descendant(tmp_path):
    code = "import subprocess,sys,time; child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)']); print(child.pid,flush=True);time.sleep(20)"
    result = execution.execute(tmp_path, [child(code)], 0.75)
    pid = int(Path(result["artifacts"][0]).read_text().strip())
    assert result["exit_code"] == 5 and wait_stopped(pid)


def test_l3_requires_explicit_budget_without_starting_any_child(
    registered, capsys, monkeypatch
):
    monkeypatch.setattr(studyctl, "ROOT", registered)
    monkeypatch.setattr(
        execution, "execute", lambda *args: pytest.fail("L3 started without a budget")
    )
    result = invoke(capsys, "test", "run", "--repo", str(registered), "--level", "L3")
    assert (
        result["exit_code"] == 2
        and result["errors"][0]["code"] == "l3_timeout_required"
    )
    planned = invoke(
        capsys,
        "test",
        "run",
        "--repo",
        str(registered),
        "--level",
        "L3",
        "--timeout",
        "1800",
        "--dry-run",
    )
    assert planned["exit_code"] == 0 and len(planned["data"]["commands"]) == 2


def test_timeout_after_parent_exit_still_cleans_descendant(tmp_path, monkeypatch):
    # Force wait() to time out exactly as the runner exits. The next poll sees
    # completion; only the post-loop deadline detects timeout.
    original_wait = subprocess.Popen.wait
    original_clock = execution.time.monotonic
    expired = []
    original_stop = execution.stop_tree
    stopped = []

    def racing_wait(process, timeout=None):
        if timeout is not None and timeout <= 0.05 and not expired:
            original_wait(process, timeout=5)
            expired.append(True)
            raise subprocess.TimeoutExpired(process.args, timeout)
        return original_wait(process, timeout=timeout)

    def clock():
        return original_clock() + (100 if expired else 0)

    def stop(process, job=None):
        stopped.append(True)
        return original_stop(process, job)

    monkeypatch.setattr(subprocess.Popen, "wait", racing_wait)
    monkeypatch.setattr(execution.time, "monotonic", clock)
    monkeypatch.setattr(execution, "stop_tree", stop)
    code = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); print(p.pid,flush=True)"
    result = execution.execute(tmp_path, [child(code)], 10)
    pid = int(Path(result["artifacts"][0]).read_text().strip())
    try:
        assert (
            result["exit_code"] == 5 and result["steps"][0]["stop_reason"] == "timeout"
        )
        assert stopped and result["steps"][0]["cleanup_complete"]
        assert wait_stopped(pid, clock=original_clock)
    finally:
        if alive(pid):
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"], capture_output=True
                )
            else:
                import os
                import signal

                os.kill(pid, signal.SIGKILL)
