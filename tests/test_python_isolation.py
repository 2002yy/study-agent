"""Isolated Python: hardening, fail-closed, bounds and required negative controls.

The orchestration-level tests use fake processes; they prove command hardening,
read-time output bounding and the fail-closed contract.  The real-container
negative controls are skipped unless an isolation runtime is actually usable,
because a mock can never prove host files, the network or memory are contained.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from src.tools.python_isolation import (
    DockerPythonRunner,
    IsolationSpec,
    IsolationUnavailable,
    NullRunner,
    get_default_runner,
    isolated_python_available,
)


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeDocker:
    """Fake ``subprocess.run`` used for the availability probe and ``rm -f``."""

    def __init__(self, *, inspect_returncode=0):
        self.calls: list[list[str]] = []
        self.inspect_returncode = inspect_returncode

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        if len(cmd) > 1 and cmd[1] == "image":
            return FakeCompleted(self.inspect_returncode)
        return FakeCompleted()

    @property
    def removed(self) -> bool:
        return any(cmd[1:3] == ["rm", "-f"] for cmd in self.calls)


class FakePipe:
    def __init__(self, data: bytes):
        self._data = data

    def read(self, size: int = -1) -> bytes:
        chunk = self._data if size is None or size < 0 else self._data[:size]
        self._data = self._data[len(chunk):]
        return chunk

    def close(self) -> None:
        self._data = b""


class FakeStdin:
    def __init__(self) -> None:
        self.data = b""

    def write(self, payload: bytes) -> None:
        self.data += payload

    def close(self) -> None:
        return None


class FakeProcess:
    def __init__(self, *, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0, hang: bool = False):
        self.stdout = FakePipe(stdout)
        self.stderr = FakePipe(stderr)
        self.stdin = FakeStdin()
        self.returncode = returncode
        self._hang = hang
        self.killed = False

    def wait(self, timeout=None):
        if self._hang:
            raise subprocess.TimeoutExpired("docker", timeout)
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class FakePopen:
    def __init__(self, process: FakeProcess):
        self.process = process
        self.command: list[str] | None = None

    def __call__(self, cmd, **kwargs):
        self.command = list(cmd)
        return self.process


def spec(**overrides) -> IsolationSpec:
    return IsolationSpec(image="python:3.12-slim", **overrides)


def runner_with(*, process: FakeProcess, probe: FakeDocker | None = None, **spec_overrides):
    popen = FakePopen(process)
    return DockerPythonRunner(spec(**spec_overrides), runner=probe or FakeDocker(), popen=popen), popen


def test_run_command_has_no_network_no_host_mounts_and_hard_limits():
    runner, popen = runner_with(process=FakeProcess(stdout=b'{"columns":["a"],"rows":[[1]]}'))
    out = runner.run("print('hi')")
    cmd = popen.command
    assert cmd is not None
    for flag in ("--network", "--read-only", "--cap-drop", "--security-opt", "--pids-limit", "--memory", "--user", "--tmpfs", "--ulimit"):
        assert flag in cmd
    assert cmd[cmd.index("--network") + 1] == "none"
    assert cmd[cmd.index("--cap-drop") + 1] == "ALL"
    assert cmd[cmd.index("--user") + 1] == "65534:65534"
    assert "--volume" not in cmd and "-v" not in cmd  # no host directory is mounted
    assert out["status"] == "succeeded"


def test_timeout_kills_the_whole_container():
    probe = FakeDocker()
    runner, _ = runner_with(process=FakeProcess(hang=True), probe=probe)
    out = runner.run("while True: pass", timeout_seconds=1)
    assert out["status"] == "timeout"
    assert probe.removed


def test_output_is_bounded_while_reading_and_stops_the_unit():
    probe = FakeDocker()
    runner, _ = runner_with(process=FakeProcess(stdout=b"x" * 50_000), probe=probe, max_output_bytes=100)
    out = runner.run("print('x' * 50000)")
    assert out["truncated"] is True
    assert len(out["stdout"]) == 100
    assert probe.removed  # a runaway writer is stopped, not merely truncated afterwards


def test_available_requires_a_working_daemon_and_image(monkeypatch):
    monkeypatch.setattr("src.tools.python_isolation.shutil.which", lambda _: None)
    assert DockerPythonRunner(spec(), runner=FakeDocker()).available() is False
    monkeypatch.setattr("src.tools.python_isolation.shutil.which", lambda _: "docker")
    assert DockerPythonRunner(spec(), runner=FakeDocker(inspect_returncode=1)).available() is False
    assert DockerPythonRunner(spec(), runner=FakeDocker(inspect_returncode=0)).available() is True


def test_missing_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("STUDY_AGENT_PYTHON_IMAGE", raising=False)
    assert isinstance(get_default_runner(), NullRunner)
    assert isolated_python_available() is False
    with pytest.raises(IsolationUnavailable):
        NullRunner().run("print(1)")


# --- required negative controls: only meaningful in a real container --------

requires_isolation = pytest.mark.skipif(
    not isolated_python_available(),
    reason="No usable OS-level isolation runtime (fail-closed path exercised elsewhere)",
)


def _real_run(code: str, **overrides):
    timeout = overrides.pop("timeout_seconds", 10)
    runner = DockerPythonRunner(spec(timeout_seconds=timeout, **overrides))
    return runner.run(code)


@requires_isolation
def test_positive_control_runs_a_real_computation():
    result = _real_run("import json; print(json.dumps({'columns': ['a'], 'rows': [[2]]}))")
    assert result["status"] == "succeeded", result["stderr"]
    assert json.loads(result["stdout"])["rows"] == [[2]]


@requires_isolation
def test_negative_control_cannot_read_host_only_files_or_inherit_host_env(tmp_path, monkeypatch):
    token = "host-secret-2f8c1d"
    marker = tmp_path / "host_secret.txt"
    marker.write_text(token, encoding="utf-8")
    monkeypatch.setenv("STUDY_AGENT_HOST_SECRET", token)
    program = (
        "import os, json\n"
        f"paths = {json.dumps([str(marker)])}\n"
        "files = {}\n"
        "for path in paths:\n"
        "    try:\n"
        "        with open(path) as handle: files[path] = handle.read()\n"
        "    except Exception as exc: files[path] = 'ERR:' + type(exc).__name__\n"
        "print(json.dumps({'env': os.environ.get('STUDY_AGENT_HOST_SECRET'), 'files': files}))\n"
    )
    result = _real_run(program)
    assert result["status"] == "succeeded", result["stderr"]
    payload = json.loads(result["stdout"])
    assert payload["env"] is None                        # host env is not inherited
    assert payload["files"][str(marker)].startswith("ERR:")  # host path is absent
    assert token not in result["stdout"]


@requires_isolation
def test_negative_control_cannot_reach_the_network():
    result = _real_run("import socket; socket.create_connection(('1.1.1.1', 53), 3)")
    assert result["status"] == "failed"


@requires_isolation
def test_negative_control_infinite_loop_is_killed():
    result = _real_run("while True:\n    pass", timeout_seconds=2)
    assert result["status"] == "timeout"


@requires_isolation
def test_negative_control_unbounded_memory_is_bounded():
    result = _real_run("payload = bytearray(2_000_000_000)\nprint(len(payload))", timeout_seconds=20, memory_mb=128)
    assert result["status"] == "failed"


@requires_isolation
def test_negative_control_unbounded_output_is_capped():
    result = _real_run("print('x' * 10_000_000)", max_output_bytes=1000)
    assert result["truncated"] is True
    assert len(result["stdout"]) == 1000
