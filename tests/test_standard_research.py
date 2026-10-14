"""Strategy is resumable; source acquisition never proves a requested claim."""

from copy import deepcopy
from datetime import timedelta
import json
import threading

import pytest

from src.application.standard_research import ModelStandardPlanner, StandardResearchLoop
from src.repositories.standard_execution_repository import StandardResearchBusy
from src.web.research.standard_plan import PLAN_SCHEMA, search_urls
from tests.test_standard_execution import running as running, resume, snapshot
from tests.test_standard_handoff import saved_parent as saved_parent


class Planner:
    def __init__(self, *, queries=None):
        self.requests = []
        self.queries = (
            ["Python 3.14 release date primary source"] if queries is None else queries
        )

    def __call__(self, request):
        self.requests.append(deepcopy(request))
        handoff = request["handoff"]
        return {
            "schema": PLAN_SCHEMA,
            "query": handoff["query"],
            "handoff_sha256": handoff["payload_sha256"],
            "gaps": [
                {"field": field, "queries": self.queries, "candidate_urls": []}
                for field in handoff["unresolved_fields"]
            ],
        }


class Gateway:
    def __init__(self, *, count=1, fail_reads=False):
        self.events = []
        self.count = count
        self.fail_reads = fail_reads

    def search_exact(self, query, **_kwargs):
        self.events.append(("search", query))
        return {
            "status": "ok",
            "results": [
                {"url": f"https://www.python.org/alternate-{index}"}
                for index in range(self.count)
            ],
        }

    def read(self, url, **_kwargs):
        self.events.append(("read", url))
        if self.fail_reads:
            raise OSError("offline")
        return {
            "ok": True,
            "url": url,
            "content": "Python 3.14 overview; no bound release date.",
        }


def test_saved_handoff_to_plan_search_read_and_nonpublishing_result(running):
    execution, _, _, runs, parent = running
    planner, gateway = Planner(), Gateway()
    result = StandardResearchLoop(execution, planner).advance(gateway)
    assert (
        planner.requests[0]["handoff"]
        == parent.rag_snapshot["lookup_terminal"]["handoff"]
    )
    assert len(planner.requests) == 1
    assert [kind for kind, _ in gateway.events] == ["search", "read"]
    assert result["stop_reason"] == "ready_for_binding"
    assert result["publication_authority"] is False and "answer" not in result
    assert result["unresolved_gaps"] == ["release_date"]
    assert result["gap_states"]["release_date"]["support_status"] == "NOT_EVALUATED"
    assert len(result["reused_sources"]) == len(result["acquired_sources"]) == 1
    assert result["budget_consumed"] == {
        "new_reads": 1,
        "new_queries": 1,
        "planner_calls": 1,
    }
    assert (
        runs.get(execution.run_id).research_context["standard"]["research"]["result"]
        == result
    )
    # Research opening ("研究开场"): projected from the model's own plan fields,
    # deterministically, with no extra call and no evidence authority.
    approach = runs.get(execution.run_id).research_context["approach"]
    assert approach["schema"] == "research-approach-v1"
    assert approach["origin"] == "model_plan"
    assert approach["status"] == "ready"
    assert approach["sequence"] == 1
    assert approach["focus"] == ["发布日期"]
    assert "发布日期" in approach["summary"]


def _generated_approach(run_id: str) -> dict:
    return {
        "schema": "research-approach-v1",
        "root_run_id": run_id,
        "turn_id": "",
        "mode": "standard",
        "status": "ready",
        "summary": "我会先核对发布日期，再核对许可证。",
        "focus": ["发布日期", "许可证"],
        "origin": "model_generated",
        "sequence": 1,
    }


def test_approach_attempt_authorization_is_persisted_and_idempotent(running):
    execution, clock, _, runs, _ = running
    # Authorization is only meaningful once the plan phase exists.
    StandardResearchLoop(execution, Planner()).advance(Gateway(), max_steps=1)
    args = (execution.run_id, execution.thread_id, execution.operation_id, clock[0])
    assert execution.journal.authorize_approach_attempt(*args, model_call_ceiling=2) is True
    # The reservation is authoritative: a second attempt cannot spend it again.
    assert execution.journal.authorize_approach_attempt(*args, model_call_ceiling=2) is False
    stored = runs.get(execution.run_id).research_context["standard"]["research"]
    assert stored["approach_generation_calls"] == 1


def test_approach_attempt_shares_the_planning_ceiling(running):
    execution, clock, _, _, _ = running
    StandardResearchLoop(execution, Planner()).advance(Gateway(), max_steps=1)
    args = (execution.run_id, execution.thread_id, execution.operation_id, clock[0])
    # planner_calls == 1 after planning, so a ceiling of 1 leaves no room.
    assert execution.journal.authorize_approach_attempt(*args, model_call_ceiling=1) is False
    # A ceiling of 2 shares the single remaining slot with the opening.
    assert execution.journal.authorize_approach_attempt(*args, model_call_ceiling=2) is True
    assert execution.journal.authorize_approach_attempt(*args, model_call_ceiling=2) is False


def test_record_approach_writes_atomically_and_rejects_stale(running):
    execution, clock, _, runs, _ = running
    args = (execution.run_id, execution.thread_id, execution.operation_id, clock[0])
    approach = _generated_approach(execution.run_id)
    assert execution.journal.record_approach(*args, approach) is True
    assert (
        runs.get(execution.run_id).research_context["approach"]["origin"]
        == "model_generated"
    )
    # Same/lower sequence must not overwrite.
    assert execution.journal.record_approach(*args, approach) is False


def test_record_approach_rejected_after_cancel(running):
    execution, clock, _, _, _ = running
    execution.interrupt()
    with pytest.raises(ValueError):
        execution.journal.record_approach(
            execution.run_id,
            execution.thread_id,
            execution.operation_id,
            clock[0],
            _generated_approach(execution.run_id),
        )


def test_record_approach_rejected_when_projection_already_ready(running):
    execution, clock, _, _, _ = running
    # Saving a plan persists a model_plan projection; a generated summary must
    # not replace it.
    StandardResearchLoop(execution, Planner()).advance(Gateway(), max_steps=1)
    written = execution.journal.record_approach(
        execution.run_id,
        execution.thread_id,
        execution.operation_id,
        clock[0],
        _generated_approach(execution.run_id),
    )
    assert written is False


def test_standard_binding_costs_zero_calls_when_projection_ready(running):
    from src.web.research.approach_generation import (
        ApproachGenerationCoordinator,
        standard_execution_bindings,
    )

    execution, clock, _, runs, _ = running
    StandardResearchLoop(execution, Planner()).advance(Gateway(), max_steps=1)
    authorize, write = standard_execution_bindings(
        execution, clock=lambda: clock[0], model_call_ceiling=2
    )
    # Identity mismatch is refused before any journal work.
    assert authorize("other-run", execution.operation_id) is False
    assert write("other-run", _generated_approach(execution.run_id)) is False
    calls = {"completion": 0}

    def completion(messages, **kwargs):  # noqa: ANN001
        calls["completion"] += 1
        return "{}"

    coordinator = ApproachGenerationCoordinator(
        authorize=authorize, write=write, completion=completion
    )
    current = runs.get(execution.run_id).research_context["approach"]
    outcome = coordinator.attempt(
        run_id=execution.run_id,
        operation_id=execution.operation_id,
        mode="standard",
        query="q",
        current=current,
        is_terminal=lambda: False,
    )
    assert outcome.reason == "not_needed"
    assert calls["completion"] == 0


def test_standard_loop_schedules_off_path_without_extra_calls(running):
    from src.web.research.approach_generation import (
        ApproachGenerationCoordinator,
        ApproachTaskScheduler,
        standard_execution_bindings,
    )

    execution, clock, _, _, _ = running
    calls = {"completion": 0}

    def completion(messages, **kwargs):  # noqa: ANN001
        calls["completion"] += 1
        return "{}"

    authorize, write = standard_execution_bindings(
        execution, clock=lambda: clock[0], model_call_ceiling=2
    )
    coordinator = ApproachGenerationCoordinator(
        authorize=authorize, write=write, completion=completion
    )
    scheduler = ApproachTaskScheduler(coordinator=coordinator, enabled=True)
    try:
        loop = StandardResearchLoop(execution, Planner(), approach_scheduler=scheduler)
        assert loop.advance(Gateway(), max_steps=1) is None  # paused, never blocked
    finally:
        scheduler.shutdown(wait=True)
    # A plan projection already exists, so the off-path task makes zero calls.
    assert calls["completion"] == 0


def test_record_approach_rejected_after_lease_expiry(running):
    execution, clock, _, _, _ = running
    clock[0] += timedelta(seconds=16)  # past the 15s lease
    with pytest.raises(ValueError):
        execution.journal.record_approach(
            execution.run_id,
            execution.thread_id,
            execution.operation_id,
            clock[0],
            _generated_approach(execution.run_id),
        )


def test_restart_does_not_double_charge_approach_budget(running):
    from src.application.standard_execution import StandardExecution
    from src.repositories.runtime_repository import RuntimeRepository

    execution, clock, repository, _, parent = running
    StandardResearchLoop(execution, Planner()).advance(Gateway(), max_steps=1)
    args = (execution.run_id, execution.thread_id, execution.operation_id, clock[0])
    assert execution.journal.authorize_approach_attempt(*args, model_call_ceiling=2) is True
    # A restart reconstructs the service with no in-memory counter surviving; the
    # previous lease must first expire, as it would after a real process restart.
    clock[0] += timedelta(seconds=16)
    after = StandardExecution.resume(
        RuntimeRepository(repository.database),
        run_id=execution.run_id,
        thread_id=parent.thread_id,
        clock=lambda: clock[0],
    )
    assert (
        after.journal.authorize_approach_attempt(
            after.run_id,
            after.thread_id,
            after.operation_id,
            clock[0],
            model_call_ceiling=2,
        )
        is False
    )


def test_slow_generation_does_not_block_research_and_late_write_is_rejected(running):
    from src.web.research.approach_generation import ApproachGenerationCoordinator

    execution, clock, _, runs, _ = running
    started = threading.Event()
    release = threading.Event()
    outcome_box: dict = {}

    def completion(messages, **kwargs):  # noqa: ANN001
        started.set()
        release.wait(5.0)
        return json.dumps(
            {"summary": "我会先核对发布日期。", "focus": ["发布日期"]}, ensure_ascii=False
        )

    def write(run_id, approach):
        return execution.journal.record_approach(
            execution.run_id,
            execution.thread_id,
            execution.operation_id,
            clock[0],
            approach,
        )

    coordinator = ApproachGenerationCoordinator(
        authorize=lambda run_id, operation_id: True,
        write=write,
        completion=completion,
    )

    def run_generation() -> None:
        outcome_box["r"] = coordinator.attempt(
            run_id=execution.run_id,
            operation_id=execution.operation_id,
            mode="standard",
            query="q",
            current=None,
            is_terminal=lambda: False,
        )

    thread = threading.Thread(target=run_generation)
    thread.start()
    assert started.wait(5.0)  # the model is in flight

    # Research must continue while the model is slow (barrier-ordered, no sleep).
    result = StandardResearchLoop(execution, Planner()).advance(Gateway())
    assert result is not None

    release.set()
    thread.join(5.0)
    outcome = outcome_box["r"]
    assert outcome.written is False  # the plan projection won
    assert (
        runs.get(execution.run_id).research_context["approach"]["origin"] == "model_plan"
    )


def test_resume_uses_saved_plan_and_next_action_without_model_reentry(running):
    execution, _, _, _, _ = running
    planner, gateway = Planner(), Gateway()
    assert (
        StandardResearchLoop(execution, planner).advance(gateway, max_steps=1) is None
    )
    saved = snapshot(running)
    assert saved["research"]["next_cursor"] == 1 and not gateway.events
    execution.interrupt()
    after = resume(running)

    def no_replan(_request):
        pytest.fail("resume must not call the model again")

    result = StandardResearchLoop(after, no_replan).advance(gateway)
    assert result["budget_consumed"]["planner_calls"] == len(planner.requests) == 1
    assert [kind for kind, _ in gateway.events] == ["search", "read"]
    assert result["plan"] == saved["research"]["plan"]


def test_crash_after_read_before_observation_replays_saved_outcome(running):
    execution, clock, _, _, _ = running
    planner, gateway = Planner(), Gateway()
    assert (
        StandardResearchLoop(execution, planner).advance(gateway, max_steps=2) is None
    )
    step = execution.journal.claim_research_step(
        execution.run_id, execution.thread_id, execution.operation_id, clock[0]
    )
    execution.read(gateway, step["target"])
    # Simulate losing the loop before observation/cursor persistence.
    execution.interrupt()
    result = StandardResearchLoop(
        resume(running), lambda _: pytest.fail("no replan")
    ).advance(gateway)
    assert len([event for event in gateway.events if event[0] == "read"]) == 1
    assert result["budget_consumed"]["new_reads"] == 1
    assert len(result["acquired_sources"]) == 1
    assert result["publication_authority"] is False


def test_crash_after_search_before_observation_recovers_discovery_queue(running):
    execution, clock, _, _, _ = running
    gateway = Gateway()
    StandardResearchLoop(execution, Planner()).advance(gateway, max_steps=1)
    step = execution.journal.claim_research_step(
        execution.run_id, execution.thread_id, execution.operation_id, clock[0]
    )
    execution.search(gateway, step["target"])
    execution.interrupt()
    result = StandardResearchLoop(
        resume(running), lambda _: pytest.fail("no replan")
    ).advance(gateway)
    assert [kind for kind, _ in gateway.events] == ["search", "read"]
    assert result["budget_consumed"]["new_queries"] == 1


def test_crash_in_planning_is_unknown_and_never_replanned(running):
    execution, clock, _, _, _ = running
    execution.journal.begin_research_plan(
        execution.run_id, execution.thread_id, execution.operation_id, clock[0]
    )
    execution.interrupt()
    result = StandardResearchLoop(
        resume(running), lambda _: pytest.fail("must not resend planning")
    ).advance(Gateway())
    assert result["stop_reason"] == "result_unknown"
    assert result["plan"] is None and result["budget_consumed"]["planner_calls"] == 1


def test_crash_in_dispatch_stops_with_unknown_without_resend(running):
    execution, clock, _, _, _ = running
    gateway = Gateway()
    StandardResearchLoop(execution, Planner()).advance(gateway, max_steps=1)
    step = execution.journal.claim_research_step(
        execution.run_id, execution.thread_id, execution.operation_id, clock[0]
    )
    execution.journal.reserve(
        execution.run_id,
        execution.thread_id,
        execution.operation_id,
        step["kind"],
        step["target"],
        clock[0],
    )
    clock[0] += timedelta(seconds=16)
    result = StandardResearchLoop(
        resume(running), lambda _: pytest.fail("no replan")
    ).advance(gateway)
    assert result["stop_reason"] == "result_unknown" and not gateway.events
    assert result["budget_consumed"]["new_queries"] == 1


@pytest.mark.parametrize(
    "fault",
    [
        "query",
        "hash",
        "gap",
        "omit",
        "duplicate",
        "answer",
        "support",
        "url",
        "queries",
    ],
)
def test_planner_cannot_expand_identity_fields_or_publication_authority(running, fault):
    planner, gateway = Planner(), Gateway()

    def invalid(request):
        plan = planner(request)
        if fault == "query":
            plan["query"] = "unrelated question"
        elif fault == "hash":
            plan["handoff_sha256"] = "forged"
        elif fault == "gap":
            plan["gaps"][0]["field"] = "invented_fact"
        elif fault == "omit":
            plan["gaps"] = []
        elif fault == "duplicate":
            plan["gaps"] *= 2
        elif fault == "answer":
            plan["answer"] = "The release date is known"
        elif fault == "support":
            plan["gaps"][0]["supported"] = True
        elif fault == "url":
            plan["gaps"][0]["candidate_urls"] = ["https://example.com/invented"]
        else:
            plan["gaps"][0]["queries"] *= 5
        return plan

    result = StandardResearchLoop(running[0], invalid).advance(gateway)
    assert result["stop_reason"] == "planner_invalid" and not gateway.events
    assert result["plan"] is None and result["publication_authority"] is False
    assert (
        result["budget_consumed"]["new_reads"]
        == result["budget_consumed"]["new_queries"]
        == 0
    )


def test_model_request_mutation_cannot_reset_ledger_budget(running):
    planner = Planner()

    def mutate(request):
        request["budget"]["new_reads"] = -100
        return planner(request)

    result = StandardResearchLoop(running[0], mutate).advance(Gateway())
    assert result["budget_consumed"] == {
        "new_reads": 1,
        "new_queries": 1,
        "planner_calls": 1,
    }


def test_new_reads_stop_at_existing_ledger_budget(running):
    gateway = Gateway(count=8)
    result = StandardResearchLoop(running[0], Planner()).advance(gateway)
    assert result["stop_reason"] == "budget_exhausted"
    assert result["budget_consumed"]["new_reads"] == 5
    assert len([event for event in gateway.events if event[0] == "read"]) == 5


@pytest.mark.parametrize("mode", ["cancel", "deadline"])
def test_stop_preserves_diagnostic_artifact_without_new_work(running, mode):
    execution, clock, _, runs, _ = running
    planner, gateway = Planner(), Gateway()
    StandardResearchLoop(execution, planner).advance(gateway, max_steps=1)
    if mode == "cancel":
        runs.request_cancel(execution.run_id)
    else:
        clock[0] += timedelta(seconds=60)
    result = StandardResearchLoop(execution, planner).advance(gateway)
    assert result["stop_reason"] == ("cancelled" if mode == "cancel" else "deadline")
    assert not gateway.events and len(planner.requests) == 1
    assert result["publication_authority"] is False
    assert snapshot(running)["research"]["result"] == result


def test_expiry_before_planning_does_not_call_or_charge_model(running):
    execution, clock, _, _, _ = running
    clock[0] += timedelta(seconds=60)
    result = StandardResearchLoop(
        execution, lambda _: pytest.fail("no model after deadline")
    ).advance(Gateway())
    assert (
        result["stop_reason"] == "deadline"
        and result["budget_consumed"]["planner_calls"] == 0
    )


def test_takeover_rejects_old_loop_completion(running):
    execution, clock, _, _, _ = running
    StandardResearchLoop(execution, Planner()).advance(Gateway(), max_steps=1)
    clock[0] += timedelta(seconds=16)
    resume(running)
    with pytest.raises(ValueError, match="stale operation"):
        StandardResearchLoop(execution, Planner()).advance(Gateway())


def test_completed_loop_is_replayed_without_additional_work(running):
    planner, gateway = Planner(), Gateway()
    result = StandardResearchLoop(running[0], planner).advance(gateway)
    events = list(gateway.events)
    after = resume(running)
    repeated = StandardResearchLoop(after, lambda _: pytest.fail("no replan")).advance(
        gateway
    )
    assert repeated == result and gateway.events == events


def test_failed_read_is_an_observation_not_claim_support(running):
    result = StandardResearchLoop(running[0], Planner()).advance(
        Gateway(fail_reads=True)
    )
    assert result["budget_consumed"]["new_reads"] == 1
    assert any(row["outcome"] == "failed" for row in result["read_outcomes"])
    assert (
        result["unresolved_gaps"] == ["release_date"]
        and result["publication_authority"] is False
    )


def test_planning_and_steps_have_single_inflight_owner(running):
    execution, clock, _, _, _ = running
    args = (execution.run_id, execution.thread_id, execution.operation_id, clock[0])
    request = execution.journal.begin_research_plan(*args)
    with pytest.raises(StandardResearchBusy):
        execution.journal.begin_research_plan(*args)
    execution.journal.save_research_plan(*args, Planner()(request))
    execution.journal.claim_research_step(*args)
    with pytest.raises(StandardResearchBusy):
        execution.journal.claim_research_step(*args)


def test_tampered_saved_plan_fails_closed(running):
    execution, _, repository, _, _ = running
    StandardResearchLoop(execution, Planner()).advance(Gateway(), max_steps=1)
    execution.interrupt()
    run = snapshot(running)
    run["research"]["plan"]["gaps"][0]["queries"] = ["tampered query"]
    with repository.database.connect() as connection:
        raw = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (execution.run_id,),
        ).fetchone()
        context = json.loads(raw["research_context"])
        context["standard"] = run
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), execution.run_id),
        )
    with pytest.raises(ValueError, match="digest"):
        StandardResearchLoop(resume(running), Planner()).advance(Gateway())


def test_discovery_filters_private_and_blocked_urls_and_prefers_official_host():
    rows = [
        {"url": "https://third-party.example/tutorial"},
        {"url": "http://127.0.0.1/private"},
        {"url": "https://www.python.org/alternate"},
        {"url": "https://[bad"},
        {"url": "https://example.com/blocked", "policy_allowed": False},
    ]
    assert search_urls({"status": "ok", "results": rows}, "Python 3.14 发布日期") == [
        "https://www.python.org/alternate",
        "https://third-party.example/tutorial",
    ]


def test_model_adapter_uses_one_bounded_json_call(running):
    captured = []

    def complete(messages, **kwargs):
        captured.append(kwargs)
        return json.dumps(Planner()(json.loads(messages[-1]["content"])))

    result = StandardResearchLoop(running[0], ModelStandardPlanner(complete)).advance(
        Gateway()
    )
    assert len(captured) == 1 and captured[0]["request_max_retries"] == 0
    assert captured[0]["timeout"] == 8 and result["publication_authority"] is False


def test_fresh_process_uses_saved_plan_without_replanning(running):
    import subprocess
    import sys

    execution, clock, repository, _, _ = running
    StandardResearchLoop(execution, Planner(queries=[])).advance(Gateway(), max_steps=0)
    execution.interrupt()
    script = """
import sys
from datetime import datetime
from src.application.standard_execution import StandardExecution
from src.application.standard_research import StandardResearchLoop
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository
def no_model(_): raise AssertionError('unexpected replan')
execution = StandardExecution.resume(RuntimeRepository(RuntimeDatabase(sys.argv[1])),
    run_id=sys.argv[2], thread_id=sys.argv[3], clock=lambda: datetime.fromisoformat(sys.argv[4]))
result = StandardResearchLoop(execution, no_model).advance(object())
assert result['publication_authority'] is False
assert result['unresolved_gaps'] == ['release_date']
assert result['budget_consumed']['new_reads'] == 0
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(repository.database.path),
            execution.run_id,
            execution.thread_id,
            clock[0].isoformat(),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_reservation_and_plan_are_durable_before_model_or_network(running):
    def planner(request):
        research = snapshot(running)["research"]
        assert research["status"] == "planning" and research["planner_calls"] == 1
        return Planner()(request)

    class CheckedGateway(Gateway):
        def search_exact(self, *args, **kwargs):
            assert snapshot(running)["research"]["plan"]["schema"] == PLAN_SCHEMA
            return super().search_exact(*args, **kwargs)

        def read(self, *args, **kwargs):
            assert snapshot(running)["research"]["status"] == "planned"
            return super().read(*args, **kwargs)

    result = StandardResearchLoop(running[0], planner).advance(CheckedGateway())
    assert result["publication_authority"] is False


def test_cancelled_planner_late_result_cannot_save_plan(running):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    execution, _, _, runs, _ = running
    entered, release = Event(), Event()

    def blocked(request):
        entered.set()
        release.wait(2)
        return Planner()(request)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                StandardResearchLoop(execution, blocked).advance, Gateway()
            )
            assert entered.wait(2)
            runs.request_cancel(execution.run_id)
            result = future.result(timeout=2)
    finally:
        release.set()
    assert result["stop_reason"] == "cancelled" and result["plan"] is None
    assert snapshot(running)["research"]["plan"] is None
    assert result["budget_consumed"]["planner_calls"] == 1


@pytest.mark.parametrize("fault", ["query", "url", "field", "kind"])
def test_tampered_action_never_dispatches(running, fault):
    from src.repositories.standard_execution_repository import work_key

    execution, _, repository, _, _ = running
    StandardResearchLoop(execution, Planner()).advance(Gateway(), max_steps=1)
    execution.interrupt()
    with repository.database.connect() as connection:
        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (execution.run_id,),
        ).fetchone()
        context = json.loads(row["research_context"])
        step = context["standard"]["research"]["actions"][1]
        if fault == "query":
            step["target"] = "foreign query"
        elif fault == "url":
            step.update(kind="read", target="http://127.0.0.1/private")
        elif fault == "field":
            step["fields"] = ["invented_claim"]
        else:
            step["kind"] = "publish"
        step["id"] = work_key(step["kind"], step["target"])
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), execution.run_id),
        )
    gateway = Gateway()
    result = StandardResearchLoop(resume(running), Planner()).advance(gateway)
    assert not gateway.events and result["stop_reason"] == "result_unknown"
    assert result["publication_authority"] is False


def test_unknown_loop_schema_is_rejected(running):
    execution, _, repository, _, _ = running
    StandardResearchLoop(execution, Planner()).advance(Gateway(), max_steps=0)
    execution.interrupt()
    with repository.database.connect() as connection:
        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (execution.run_id,),
        ).fetchone()
        context = json.loads(row["research_context"])
        context["standard"]["research"]["schema"] = "future-loop"
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), execution.run_id),
        )
    with pytest.raises(ValueError, match="schema"):
        StandardResearchLoop(resume(running), Planner()).advance(Gateway())
