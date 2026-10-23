"""Time-boundary behaviour: a slow network must not lose work or fake success.

Simulates a slow provider (scripted gateway + tiny wall budget) and asserts the
Deep run exits safely: it returns, keeps its checkpointed plan/notes so it can be
resumed, reports the unexecuted supplement honestly, and never fabricates a
computation.  Zero model cost.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository


class SlowGateway:
    """Every read is slow; searches return many candidates."""

    def __init__(self, read_seconds: float = 0.05, candidates: int = 6):
        self.read_seconds = read_seconds
        self.candidates = candidates
        self.search_calls: list[str] = []
        self.read_calls: list[str] = []

    def search(self, query: str, *, max_items: int = 10):
        self.search_calls.append(query)
        return [
            {"title": f"{query} #{index}", "url": f"https://example.org/{index}",
             "source": "Test", "snippet": f"{query} snippet {index}"}
            for index in range(min(self.candidates, max_items))
        ]

    def read(self, url: str, *, max_chars: int = 6000):
        self.read_calls.append(url)
        time.sleep(self.read_seconds)
        return {"ok": True, "url": url, "content": "slow page body " * 20}

    def warnings(self):
        return []


class OneTaskPlanner:
    def plan(self, query, context):
        return ["slow research topic"]

    def revise(self, memo, notes, remaining):
        return {"done": True, "additional": [], "compute": None}


def _service(tmp_path: Path, gateway: SlowGateway) -> WebLookupService:
    database = RuntimeDatabase(tmp_path / "runtime.db")
    database.initialize()
    return WebLookupService(WebLookupRepository(database), gateway, planner=OneTaskPlanner())


def test_slow_network_with_tiny_wall_budget_exits_safely(tmp_path, monkeypatch):
    policy = {
        "initial": {"model_calls": 3, "searches": 4, "reads": 1, "python_runs": 0, "wall_seconds": 0.3},
        "per_goal": {"model_calls": 1, "searches": 2, "reads": 1, "python_runs": 0, "wall_seconds": 0.2},
        "limits": {"model_calls": 4, "searches": 6, "reads": 2, "python_runs": 0, "wall_seconds": 0.5},
    }
    monkeypatch.setenv("WEB_RESEARCH_STEERING_BUDGET_POLICY", json.dumps(policy))
    gateway = SlowGateway(read_seconds=0.05, candidates=6)
    service = _service(tmp_path, gateway)

    run = service.create("slow topic", owner_thread_id="t", research_mode="deep")
    started = time.monotonic()
    completed = service.execute(run.id)
    elapsed = time.monotonic() - started

    # 1. It returns instead of hanging, and it respects the wall ceiling (with slack
    #    for one in-flight read).
    assert elapsed < 5.0

    deep = completed.research_context["deep"]
    # 2. Checkpointed work is preserved for a later resume.
    assert deep.get("plan"), "the plan must survive a time stop"
    assert deep.get("steps")
    assert completed.query_attempts is not None

    # 3. The read budget was respected, and nothing was fabricated.
    assert len(gateway.read_calls) <= policy["limits"]["reads"]
    assert not (deep.get("computations") or [])


def test_time_stop_keeps_the_supplement_honest(tmp_path, monkeypatch):
    policy = {
        "initial": {"model_calls": 3, "searches": 4, "reads": 8, "python_runs": 0, "wall_seconds": 0.1},
        "per_goal": {"model_calls": 1, "searches": 1, "reads": 1, "python_runs": 0, "wall_seconds": 0.1},
        "limits": {"model_calls": 4, "searches": 6, "reads": 10, "python_runs": 0, "wall_seconds": 0.2},
    }
    monkeypatch.setenv("WEB_RESEARCH_STEERING_BUDGET_POLICY", json.dumps(policy))
    gateway = SlowGateway(read_seconds=0.05)
    service = _service(tmp_path, gateway)
    run = service.create("slow topic", owner_thread_id="t", research_mode="deep")

    original = gateway.search
    injected = False

    def search(query, *, max_items=10):
        nonlocal injected
        if not injected:
            injected = True
            service.steer(run.id, content="按新配置重算：2 魂 叠影 5", request_id="req-slow")
        return original(query, max_items=max_items)

    gateway.search = search
    completed = service.execute(run.id)

    deep = completed.research_context["deep"]
    entry = deep["steering"][0]
    # Accepted, and honestly reported as not executed.
    assert entry.get("executed_in_round") is None
    assert not (deep.get("computations") or [])
    warning_text = " ".join(str(item) for item in (completed.warnings or []))
    assert ("未能" in warning_text) or completed.status == "partial"
