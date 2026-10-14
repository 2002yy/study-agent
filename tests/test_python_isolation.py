"""Isolated Python: hardening, fail-closed, bounds and required negative controls.

The orchestration-level tests here use a fake docker process; they prove the
command hardening and the fail-closed contract.  The real-container negative
controls are skipped unless an isolation runtime is actually usable, because a
mock can never prove that host files or the network are unreachable.
"""

from __future__ import annotations

import subprocess

import pytest

from src.tools.python_isolation import (
    DockerPythonRunner,
    IsolationSpec,
    IsolationUnavailable,
    NullRunner,
    isolated_python_available,
    get_default_runner,
)


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeDocker:
    def __init__(self, *, run_result=None, raise_timeout=False, inspect_returncode=0):
        self.calls: list[tuple[list[str], dict]] = []
        self.run_result = run_result or FakeCompleted()
        self.raise_timeout = raise_timeout
        self.inspect_returncode = inspect_returncode

    def __call__(self, cmd, **kwargs):
        self.calls.append((list(cmd), kwargs))
        if len(cmd) > 1 and cmd[1] == "image":
            return FakeCompleted(self.inspect_returncode)
        if len(cmd) > 1 and cmd[1] == "rm":
            return FakeCompleted()
        if self.raise_timeout:
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1))
        return self.run_result

    @property
    def run_cmd(self) -> list[str]:
        for cmd, _ in self.calls:
            if len(cmd) > 1 and cmd[1] == "run":
                return cmd
        raise AssertionError("no docker run command recorded")


def spec(**overrides) -> IsolationSpec:
    return IsolationSpec(image="python:3.12-slim", **overrides)


def test_run_command_has_no_network_no_host_mounts_and_hard_limits(monkeypatch):
    monkeypatch.setattr("src.tools.python_isolation.shutil.which", lambda _: "docker")
    fake = FakeDocker(run_result=FakeCompleted(0, stdout='{"columns":["a"],"rows":[[1]]}'))
    runner = DockerPythonRunner(spec(), runner=fake)
    assert runner.available() is True
    out = runner.run("print('hi')")
    cmd = fake.run_cmd
    for flag in ("--network", "--read-only", "--cap-drop", "--security-opt", "--pids-limit", "--memory", "--user", "--tmpfs", "--ulimit"):
        assert flag in cmd
    assert cmd[cmd.index("--network") + 1] == "none"
    assert cmd[cmd.index("--cap-drop") + 1] == "ALL"
    assert cmd[cmd.index("--user") + 1] == "65534:65534"
    assert not any(part.startswith("-v") or part.startswith("--volume") or ":" in part and part.endswith(":/host") for part in cmd)
    assert out["status"] == "succeeded"


def test_timeout_kills_the_whole_container(monkeypatch):
    monkeypatch.setattr("src.tools.python_isolation.shutil.which", lambda _: "docker")
    fake = FakeDocker(raise_timeout=True)
    runner = DockerPythonRunner(spec(timeout_seconds=1), runner=fake)
    out = runner.run("while True: pass")
    assert out["status"] == "timeout"
    assert any(cmd[1:3] == ["rm", "-f"] for cmd, _ in fake.calls)


def test_output_is_bounded(monkeypatch):
    monkeypatch.setattr("src.tools.python_isolation.shutil.which", lambda _: "docker")
    fake = FakeDocker(run_result=FakeCompleted(0, stdout="x" * 50_000))
    runner = DockerPythonRunner(spec(max_output_bytes=100), runner=fake)
    out = runner.run("print('x'*50000)")
    assert out["truncated"] is True
    assert len(out["stdout"]) == 100


def test_availability_requires_a_working_daemon_and_image(monkeypatch):
    monkeypatch.setattr("src.tools.python_isolation.shutil.which", lambda _: None)
    assert DockerPythonRunner(spec(), runner=FakeDocker()).available() is False
    monkeypatch.setattr("src.tools.python_isolation.shutil.which", lambda _: "docker")
    assert DockerPythonRunner(spec(), runner=FakeDocker(inspect_returncode=1)).available() is False


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
    runner = DockerPythonRunner(spec(timeout_seconds=overrides.pop("timeout_seconds", 10), **overrides))
    return runner.run(code)


@requires_isolation
def test_negative_control_cannot_read_host_files_or_secrets():
    result = _real_run("print(open('/etc/passwd').read())")
    assert result["status"] == "failed"
    assert "passwd" not in result["stdout"]


@requires_isolation
def test_negative_control_cannot_reach_the_network():
    result = _real_run("import socket; socket.create_connection(('1.1.1.1', 53), 3)")
    assert result["status"] == "failed"


@requires_isolation
def test_negative_control_infinite_loop_is_killed():
    result = _real_run("while True:\n    pass", timeout_seconds=2)
    assert result["status"] == "timeout"


@requires_isolation
def test_negative_control_unbounded_output_is_capped():
    result = _real_run("print('x' * 10_000_000)", max_output_bytes=1000)
    assert result["truncated"] is True
