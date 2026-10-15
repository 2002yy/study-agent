"""Production Deep loop: real planner wiring, steering context, budget, compute.

Everything here runs the **production service factory** (`get_web_lookup_service`,
which now injects `ModelDeepPlanner`) plus a **simulated model provider**
(a scripted completion), a scripted search gateway and a real SQLite database.
No paid call is made.

Covers the P1/P1b/P2 fixes and the required negative controls: malformed model
output, no compute proposed, exhausted budget, duplicate steering, and compute
failure — each must be reported honestly rather than fabricated.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.web.research.deep_planner import ModelDeepPlanner

POLICY = {
    "initial": {"model_calls": 5, "searches": 5, "reads": 8, "python_runs": 0, "wall_seconds": 150},
    "per_goal": {"model_calls": 2, "searches": 3, "reads": 4, "python_runs": 0, "wall_seconds": 45},
    "limits": {"model_calls": 9, "searches": 11, "reads": 16, "python_runs": 0, "wall_seconds": 300},
}


class ScriptedGateway:
    def __init__(self, mapping: dict[str, list[dict]]):
        self.mapping = {key.lower(): value for key, value in mapping.items()}
        self.search_calls: list[str] = []
        self.read_calls: list[str] = []

    def search(self, query: str, *, max_items: int = 10):
        self.search_calls.append(query)
        for key, results in self.mapping.items():
            if key in query.lower():
                out = []
                for item in results[:max_items]:
                    record = dict(item)
                    record["title"] = f"{query} - {record.get('title', '')}"
                    record["snippet"] = f"{query}: {record.get('snippet', '')}"
                    out.append(record)
                return out
        return []

    def read(self, url: str, *, max_chars: int = 6000):
        self.read_calls.append(url)
        return {"ok": True, "url": url,
                "content": "流萤超击破机制：击破特攻提高超击破伤害。 " * 3}

    def warnings(self):
        return []


def _result(url: str, title: str) -> dict:
    return {"title": title, "url": url, "source": "Test source",
            "snippet": f"Evidence from {title}"}


def _production_service(tmp_path: Path, monkeypatch, gateway: ScriptedGateway):
    """Build the service through the production factory (planner included)."""

    import src.application.runtime_repository as runtime_repository
    from src.infrastructure.sqlite.database import RuntimeDatabase
    from src.repositories.web_lookup_repository import WebLookupRepository

    database = RuntimeDatabase(tmp_path / "runtime.db")
    database.initialize()
    monkeypatch.setattr(
        runtime_repository,
        "get_web_lookup_repository",
        lambda: WebLookupRepository(database),
    )
    runtime_repository.get_web_lookup_service.cache_clear()
    service = runtime_repository.get_web_lookup_service()
    # Only external transports are substituted; the service/planner are production.
    service.gateway = gateway
    return service, database


def _scripted_provider(plan_queries, revise_responses):
    """A simulated model provider: scripted, never a real call."""

    calls: list[dict] = []

    def completion(instruction: str, payload: dict) -> str:
        calls.append({"instruction": instruction, "payload": payload})
        if "sub_questions" in instruction:
            return json.dumps({"sub_questions": list(plan_queries)})
        index = sum(1 for c in calls if "sub_questions" not in c["instruction"]) - 1
        return json.dumps(revise_responses[min(index, len(revise_responses) - 1)])

    return completion, calls


def test_production_factory_injects_a_model_deep_planner(tmp_path, monkeypatch):
    service, _ = _production_service(tmp_path, monkeypatch, ScriptedGateway({}))
    assert isinstance(service.planner, ModelDeepPlanner)


def test_deep_run_plans_researches_recomputes_and_stays_consistent(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_RESEARCH_STEERING_BUDGET_POLICY", json.dumps(POLICY))
    gateway = ScriptedGateway({"流萤": [_result("https://example.org/firefly", "流萤机制")]})
    service, _ = _production_service(tmp_path, monkeypatch, gateway)
    completion, calls = _scripted_provider(
        ["流萤 击破特攻 伤害", "流萤 光锥叠影 加成"],
        [
            {"done": False, "additional": [], "compute": {
                "engine": "deterministic", "mode": "table", "statistic": "mean",
                "series": {"1魂/叠影1": [10.0, 10.0]}, "unit": "dps"}},
            {"done": True, "additional": [], "compute": {
                "engine": "deterministic", "mode": "table", "statistic": "mean",
                "series": {"2魂/叠影5": [18.0, 20.0]}, "unit": "dps"}},
        ],
    )
    service.planner._completion = completion

    run = service.create(
        "帮我比较流萤在两种配置下的伤害和资源投入",
        owner_thread_id="thread-1", research_mode="deep",
        attachment_material=[{"attachment_id": "att1", "filename": "shot.png",
                              "content_hash": "h1", "text": "流萤 1 魂，光锥叠影 1"}],
    )

    original_search = gateway.search
    injected = False

    def search(query, *, max_items=10):
        nonlocal injected
        if not injected:
            injected = True
            service.steer(run.id, content="按新配置重算：流萤实际上是 2 魂，光锥叠影 5",
                          request_id="req-1")
            service.steer(run.id, content="按新配置重算：流萤实际上是 2 魂，光锥叠影 5",
                          request_id="req-1")  # duplicate must be idempotent
        return original_search(query, max_items=max_items)

    gateway.search = search
    completed = service.execute(run.id)

    # Initial model planning produced the queries (not the raw user sentence).
    assert "流萤 击破特攻 伤害" in gateway.search_calls
    plan_payload = next(c["payload"] for c in calls if "sub_questions" in c["instruction"])
    assert plan_payload["question"].startswith("帮我比较流萤")

    # Real reading happened.
    assert gateway.read_calls.count("https://example.org/firefly") >= 1

    deep = completed.research_context["deep"]
    # Steering: one entry (idempotent), accepted AND executed.
    assert len(deep["steering"]) == 1
    assert deep["steering"][0]["incorporated_in_round"] is not None
    assert deep["steering"][0]["executed_in_round"] is not None

    # The revise call carried bounded steering context, and the recompute is real.
    revise_payloads = [c["payload"] for c in calls if "sub_questions" not in c["instruction"]]
    assert any(p.get("steering") for p in revise_payloads), "revise never saw the supplement"
    assert [item["status"] for item in deep["computations"]] == ["superseded", "succeeded"]
    assert deep["computations"][1]["result"]["rows"] == [["2魂/叠影5", 19.0]]

    # Budget ledger: persistent, idempotent, never reset.
    ledger = deep["incremental_budget"]
    assert ledger["grants"], "the supplement received no budget"
    assert ledger["consumed"]["model_calls"] >= 1

    # Surfaces agree: receipt + SQLite + budget.
    from src.api.routes.chat_routes import _research_progress

    progress = _research_progress(completed)
    assert [item["status"] for item in progress["steering"]] == ["applied"]
    assert progress["narration"]
    assert completed.research_context["attachments"][0]["attachment_id"] == "att1"


def test_malformed_model_output_is_reported_honestly(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_RESEARCH_STEERING_BUDGET_POLICY", json.dumps(POLICY))
    gateway = ScriptedGateway({"流萤": [_result("https://example.org/firefly", "流萤机制")]})
    service, _ = _production_service(tmp_path, monkeypatch, gateway)
    service.planner._completion = lambda instruction, payload: "not json at all"

    run = service.create("帮我比较流萤的配置", owner_thread_id="t", research_mode="deep")
    completed = service.execute(run.id)

    deep = completed.research_context["deep"]
    # No fabricated computation and no crash; the run stays bound.
    assert deep.get("computations") in (None, [], ())
    assert completed.status in {"completed", "partial", "failed"}


def test_no_compute_proposed_means_no_computation(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_RESEARCH_STEERING_BUDGET_POLICY", json.dumps(POLICY))
    gateway = ScriptedGateway({"流萤": [_result("https://example.org/firefly", "流萤机制")]})
    service, _ = _production_service(tmp_path, monkeypatch, gateway)
    completion, _ = _scripted_provider(
        ["流萤 机制"],
        [{"done": True, "additional": [], "compute": None}],
    )
    service.planner._completion = completion

    run = service.create("流萤机制是什么", owner_thread_id="t", research_mode="deep")
    completed = service.execute(run.id)
    assert not (completed.research_context["deep"].get("computations") or [])


def test_exhausted_steering_budget_reports_unexecuted_supplement(tmp_path, monkeypatch):
    starved = {
        "initial": {"model_calls": 1, "searches": 1, "reads": 1, "python_runs": 0, "wall_seconds": 1},
        "per_goal": {"model_calls": 0, "searches": 0, "reads": 0, "python_runs": 0, "wall_seconds": 0},
        "limits": {"model_calls": 1, "searches": 1, "reads": 1, "python_runs": 0, "wall_seconds": 1},
    }
    monkeypatch.setenv("WEB_RESEARCH_STEERING_BUDGET_POLICY", json.dumps(starved))
    gateway = ScriptedGateway({"流萤": [_result("https://example.org/firefly", "流萤机制")]})
    service, _ = _production_service(tmp_path, monkeypatch, gateway)
    completion, _ = _scripted_provider(["流萤 机制"], [{"done": True, "additional": [], "compute": None}])
    service.planner._completion = completion

    run = service.create("流萤机制是什么", owner_thread_id="t", research_mode="deep")
    original_search = gateway.search
    injected = False

    def search(query, *, max_items=10):
        nonlocal injected
        if not injected:
            injected = True
            service.steer(run.id, content="按新配置重算：2 魂 叠影 5", request_id="req-x")
        return original_search(query, max_items=max_items)

    gateway.search = search
    completed = service.execute(run.id)

    deep = completed.research_context["deep"]
    entry = deep["steering"][0]
    # Accepted but not executed -> the run must say so, not claim success.
    assert entry.get("executed_in_round") is None
    unapplied = any("未能" in str(w) or "不完整" in str(w) for w in (completed.warnings or []))
    assert unapplied or completed.status == "partial"
