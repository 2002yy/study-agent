"""§143-SI production Crawl4AI specialist integration regressions.

The specialist must be production-addressable yet default-inert. These tests use
injected fakes for the worker bridge / executor, so they run without a real
Crawl4AI environment. One optional end-to-end test runs only when the operator
provides ``CRAWL4AI_PYTHON`` (the same explicit configuration production uses).
"""

from __future__ import annotations

import subprocess
import sys
import time
import types
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tools" / "f2_paired_fixture_server.py"

sys.path.insert(0, str(REPO_ROOT))

from src.application.active_research_runtime import ACTIVE_READER_CHAIN  # noqa: E402
from src.web.research.crawl4ai_browser_executor import WorkerUnavailable  # noqa: E402
from src.web.research.crawl4ai_specialist import (  # noqa: E402
    CRAWL4AI_BROWSER,
    SPECIALIST_ENABLED_ENV,
    SPECIALIST_PYTHON_ENV,
    _SpecialistManager,
    configured_python,
    crawl4ai_specialist_status,
    invoke_crawl4ai_specialist,
)


class FakeBridge:
    def __init__(self, python: str, *, ready: bool = True, fail_start: bool = False) -> None:
        self.python = python
        self._ready = ready
        self.fail_start = fail_start
        self.started = False
        self.stopped = False
        self.requests: list[dict] = []

    def start(self, **_: object) -> None:
        if self.fail_start:
            raise RuntimeError("boom")
        self.started = True

    @property
    def availability(self) -> bool:
        return self._ready

    def request(self, **payload: object) -> dict:
        self.requests.append(dict(payload))
        return {"provider_success": True, "content": "ok"}

    def stop(self) -> None:
        self.stopped = True
        self._ready = False


class FakeExecutor:
    """Records construction kwargs and the executed request."""

    last_kwargs: dict = {}
    calls: int = 0
    raise_unavailable = False
    kill_bridge: FakeBridge | None = None

    def __init__(self, **kwargs: object) -> None:
        FakeExecutor.last_kwargs = dict(kwargs)
        self._bridge = kwargs.get("bridge")

    def execute(self, request: object) -> types.SimpleNamespace:
        FakeExecutor.calls += 1
        if FakeExecutor.raise_unavailable:
            raise WorkerUnavailable("crashed")
        if FakeExecutor.kill_bridge is not None:
            FakeExecutor.kill_bridge._ready = False
        return types.SimpleNamespace(
            backend=CRAWL4AI_BROWSER,
            retrieval_state="success",
            usable_content=True,
            content="recovered",
        )


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setenv(SPECIALIST_ENABLED_ENV, "1")
    monkeypatch.setenv(SPECIALIST_PYTHON_ENV, sys.executable)
    monkeypatch.setenv("RESEARCH_WIGOLO_ESCALATION", "browser")
    FakeExecutor.last_kwargs = {}
    FakeExecutor.calls = 0
    FakeExecutor.raise_unavailable = False
    FakeExecutor.kill_bridge = None
    return monkeypatch


def _manager(bridges: list[FakeBridge]) -> _SpecialistManager:
    def factory(python: str) -> FakeBridge:
        bridge = FakeBridge(python)
        bridges.append(bridge)
        return bridge

    return _SpecialistManager(bridge_factory=factory, executor_factory=FakeExecutor)


# ------------------------------------------------------------- safety boundary

def test_default_chain_is_unchanged_and_has_no_specialist() -> None:
    assert ACTIVE_READER_CHAIN == ("native_http", "wigolo_http")
    assert "crawl4ai" not in ACTIVE_READER_CHAIN
    assert CRAWL4AI_BROWSER not in ACTIVE_READER_CHAIN


def test_no_explicit_invocation_never_starts_the_worker(enabled) -> None:
    bridges: list[FakeBridge] = []
    _manager(bridges)
    # merely constructing the manager must not start anything
    assert bridges == []
    status = crawl4ai_specialist_status()
    assert status["worker_started"] is False
    assert status["worker_starts"] == 0


# ------------------------------------------------------------------ fail-closed

def test_disabled_gate_blocks_invocation_without_starting(enabled) -> None:
    enabled.delenv(SPECIALIST_ENABLED_ENV, raising=False)
    bridges: list[FakeBridge] = []
    manager = _manager(bridges)
    out = manager.invoke(url="http://127.0.0.1/x")
    assert out["specialist_available"] is False
    assert out["unavailable_reason"] in {"disabled", "browser_tier_disabled"}
    assert bridges == []
    assert FakeExecutor.calls == 0


def test_missing_python_is_unavailable_without_host_fallback(enabled) -> None:
    enabled.delenv(SPECIALIST_PYTHON_ENV, raising=False)
    assert configured_python() == ""
    bridges: list[FakeBridge] = []
    manager = _manager(bridges)
    out = manager.invoke(url="http://127.0.0.1/x")
    assert out["unavailable_reason"] == "python_not_configured"
    assert bridges == []
    assert FakeExecutor.calls == 0


def test_python_must_be_absolute_and_exist(enabled, tmp_path) -> None:
    enabled.setenv(SPECIALIST_PYTHON_ENV, "python.exe")
    assert _manager([]).invoke(url="u")["unavailable_reason"] == "python_not_absolute"

    enabled.setenv(SPECIALIST_PYTHON_ENV, str(tmp_path / "nope" / "python.exe"))
    assert _manager([]).invoke(url="u")["unavailable_reason"] == "python_missing"


def test_browser_tier_disabled_is_fail_closed(enabled) -> None:
    enabled.setenv("RESEARCH_WIGOLO_ESCALATION", "off")
    bridges: list[FakeBridge] = []
    out = _manager(bridges).invoke(url="u")
    assert out["unavailable_reason"] == "browser_tier_disabled"
    assert bridges == []


def test_start_failure_is_fail_closed(enabled) -> None:
    def factory(_python: str) -> FakeBridge:
        return FakeBridge(_python, fail_start=True)

    manager = _SpecialistManager(bridge_factory=factory, executor_factory=FakeExecutor)
    out = manager.invoke(url="u")
    assert out["specialist_available"] is False
    assert out["unavailable_reason"].startswith("start_failed:")


# --------------------------------------------------------- lazy + warm reuse

def test_first_invocation_lazy_starts_and_second_reuses(enabled) -> None:
    bridges: list[FakeBridge] = []
    manager = _manager(bridges)
    first = manager.invoke(url="http://127.0.0.1/a")
    second = manager.invoke(url="http://127.0.0.1/b")
    assert first["specialist_available"] is True
    assert second["specialist_available"] is True
    assert len(bridges) == 1, "warm worker must be reused"
    assert bridges[0].started is True
    assert manager.worker_starts == 1


def test_dead_worker_after_invocation_is_reset_and_next_lazily_starts(enabled) -> None:
    bridges: list[FakeBridge] = []

    # first bridge will be killed by the executor mid-call
    def factory(python: str) -> FakeBridge:
        bridge = FakeBridge(python)
        bridges.append(bridge)
        FakeExecutor.kill_bridge = bridge
        return bridge

    manager = _SpecialistManager(bridge_factory=factory, executor_factory=FakeExecutor)
    first = manager.invoke(url="http://127.0.0.1/a")
    assert first["specialist_available"] is True
    assert manager.worker_resets == 1, "a worker that died must be reset"

    # next explicit invocation starts a fresh worker
    FakeExecutor.kill_bridge = None
    second = manager.invoke(url="http://127.0.0.1/b")
    assert second["specialist_available"] is True
    assert len(bridges) == 2
    assert manager.worker_starts == 2


def test_worker_crash_fails_closed_without_replay(enabled) -> None:
    bridges: list[FakeBridge] = []
    manager = _manager(bridges)
    FakeExecutor.raise_unavailable = True
    out = manager.invoke(url="http://127.0.0.1/a")
    assert out["specialist_available"] is False
    assert out["unavailable_reason"] == "worker_crash"
    assert FakeExecutor.calls == 1, "the current request must not be replayed"
    assert manager.worker_resets == 1


def test_timeout_does_not_mechanically_restart_healthy_worker(enabled) -> None:
    bridges: list[FakeBridge] = []
    manager = _manager(bridges)
    # executor returns a bounded failure but the bridge is still healthy
    manager.invoke(url="http://127.0.0.1/a")
    manager.invoke(url="http://127.0.0.1/b")
    assert manager.worker_resets == 0
    assert len(bridges) == 1


# ------------------------------------------------------------- contract surface

def test_provenance_fields_are_recorded(enabled) -> None:
    bridges: list[FakeBridge] = []
    out = _manager(bridges).invoke(url="http://127.0.0.1/a")
    assert out["requested_specialist"] == CRAWL4AI_BROWSER
    assert out["actual_backend"] == CRAWL4AI_BROWSER
    assert out["terminal_outcome"] == "success"
    assert out["fallback_used"] is False
    assert out["latency_ms"] >= 0.0
    assert out["result"] is not None


def test_session_setup_is_consumed_not_invented(enabled) -> None:
    bridges: list[FakeBridge] = []
    manager = _manager(bridges)
    manager.invoke(
        url="http://127.0.0.1/session/check",
        session_id="s1",
        setup_url="http://127.0.0.1/session/start",
    )
    bridge = bridges[0]
    # the setup call is issued explicitly with the caller's session
    assert any(r.get("url") == "http://127.0.0.1/session/start" for r in bridge.requests)
    assert FakeExecutor.last_kwargs["session_id"] == "s1"


def test_deadline_and_budget_are_forwarded(enabled) -> None:
    bridges: list[FakeBridge] = []
    sentinel_clock = lambda: 1.0  # noqa: E731
    sentinel_charge = lambda ms: None  # noqa: E731
    _manager(bridges).invoke(
        url="http://127.0.0.1/a",
        hard_seconds_left=sentinel_clock,
        charge_envelope=sentinel_charge,
    )
    assert FakeExecutor.last_kwargs["hard_seconds_left"] is sentinel_clock
    assert FakeExecutor.last_kwargs["charge_envelope"] is sentinel_charge


def test_specialist_gate_off_has_no_effect_on_default_runtime() -> None:
    # gate is off by default; the default chain is a static contract
    assert ACTIVE_READER_CHAIN == ("native_http", "wigolo_http")


# ------------------------------------------------- optional real-worker e2e

def test_real_specialist_is_addressable(monkeypatch, tmp_path) -> None:
    python = configured_python()
    if not python:
        pytest.skip("CRAWL4AI_PYTHON not set; operator-provided e2e only")

    monkeypatch.setenv(SPECIALIST_ENABLED_ENV, "1")
    monkeypatch.setenv("RESEARCH_WIGOLO_ESCALATION", "browser")
    monkeypatch.setenv("WIGOLO_RERANKER", "off")

    server = subprocess.Popen(
        [sys.executable, "-u", "-X", "utf8", str(FIXTURE), "--port", "8801"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = "http://127.0.0.1:8801"
    ready = False
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base}/structured-spec.html", timeout=2).read(8)
            ready = True
            break
        except Exception:
            time.sleep(0.3)
    if not ready:
        server.terminate()
        pytest.skip("fixture server not ready")
    try:
        try:
            out = invoke_crawl4ai_specialist(url=f"{base}/structured-spec.html", mode="browser")
        finally:
            from src.web.research.crawl4ai_specialist import reset_crawl4ai_specialist

            reset_crawl4ai_specialist()
        assert out["specialist_available"] is True
        assert out["actual_backend"] == CRAWL4AI_BROWSER
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()
