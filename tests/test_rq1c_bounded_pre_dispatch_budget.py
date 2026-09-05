from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import tools.run_rq1c_bounded_qualification as runner


def test_answer_pipeline_capacity_rejects_before_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(runner, "_production_chat", lambda *args, **kwargs: calls.append((args, kwargs)))
    budget = runner._AnswerStageBudget(
        started_at=time.monotonic(),
        research_model_calls=5,
        required_answer_calls=2,
    )

    with pytest.raises(
        runner.QualificationModelBudgetExhausted,
        match="answer_pipeline_model_call_capacity_exhausted",
    ):
        budget.chat([], task_name="single_chat", timeout=10.0)

    assert calls == []
    assert budget.answer_calls_started == 0
    assert budget.total_model_calls_started == 5


def test_sixth_call_may_dispatch_but_seventh_is_rejected_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_chat(messages: list[dict], **kwargs: object) -> str:
        calls.append(dict(kwargs))
        return "ok"

    monkeypatch.setattr(runner, "_production_chat", fake_chat)
    budget = runner._AnswerStageBudget(
        started_at=time.monotonic(),
        research_model_calls=5,
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
    assert budget.total_model_calls_started == 6


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
