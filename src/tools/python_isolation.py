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
import threading
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
        popen: Any = subprocess.Popen,
    ) -> None:
        self.spec = spec
        self.docker = docker
        self._run = runner
        self._popen = popen

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
            process = self._popen(
                self._command(name, timeout),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise IsolationUnavailable(str(exc)) from exc

        # Output is bounded *while reading*: a runaway program can no longer
        # exhaust host memory by printing forever before we truncate.
        limit = self.spec.max_output_bytes
        state = {"truncated": False}
        stdout: list[bytes] = []
        stderr: list[bytes] = []
        readers = [
            threading.Thread(target=_drain, args=(process.stdout, stdout, state, limit), daemon=True),
            threading.Thread(target=_drain, args=(process.stderr, stderr, state, limit), daemon=True),
        ]
        for reader in readers:
            reader.start()
        try:
            process.stdin.write(code.encode("utf-8"))
            process.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass

        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        if timed_out or state["truncated"]:
            self._kill(name)
            try:
                process.kill()
            except OSError:
                pass
        for reader in readers:
            reader.join(timeout=5)

        status = "timeout" if timed_out else (
            "succeeded" if getattr(process, "returncode", 1) == 0 else "failed"
        )
        reason = "execution exceeded the time limit" if timed_out else (
            "output limit exceeded" if state["truncated"] else ""
        )
        return {
            "status": status,
            "exit_code": getattr(process, "returncode", None),
            "stdout": b"".join(stdout).decode("utf-8", "replace"),
            "stderr": b"".join(stderr).decode("utf-8", "replace"),
            "truncated": state["truncated"],
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "reason": reason,
        }

    def _kill(self, name: str) -> None:
        try:
            self._run([self.docker, "rm", "-f", name], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            pass


def _drain(stream: Any, sink: list[bytes], state: dict[str, bool], limit: int) -> None:
    """Read a pipe incrementally, stopping (and flagging) at the byte cap."""

    if stream is None:
        return
    total = 0
    try:
        while total < limit:
            chunk = stream.read(min(4096, limit - total))
            if not chunk:
                break
            sink.append(chunk)
            total += len(chunk)
        else:
            state["truncated"] = True
    except (OSError, ValueError):
        return
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


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
