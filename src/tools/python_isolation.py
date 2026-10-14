"""OS-level isolation for untrusted Python computation.

A plain ``subprocess`` with a timeout and an AST check is **not** a security
sandbox, and on Windows a child Python process cannot reliably be stopped from
reading host files or opening sockets.  Untrusted model/agent code therefore
only ever runs inside a hardened, network-less Linux container.

Fail-closed contract: when the isolation runtime is unavailable (no daemon, no
image, unsupported host) this module reports the tool as unavailable and never
falls back to executing arbitrary Python on the host.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

DEFAULT_IMAGE = "python:3.12-slim"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MEMORY_MB = 256
DEFAULT_CPUS = 1.0
DEFAULT_PIDS_LIMIT = 64
DEFAULT_TMPFS_MB = 32
DEFAULT_MAX_OUTPUT_BYTES = 20_000


class IsolationUnavailable(RuntimeError):
    """Raised when untrusted code cannot be run in a real isolated runtime."""


@dataclass(frozen=True)
class IsolationSpec:
    image: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    memory_mb: int = DEFAULT_MEMORY_MB
    cpus: float = DEFAULT_CPUS
    pids_limit: int = DEFAULT_PIDS_LIMIT
    tmpfs_mb: int = DEFAULT_TMPFS_MB
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES


class IsolatedPythonRunner(Protocol):
    def available(self) -> bool: ...

    def run(self, code: str, *, timeout_seconds: float | None = None) -> dict[str, Any]: ...


class NullRunner:
    """Default fail-closed runner used when no isolation runtime is configured."""

    def __init__(self, reason: str = "Isolated Python runtime is not configured") -> None:
        self.reason = reason

    def available(self) -> bool:
        return False

    def run(self, code: str, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        raise IsolationUnavailable(self.reason)


class DockerPythonRunner:
    """Runs untrusted code in a hardened, network-less, read-only Linux container."""

    def __init__(
        self,
        spec: IsolationSpec,
        *,
        docker: str = "docker",
        runner: Any = subprocess.run,
    ) -> None:
        self.spec = spec
        self.docker = docker
        self._run = runner

    def available(self) -> bool:
        if shutil.which(self.docker) is None:
            return False
        try:
            probe = self._run(
                [self.docker, "image", "inspect", self.spec.image],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return getattr(probe, "returncode", 1) == 0

    def _command(self, name: str, timeout_seconds: float) -> list[str]:
        spec = self.spec
        return [
            self.docker, "run", "--rm", "--name", name,
            "--network", "none",
            "--read-only",
            "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size={spec.tmpfs_mb}m",
            "--memory", f"{spec.memory_mb}m", "--memory-swap", f"{spec.memory_mb}m",
            "--cpus", str(spec.cpus),
            "--pids-limit", str(spec.pids_limit),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", "65534:65534",
            "--ulimit", "nofile=64:64",
            "-i",
            spec.image, "python", "-I", "-S", "-",
        ]

    def run(self, code: str, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code is required")
        timeout = float(timeout_seconds or self.spec.timeout_seconds)
        name = f"study-agent-py-{uuid.uuid4().hex[:12]}"
        started = time.perf_counter()
        try:
            completed = self._run(
                self._command(name, timeout),
                input=code,
                capture_output=True,
                text=True,
                timeout=timeout + 5,
            )
        except subprocess.TimeoutExpired:
            self._kill(name)
            return self._result("timeout", "", "", None, started,
                                reason="execution exceeded the time limit")
        except OSError as exc:
            raise IsolationUnavailable(str(exc)) from exc
        return self._result(
            "succeeded" if completed.returncode == 0 else "failed",
            completed.stdout or "",
            completed.stderr or "",
            completed.returncode,
            started,
        )

    def _kill(self, name: str) -> None:
        try:
            self._run([self.docker, "rm", "-f", name], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            pass

    def _result(
        self,
        status: str,
        stdout: str,
        stderr: str,
        exit_code: int | None,
        started: float,
        reason: str = "",
    ) -> dict[str, Any]:
        limit = self.spec.max_output_bytes
        stdout, truncated = _bounded(stdout, limit)
        stderr, _ = _bounded(stderr, limit)
        return {
            "status": status,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": truncated,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "reason": reason,
        }


def _bounded(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def get_default_runner(*, docker: str = "docker") -> IsolatedPythonRunner:
    """Build the runner from the environment; absence means fail closed."""

    image = os.getenv("STUDY_AGENT_PYTHON_IMAGE", "").strip()
    if not image:
        return NullRunner("Isolated Python image is not configured (STUDY_AGENT_PYTHON_IMAGE)")
    spec = IsolationSpec(
        image=image,
        timeout_seconds=float(os.getenv("STUDY_AGENT_PYTHON_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)),
        memory_mb=int(os.getenv("STUDY_AGENT_PYTHON_MEMORY_MB", DEFAULT_MEMORY_MB)),
    )
    return DockerPythonRunner(spec, docker=docker)


def isolated_python_available(*, docker: str = "docker") -> bool:
    """True only when a real OS-level isolation runtime is usable.

    Never assume isolation; a missing daemon, image or CLI must disable compute
    grants rather than silently fall back to host execution.
    """

    try:
        return get_default_runner(docker=docker).available()
    except Exception:
        return False
