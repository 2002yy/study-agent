"""Bounded subprocess adapter for existing gates, without shell or a new scheduler."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any

from tools.run_stage_gate import load_manifest, resolve


class WindowsJob:
    """Own descendants even after the runner exits; assigned before releasing work."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64),
                ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD),
                ("min_ws", ctypes.c_size_t),
                ("max_ws", ctypes.c_size_t),
                ("active_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits),
                ("io", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        class Accounting(ctypes.Structure):
            _fields_ = [
                ("times", ctypes.c_int64 * 4),
                ("faults", wintypes.DWORD),
                ("total", wintypes.DWORD),
                ("active", wintypes.DWORD),
                ("terminated", wintypes.DWORD),
            ]

        self.ctypes, self.accounting = ctypes, Accounting
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.kernel.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("Cannot create process job")
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            self.close()
            raise OSError("Cannot configure process job")

    def assign(self, pid: int) -> None:
        handle = self.kernel.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE
        if not handle:
            raise OSError("Cannot open owned process")
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, handle):
                raise OSError("Cannot assign owned process")
        finally:
            self.kernel.CloseHandle(handle)

    def empty(self) -> bool:
        info = self.accounting()
        if not self.kernel.QueryInformationJobObject(
            self.handle, 1, self.ctypes.byref(info), self.ctypes.sizeof(info), None
        ):
            return False
        return info.active == 0

    def terminate(self) -> bool:
        if not self.kernel.TerminateJobObject(self.handle, 1):
            return False
        until = time.monotonic() + 5
        while not self.empty():
            if time.monotonic() >= until:
                return False
            time.sleep(0.01)
        return True

    def close(self) -> None:
        self.kernel.CloseHandle(self.handle)


def commands_for(root: Path, level: str, impact: str, stage: str) -> list[list[str]]:
    if level == "L3":
        if impact or stage:
            raise ValueError("L3 cannot accept a narrower selector")
        return [
            [sys.executable, str(root / "tools/l3_preflight.py")],
            [sys.executable, "-m", "pytest", "tests", "-q"],
        ]
    if (
        level not in {"L1", "L2"}
        or (level == "L1" and (not impact or stage))
        or (level == "L2" and (not stage or impact))
    ):
        raise ValueError("one matching level and registered selector required")
    paths = resolve(
        load_manifest(root / "tests/stage_gates.json"), impact_set=impact, stage=stage
    )
    if not paths:
        raise ValueError("empty gate")
    for value in paths:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not value.startswith("tests/")
            or not (root / value).is_file()
            or not (root / value).resolve().is_relative_to(root.resolve())
        ):
            raise ValueError("unsafe gate path")
    flag, name = ("--impact-set", impact) if level == "L1" else ("--stage", stage)
    return [[sys.executable, str(root / "tools/run_stage_gate.py"), flag, name, "-q"]]


def isolated_environment(profile: Path, root: Path) -> dict[str, str]:
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "CI",
        "GITHUB_SHA",
    }
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(
        HOME=str(profile),
        USERPROFILE=str(profile),
        APPDATA=str(profile),
        LOCALAPPDATA=str(profile),
        PYTHONPATH=str(root),
        PYTHONNOUSERSITE="1",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    return env


def stop_tree(process: subprocess.Popen[bytes], job: WindowsJob | None = None) -> bool:
    complete = True
    try:
        if sys.platform == "win32":
            if job is not None:
                complete = job.terminate()
            elif process.poll() is None:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        timeout=5,
                        stdin=subprocess.DEVNULL,
                        check=True,
                    )
                except (
                    OSError,
                    subprocess.TimeoutExpired,
                    subprocess.CalledProcessError,
                ):
                    complete = False
            else:
                complete = False  # PID ancestry cannot be confirmed after parent exit.
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        return complete
    except (OSError, subprocess.TimeoutExpired):
        return False


def execute(
    root: Path, commands: list[list[str]], timeout: float, log_limit: int = 1_048_576
) -> dict[str, Any]:
    logs = Path(tempfile.mkdtemp(prefix="studyctl-run-"))
    profile = logs / "profile"
    profile.mkdir()
    env = isolated_environment(profile, root)
    deadline = time.monotonic() + timeout
    rows: list[dict[str, Any]] = []
    artifacts: list[str] = []
    verdict: dict[str, Any] = {"status": "PASS", "exit_code": 0, "errors": []}
    for index, command in enumerate(commands):
        if time.monotonic() >= deadline:
            rows.append(
                {
                    "argv": command,
                    "child_exit_code": None,
                    "stop_reason": "timeout",
                    "cleanup_complete": True,
                }
            )
            verdict.update(
                status="BLOCKED",
                exit_code=5,
                errors=[
                    {
                        "code": "timeout",
                        "message": "Execution deadline exhausted before starting the next step.",
                    }
                ],
            )
            break
        stdout, stderr = logs / f"{index}.stdout.log", logs / f"{index}.stderr.log"
        artifacts.extend([str(stdout), str(stderr)])
        reason = ""
        child_code: int | None = None
        cleanup = True
        cleaned = False
        job: WindowsJob | None = None
        try:
            if sys.platform == "win32":
                job = WindowsJob()
            with stdout.open("xb") as output, stderr.open("xb") as errors:
                # The bootstrap waits on a private pipe until it belongs to the
                # job. No user command or descendant can escape the assignment race.
                launch = (
                    [
                        sys.executable,
                        "-c",
                        "import subprocess,sys; token=sys.stdin.buffer.read(1); sys.exit(subprocess.call(sys.argv[1:],stdin=subprocess.DEVNULL) if token==b'1' else 3)",
                        *command,
                    ]
                    if job
                    else command
                )
                process = subprocess.Popen(
                    launch,
                    cwd=root,
                    env=env,
                    stdin=subprocess.PIPE if job else subprocess.DEVNULL,
                    stdout=output,
                    stderr=errors,
                    start_new_session=os.name != "nt",
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    if os.name == "nt"
                    else 0,
                )
                try:
                    if job is not None:
                        job.assign(process.pid)
                        assert process.stdin is not None
                        process.stdin.write(b"1")
                        process.stdin.close()
                    while process.poll() is None:
                        if stdout.stat().st_size + stderr.stat().st_size > log_limit:
                            reason = "log_budget"
                            break
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            reason = "timeout"
                            break
                        try:
                            process.wait(timeout=min(0.05, remaining))
                        except subprocess.TimeoutExpired:
                            pass
                except KeyboardInterrupt:
                    reason = "cancelled"
                except OSError:
                    reason = "execution_unavailable"
                finally:
                    if reason:
                        cleanup = stop_tree(process, job)
                        cleaned = True
                child_code = process.poll()
            if stdout.stat().st_size + stderr.stat().st_size > log_limit and not reason:
                reason = "log_budget"
            if time.monotonic() > deadline and not reason:
                reason = "timeout"
            if reason in {"timeout", "log_budget"} and not cleaned:
                cleanup = stop_tree(process, job) and cleanup
        except OSError:
            reason = "execution_unavailable"
        finally:
            if job is not None:
                try:
                    if not job.empty():
                        cleanup = job.terminate() and cleanup
                finally:
                    job.close()
            if not cleanup and not reason:
                reason = "execution_unavailable"
        remaining_bytes = log_limit
        for path in (stdout, stderr):
            if path.exists():
                with path.open("rb") as log:
                    chunk = log.read(remaining_bytes)
                remaining_bytes -= len(chunk)
                sys.stderr.write(chunk.decode("utf-8", errors="replace"))
        rows.append(
            {
                "argv": command,
                "child_exit_code": child_code,
                "stop_reason": reason,
                "cleanup_complete": cleanup,
            }
        )
        if reason:
            code = 3 if reason == "execution_unavailable" else 5
            verdict.update(
                status="BLOCKED",
                exit_code=code,
                errors=[
                    {
                        "code": reason,
                        "message": "Gate execution did not complete; inspect local logs.",
                    }
                ],
            )
            break
        if child_code != 0:
            code = 3 if len(commands) > 1 and index == 0 else 4
            verdict.update(
                status="BLOCKED" if code == 3 else "FAIL",
                exit_code=code,
                errors=[
                    {
                        "code": "preflight_failed" if code == 3 else "gate_failed",
                        "message": "The existing gate returned a failure.",
                    }
                ],
            )
            break
    verdict.update(
        steps=rows,
        artifacts=artifacts,
        log_directory=str(logs),
        environment_policy="allowlisted and isolated; no provider credentials",
    )
    return verdict
