"""G18 deep research: multi-round WebLookupRun pipeline tests.

Contract: docs/PROJECT_STATUS.md section 11 (decisions 1-16). Real
WebLookupRepository against a temporary SQLite database; gateway and planner
are scripted fakes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository


class ScriptedGateway:
    """Deterministic gateway: search results keyed by substring, read keyed by url."""

    def __init__(self, search_map: dict[str, list[dict]], fail_reads: set[str] | None = None):
        self.search_map = {key.lower(): value for key, value in search_map.items()}
        self.fail_reads = fail_reads or set()
        self.search_calls: list[str] = []
        self.read_calls: list[str] = []

    def search(self, query: str, *, max_items: int = 10) -> list[dict]:
        self.search_calls.append(query)
        for key, results in self.search_map.items():
            if key in query.lower():
                # Echo the query into title/snippet so assess_sources marks
                # the result relevant (directness != unmatched).
                echoed = []
                for item in results[:max_items]:
                    record = dict(item)
                    record["title"] = f"{query} - {record.get('title', '')}"
                    record["snippet"] = f"{query}: {record.get('snippet', '')}"
                    echoed.append(record)
                return echoed
        return []

    def read(self, url: str, *, max_chars: int = 6000) -> dict:
        self.read_calls.append(url)
        if url in self.fail_reads:
            raise RuntimeError("deterministic read failure")
        return {
            "ok": True,
            "url": url,
            "content": f"Deterministic content for {url}. " * 3,
        }

    def warnings(self) -> list[dict[str, str]]:
        return []


class ScriptedPlanner:
    """plan() returns the initial decomposition; revise() drives round count."""

    def __init__(
        self,
        initial: list[str],
        revisions: list[dict] | None = None,
    ):
        self.initial = initial
        self.revisions = list(revisions or [])

    def plan(self, query: str, context) -> list[str]:
        return list(self.initial)

    def revise(self, memo: str, notes, remaining):
        if self.revisions:
            verdict = self.revisions.pop(0)
            return {
                "done": verdict.get("done", False),
                "additional": verdict.get("additional", []),
            }
        return {"done": True, "additional": []}


def _service(
    tmp_path: Path,
    gateway: ScriptedGateway,
    planner: ScriptedPlanner | None = None,
) -> WebLookupService:
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    return WebLookupService(repository, gateway, planner=planner)


def _result(url: str, title: str) -> dict:
    return {
        "title": title,
        "url": url,
        "source": "Test source",
        "snippet": f"Evidence snippet from {title}",
    }


def test_deep_run_produces_notes_memo_and_rounds(tmp_path):
    gateway = ScriptedGateway(
        {
            "deep topic sub one": [_result("https://a.test/1", "Source One")],
            "deep topic sub two": [_result("https://b.test/2", "Source Two")],
            "additional deep topic": [_result("https://d.test/9", "Added Source")],
        }
    )
    planner = ScriptedPlanner(
        initial=["deep topic sub one", "deep topic sub two"],
        # Decision 9: after round 1 the planner finds a gap and inserts a
        # new sub-question; round 2 researches it and closes the run.
        revisions=[
            {"done": False, "additional": ["additional deep topic"]},
            {"done": True},
        ],
    )
    service = _service(tmp_path, gateway, planner)
    run = service.create("deep topic", research_mode="deep")
    assert run.research_context["research_mode"] == "deep"
    assert run.research_context["deep"]["steering"] == []

    completed = service.execute(run.id)
    assert completed.status == "completed"
    deep = completed.research_context["deep"]
    assert len(deep["plan"]) == 3
    added = [task for task in deep["plan"] if task["task_id"] == "a1_1"]
    assert added and added[0]["status"] == "done"
    assert all(task["status"] == "done" for task in deep["plan"])
    assert deep["round_index"] >= 2
    assert len(deep["notes"]) >= 2
    assert "Deterministic content" in deep["memo"]
    # Both sub-questions were searched at least once each.
    assert len(gateway.search_calls) >= 2
    assert any("deep topic sub one" in call for call in gateway.search_calls)
    assert any("deep topic sub two" in call for call in gateway.search_calls)
    assert any("additional deep topic" in call for call in gateway.search_calls)


def test_steering_before_execution_marks_influenced_by_steering(tmp_path):
    gateway = ScriptedGateway(
        {"focus area": [_result("https://c.test/3", "Steered Source - steered topic focus area")]}
    )
    planner = ScriptedPlanner(initial=["steered topic focus area"])
    service = _service(tmp_path, gateway, planner)
    run = service.create("steered topic", research_mode="deep")

    # Inject steering before execution: it must be consumed in round 1.
    steered = service.steer(run.id, content="重点看 X 方向")
    assert steered is not None
    deep = steered.research_context["deep"]
    assert deep["steering"][0]["incorporated_in_round"] is None

    completed = service.execute(run.id)
    assert completed.status == "completed"
    deep = completed.research_context["deep"]
    consumed = deep["steering"][0]
    assert consumed["incorporated_in_round"] == 1
    # Audit marker propagates to attempts and sources created in round 1.
    marked_attempts = [
        attempt
        for attempt in completed.query_attempts
        if attempt.get("influenced_by_steering")
    ]
    assert marked_attempts, "steered round attempts must carry the marker"


def test_steer_rejects_settled_run(tmp_path):
    gateway = ScriptedGateway({"idle": [_result("https://i.test/7", "Idle")]})
    service = _service(tmp_path, gateway)
    run = service.create("idle topic", research_mode="deep")
    completed = service.execute(run.id)
    assert completed.status == "completed"
    with pytest.raises(ValueError):
        service.steer(run.id, content="too late")


def test_retry_once_then_skip_on_empty_results(tmp_path):
    # Only "good question" has results; the other sub-question gets both its
    # queries empty → skipped with a gap note, run still completes.
    gateway = ScriptedGateway({"good": [_result("https://g.test/4", "Good Source")]})
    planner = ScriptedPlanner(initial=["good deep topic", "hopeless deep topic"])
    service = _service(tmp_path, gateway, planner)
    run = service.create("mixed topic", research_mode="deep")

    completed = service.execute(run.id)
    assert completed.status == "completed"
    deep = completed.research_context["deep"]
    statuses = {task["sub_question"]: task["status"] for task in deep["plan"]}
    assert statuses["good deep topic"] == "done"
    assert statuses["hopeless deep topic"] == "skipped"
    # Retry-once: two queries attempted for the hopeless sub-question.
    hopeless_queries = [
        call for call in gateway.search_calls if 'hopeless' in call.lower()
    ]
    assert len(hopeless_queries) == 2


@pytest.mark.xfail(
    reason="known gap: concurrently-appended deep steering is persisted but not yet "
    "consumed by the running executor (next round boundary / terminal write)",
    strict=False,
)
def test_concurrent_steering_is_persisted_and_consumed(tmp_path):
    """A steering appended between two checkpoints must survive AND be consumed."""
    state = {"steered": False, "run_id": ""}
    gateway = ScriptedGateway({"area": [_result("https://c.test/1", "Focus Source")]})
    base_search = gateway.search

    def steering_search(query, *, max_items: int = 10):
        if not state["steered"] and state["run_id"]:
            state["steered"] = True
            service.steer(state["run_id"], content="并发追加：补充对比维度")
        return base_search(query, max_items=max_items)

    gateway.search = steering_search
    # Three sub-questions force a second round so the appended condition can be
    # consumed at the next round boundary.
    service = _service(
        tmp_path,
        gateway,
        ScriptedPlanner(initial=["focus area", "second area", "third area"]),
    )
    run = service.create("concurrent steering topic", research_mode="deep")
    state["run_id"] = run.id

    completed = service.execute(run.id)
    deep = completed.research_context["deep"]
    entry = next(
        (s for s in deep.get("steering", []) if "并发追加" in str(s.get("content") or "")),
        None,
    )
    assert entry is not None, "concurrent steering must survive the checkpoint"
    assert entry["incorporated_in_round"] is not None, "the executor must consume it"


def test_follow_up_child_has_its_own_opening(tmp_path):
    from src.application.runtime_repository import RuntimeRepository

    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    service = WebLookupService(
        repository, ScriptedGateway({"parent": [_result("https://p.test/1", "P")]})
    )
    RuntimeRepository(repository.database).ensure_chat_thread("thread-1")
    parent = service.create(
        "parent topic about PostgreSQL",
        owner_thread_id="thread-1",
        owner_turn_id="turn-1",
    )
    service.execute(parent.id)  # a follow-up child requires a terminal parent
    child = service.create_follow_up(
        "child topic about MySQL MVCC",
        max_items=8,
        owner_thread_id="thread-1",
        owner_turn_id="turn-2",
        parent_run_id=parent.id,
        create_request_id="req-1",
    )
    child_approach = child.research_context["approach"]
    parent_approach = parent.research_context["approach"]
    assert child_approach["origin"] == "query_plan"
    assert child_approach["turn_id"] == "turn-2"
    assert child_approach["summary"] != parent_approach["summary"]


def test_checkpoint_does_not_update_approach_after_cancel(tmp_path):
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    service = WebLookupService(repository, ScriptedGateway({}), planner=ScriptedPlanner(initial=["a"]))
    run = service.create("cancel topic", research_mode="deep")
    before = dict(run.research_context["approach"])
    operation_id = str(
        ((run.research_context.get("operation") or {}).get("active_operation_id")) or ""
    )
    repository.request_cancel(run.id)

    stale = dict(before)
    stale["summary"] = "取消后不应出现的更新"
    stale["sequence"] = int(before.get("sequence") or 0) + 1
    stale["origin"] = "direction_update"
    stale["status"] = "ready"
    context = dict(run.research_context)
    context["approach"] = stale
    try:
        updated = repository.checkpoint(
            run.id,
            operation_id=operation_id,
            research_context=context,
            query_attempts=[],
            selected_sources=[],
            rejected_sources=[],
            items=[],
            warnings=[],
        )
    except ValueError:
        updated = None
    after = (updated or repository.get(run.id)).research_context["approach"]
    assert after["summary"] == before["summary"], "a cancelled run must not change its opening"


def test_standard_mode_unchanged(tmp_path):
    gateway = ScriptedGateway({"standard": [_result("https://s.test/5", "Std")]})
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    service = WebLookupService(repository, gateway)
    run = service.create("standard topic")
    assert run.research_context.get("research_mode", "standard") == "standard"
    assert "deep" not in run.research_context
    completed = service.execute(run.id)
    assert completed.status == "completed"
    # Standard path never produces deep structures.
    assert "deep" not in completed.research_context


def test_planning_stage_recorded_in_stage_history(tmp_path):
    gateway = ScriptedGateway({"topic": [_result("https://p.test/6", "Plan Source")]})
    planner = ScriptedPlanner(initial=["Topic question"])
    service = _service(tmp_path, gateway, planner)
    run = service.create("planned topic", research_mode="deep")
    completed = service.execute(run.id)
    # Final stage is completed; steps log records the planning entry.
    steps = completed.research_context["deep"]["steps"]
    kinds = [step["kind"] for step in steps]
    assert "planning" in kinds
    assert "round" in kinds
