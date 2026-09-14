from __future__ import annotations

import time
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

import tools.run_rq1c_bounded_qualification as runner


def test_answer_pipeline_capacity_rejects_before_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(runner, "_production_chat", lambda *args, **kwargs: calls.append((args, kwargs)))
    budget = runner._AnswerStageBudget(
        started_at=time.monotonic(),
        research_model_calls=7,
        required_answer_calls=2,
    )

    with pytest.raises(
        runner.QualificationModelBudgetExhausted,
        match="answer_pipeline_model_call_capacity_exhausted",
    ):
        budget.chat([], task_name="single_chat", timeout=10.0)

    assert calls == []
    assert budget.answer_calls_started == 0
    assert budget.total_model_calls_started == 7


def test_eighth_call_may_dispatch_but_ninth_is_rejected_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_chat(messages: list[dict], **kwargs: object) -> str:
        calls.append(dict(kwargs))
        return "ok"

    monkeypatch.setattr(runner, "_production_chat", fake_chat)
    budget = runner._AnswerStageBudget(
        started_at=time.monotonic(),
        research_model_calls=7,
        required_answer_calls=1,
    )

    assert budget.chat([], task_name="single_chat", timeout=10.0) == "ok"
    with pytest.raises(
        runner.QualificationModelBudgetExhausted,
        match="model_call_budget_exhausted_pre_call",
    ):
        budget.chat([], task_name="answer_claim_binding", timeout=10.0)

    assert len(calls) == 1
    assert budget.phase_calls["answer_generation"] == 1
    assert budget.phase_calls["answer_claim_binding"] == 0
    assert budget.total_model_calls_started == 8



def test_six_research_calls_leave_capacity_for_generation_and_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_chat(messages: list[dict], **kwargs: object) -> str:
        calls.append(str(kwargs.get("task_name") or ""))
        return "ok"

    monkeypatch.setattr(runner, "_production_chat", fake_chat)
    budget = runner._AnswerStageBudget(
        started_at=time.monotonic(),
        research_model_calls=6,
        required_answer_calls=2,
    )

    assert budget.chat([], task_name="single_chat", timeout=10.0) == "ok"
    assert budget.chat([], task_name="answer_claim_binding", timeout=10.0) == "ok"
    assert calls == ["single_chat", "answer_claim_binding"]
    assert budget.total_model_calls_started == 8


def test_hosted_answer_allowance_can_raise_provider_timeout_without_changing_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[float] = []

    def fake_chat(messages: list[dict], **kwargs: object) -> str:
        seen.append(float(kwargs["timeout"]))
        return "ok"

    monkeypatch.setattr(runner, "_production_chat", fake_chat)
    budget = runner._AnswerStageBudget(
        started_at=time.monotonic(),
        hard_timeout_seconds=540.0,
        answer_timeout_floor_seconds=120.0,
    )

    assert budget.chat([], task_name="single_chat", timeout=7.0) == "ok"
    assert seen == [120.0]

def test_expired_case_deadline_rejects_before_network(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(runner, "_production_chat", lambda *args, **kwargs: calls.append((args, kwargs)))
    budget = runner._AnswerStageBudget(
        started_at=time.monotonic() - 61.0,
        research_model_calls=0,
    )

    with pytest.raises(
        runner.QualificationHardDeadlineReached,
        match="hard_timeout_exhausted_pre_call",
    ):
        budget.chat([], task_name="single_chat", timeout=10.0)

    assert calls == []
    assert budget.answer_calls_started == 0


def test_provider_timeout_is_clamped_to_remaining_case_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[float] = []

    def fake_chat(messages: list[dict], **kwargs: object) -> str:
        seen.append(float(kwargs["timeout"]))
        return "ok"

    monkeypatch.setattr(runner, "_production_chat", fake_chat)
    budget = runner._AnswerStageBudget(
        started_at=time.monotonic() - 55.0,
        research_model_calls=0,
        required_answer_calls=1,
    )

    assert budget.chat([], task_name="single_chat", timeout=30.0) == "ok"
    assert len(seen) == 1
    assert 0.0 < seen[0] <= 5.1
    assert seen[0] < 30.0


def test_provider_timeout_never_increases_normal_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[float] = []

    def fake_chat(messages: list[dict], **kwargs: object) -> str:
        seen.append(float(kwargs["timeout"]))
        return "ok"

    monkeypatch.setattr(runner, "_production_chat", fake_chat)
    budget = runner._AnswerStageBudget(
        started_at=time.monotonic(),
        research_model_calls=0,
        required_answer_calls=1,
    )

    assert budget.chat([], task_name="single_chat", timeout=7.0) == "ok"
    assert seen == [7.0]


def test_research_truth_reserves_binder_capacity_only_when_binding_rows_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = SimpleNamespace(
        research_context={"claim_engine_runtime": {"model_calls": [{}, {}, {}, {}]}}
    )
    budget = runner._AnswerStageBudget(started_at=time.monotonic())

    monkeypatch.setattr(runner._impl, "research_binding_rows", lambda run: [])
    budget.set_research_truth(completed)
    assert budget.research_model_calls == 4
    assert budget.required_answer_calls == 1

    monkeypatch.setattr(
        runner._impl,
        "research_binding_rows",
        lambda run: [{"claim_id": "c1", "evidence_id": "e1"}],
    )
    budget.set_research_truth(completed)
    assert budget.required_answer_calls == 2


def test_answer_phase_seconds_are_recorded_per_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finalization breakdown: generation and binding are priced separately."""

    def fake_chat(messages: list[dict], **kwargs: object) -> str:
        time.sleep(0.05)
        return "ok"

    monkeypatch.setattr(runner, "_production_chat", fake_chat)
    budget = runner._AnswerStageBudget(started_at=time.monotonic())

    budget.chat([], task_name="single_chat", timeout=10.0)
    budget.chat([], task_name="answer_claim_binding", timeout=10.0)

    assert budget.phase_calls["answer_generation"] == 1
    assert budget.phase_calls["answer_claim_binding"] == 1
    assert budget.phase_seconds["answer_generation"] >= 0.02
    assert budget.phase_seconds["answer_claim_binding"] >= 0.02
    assert [item["phase"] for item in budget.call_records] == [
        "answer_generation",
        "answer_claim_binding",
    ]
    assert all(item["outcome"] == "ok" for item in budget.call_records)


def test_answer_phase_seconds_record_failures_without_leaking_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_chat(messages: list[dict], **kwargs: object) -> str:
        raise TimeoutError("provider detail that must not be stored")

    monkeypatch.setattr(runner, "_production_chat", failing_chat)
    budget = runner._AnswerStageBudget(started_at=time.monotonic())

    with pytest.raises(TimeoutError):
        budget.chat([], task_name="single_chat", timeout=10.0)

    assert budget.phase_seconds["answer_generation"] >= 0.0
    assert budget.call_records == [
        {"phase": "answer_generation", "elapsed_seconds": budget.call_records[0]["elapsed_seconds"], "outcome": "TimeoutError"}
    ]


def test_guarded_run_case_attaches_finalization_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guardrails = runner._impl._core  # same module object as the guardrails module

    def fake_chat(messages: list[dict], **kwargs: object) -> str:
        time.sleep(0.05)
        return "ok"

    def raw_run_case(**kwargs: object) -> dict:
        service = kwargs["service"]
        service.execute("run")
        chat_service = kwargs["chat_service"]
        chat_service.dependencies.chat([], task_name="single_chat")
        return {
            "case_id": "case-x",
            "budget_observed": {},
            "budget_contract_violations": [],
            "answer": {},
            "finalization_breakdown": {
                "research_seconds": 1.0,
                "post_research_projection_seconds": 0.1,
                "answer_stage_seconds": 0.5,
                "total_seconds": 1.6,
            },
        }

    monkeypatch.setattr(runner, "_production_chat", fake_chat)

    @dataclass
    class FakeDependencies:
        chat: object = None

    @dataclass
    class FakeChatService:
        dependencies: FakeDependencies = field(default_factory=FakeDependencies)

    guarded = guardrails.make_guarded_run_case(
        raw_run_case=raw_run_case,
        build_chat_service=lambda database: FakeChatService(),
        binding_rows_provider=lambda run: [],
        answer_stage_model_calls=lambda value: None,
        exact_git_check=lambda: "a" * 40,
    )

    record = guarded(
        case={"id": "case-x", "category": "synthetic", "question": "q"},
        repository=SimpleNamespace(get=lambda run_id: None),
        service=SimpleNamespace(execute=lambda *args, **kwargs: None),
        chat_service=SimpleNamespace(
            repository=SimpleNamespace(database=None)
        ),
        reference_date="2026-09-14",
    )

    breakdown = record["finalization_breakdown"]
    assert breakdown["research_seconds"] >= 0.0
    assert breakdown["answer_generation_seconds"] >= 0.02
    assert breakdown["answer_claim_binding_seconds"] == 0.0
    assert breakdown["answer_stage_call_count"] == 1
    assert breakdown["finalization_seconds"] == round(
        record["elapsed_seconds"] - breakdown["research_seconds"], 3
    )
    assert breakdown["answer_stage_tokens"] is None
