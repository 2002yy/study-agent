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


def stop_tree(process: subprocess.Popen[bytes]) -> bool:
    complete = True
    try:
        if sys.platform == "win32":
            if process.poll() is None:
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
        try:
            with stdout.open("xb") as output, stderr.open("xb") as errors:
                process = subprocess.Popen(
                    command,
                    cwd=root,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=errors,
                    start_new_session=os.name != "nt",
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    if os.name == "nt"
                    else 0,
                )
                try:
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
                        cleanup = stop_tree(process)
                child_code = process.poll()
            if stdout.stat().st_size + stderr.stat().st_size > log_limit and not reason:
                reason = "log_budget"
            if time.monotonic() > deadline and not reason:
                reason = "timeout"
        except OSError:
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
