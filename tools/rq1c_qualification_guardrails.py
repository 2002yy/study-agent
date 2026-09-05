"""Import-order-independent guardrails for the RQ1-C qualification callable API."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from src.llm_client import _resolve_timeout, chat as _production_chat

MAX_MODEL_CALLS = 6
HARD_TIMEOUT_SECONDS = 60.0


def _empty_binding_rows_provider(_run: Any) -> tuple[Any, ...]:
    return ()


_default_binding_rows_provider: Callable[[Any], Any] = _empty_binding_rows_provider


class QualificationModelBudgetExhausted(RuntimeError):
    """Raised before dispatch when the six-call case budget is exhausted."""


class QualificationHardDeadlineReached(TimeoutError):
    """Raised before dispatch when no case-level wall-clock budget remains."""


def configure_default_binding_rows_provider(provider: Callable[[Any], Any]) -> None:
    """Set the compatibility provider used by manually constructed test budgets."""

    global _default_binding_rows_provider
    _default_binding_rows_provider = provider


def _bounded_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _optional_nonnegative_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0 or parsed != parsed:
        return None
    return round(parsed, 6)


def _planner_observability(run: Any) -> dict[str, Any]:
    """Project planner attempt truth without prompts, responses, or provider detail."""

    context = getattr(run, "research_context", None)
    context = context if isinstance(context, Mapping) else {}
    runtime = context.get("claim_engine_runtime")
    runtime = runtime if isinstance(runtime, Mapping) else {}
    model_calls = runtime.get("model_calls")
    attempts: list[dict[str, Any]] = []
    if isinstance(model_calls, list):
        for raw in model_calls:
            if not isinstance(raw, Mapping):
                continue
            if str(raw.get("purpose") or "") != "research_claim_planning":
                continue
            attempts.append(
                {
                    "attempt": _optional_nonnegative_int(raw.get("attempt")),
                    "status": _bounded_text(raw.get("status"), 80),
                    "error_type": _bounded_text(raw.get("error_type"), 120),
                    "finish_reason": _bounded_text(raw.get("finish_reason"), 80),
                    "input_tokens": _optional_nonnegative_int(raw.get("input_tokens")),
                    "output_tokens": _optional_nonnegative_int(raw.get("output_tokens")),
                    "total_tokens": _optional_nonnegative_int(raw.get("total_tokens")),
                    "elapsed_seconds": _optional_nonnegative_float(
                        raw.get("elapsed_seconds")
                    ),
                }
            )
    return {
        "attempt_count": len(attempts),
        "attempts": attempts,
        "stores_raw_model_text": False,
    }


@dataclass
class _AnswerStageBudget:
    """One shared physical-call/deadline ledger for a qualification case."""

    started_at: float
    research_model_calls: int = 0
    max_model_calls: int = MAX_MODEL_CALLS
    hard_timeout_seconds: float = HARD_TIMEOUT_SECONDS
    required_answer_calls: int = 1
    phase_calls: dict[str, int] = field(
        default_factory=lambda: {
            "answer_generation": 0,
            "answer_claim_binding": 0,
            "other": 0,
        }
    )
    rejection_reasons: list[str] = field(default_factory=list)
    binding_rows_provider: Callable[[Any], Any] | None = field(
        default=None,
        repr=False,
    )

    @property
    def answer_calls_started(self) -> int:
        return sum(self.phase_calls.values())

    @property
    def total_model_calls_started(self) -> int:
        return max(0, int(self.research_model_calls)) + self.answer_calls_started

    def remaining_seconds(self) -> float:
        elapsed = max(0.0, time.monotonic() - self.started_at)
        return max(0.0, self.hard_timeout_seconds - elapsed)

    def set_research_truth(self, completed: Any) -> None:
        context = getattr(completed, "research_context", None)
        context = context if isinstance(context, Mapping) else {}
        runtime = context.get("claim_engine_runtime")
        runtime = runtime if isinstance(runtime, Mapping) else {}
        model_calls = runtime.get("model_calls")
        self.research_model_calls = (
            len(model_calls) if isinstance(model_calls, list) else 0
        )
        provider = self.binding_rows_provider or _default_binding_rows_provider
        self.required_answer_calls = 1 + int(bool(provider(completed)))

    def _phase_name(self, task_name: Any) -> str:
        name = str(task_name or "").strip()
        if name == "single_chat":
            return "answer_generation"
        if name == "answer_claim_binding":
            return "answer_claim_binding"
        return "other"

    def _reject(self, reason: str, exc_type: type[Exception]) -> None:
        self.rejection_reasons.append(reason)
        raise exc_type(reason)

    def chat(self, messages: list[dict], **kwargs: Any) -> str:
        """Dispatch production chat only after reserving shared case budget."""

        phase = self._phase_name(kwargs.get("task_name"))
        if (
            self.answer_calls_started == 0
            and self.research_model_calls + self.required_answer_calls
            > self.max_model_calls
        ):
            self._reject(
                "answer_pipeline_model_call_capacity_exhausted",
                QualificationModelBudgetExhausted,
            )
        if self.total_model_calls_started >= self.max_model_calls:
            self._reject(
                "model_call_budget_exhausted_pre_call",
                QualificationModelBudgetExhausted,
            )

        remaining = self.remaining_seconds()
        if remaining <= 0:
            self._reject(
                "hard_timeout_exhausted_pre_call",
                QualificationHardDeadlineReached,
            )

        normal_timeout = float(
            _resolve_timeout(
                kwargs.get("timeout"),
                kwargs.get("task_name"),
                kwargs.get("model_profile"),
                kwargs.get("provider_profile"),
            )
        )
        bounded_timeout = min(normal_timeout, remaining)
        if bounded_timeout <= 0:
            self._reject(
                "hard_timeout_exhausted_pre_call",
                QualificationHardDeadlineReached,
            )

        self.phase_calls[phase] = self.phase_calls.get(phase, 0) + 1
        forwarded = dict(kwargs)
        forwarded["timeout"] = bounded_timeout
        return _production_chat(messages, **forwarded)


class _ResearchBudgetProxy:
    """Delegate ResearchRun execution and load its durable call truth."""

    def __init__(self, delegate: Any, budget: _AnswerStageBudget) -> None:
        self._delegate = delegate
        self._budget = budget

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        completed = self._delegate.execute(*args, **kwargs)
        self._budget.set_research_truth(completed)
        return completed


def make_guarded_run_case(
    *,
    raw_run_case: Callable[..., dict[str, Any]],
    build_chat_service: Callable[[Any], Any],
    binding_rows_provider: Callable[[Any], Any],
    answer_stage_model_calls: Callable[[Any], tuple[int, int] | None],
    exact_git_check: Callable[[], str],
) -> Callable[..., dict[str, Any]]:
    """Close the reviewed raw case function inside a non-bypassable guarded API."""

    def guarded_run_case(
        *,
        case: Mapping[str, str],
        repository: Any,
        service: Any,
        chat_service: Any,
        reference_date: str,
    ) -> dict[str, Any]:
        # Exact checkout identity is part of the callable contract, not just CLI setup.
        exact_git_check()
        budget = _AnswerStageBudget(
            started_at=time.monotonic(),
            binding_rows_provider=binding_rows_provider,
        )
        guarded_research = _ResearchBudgetProxy(service, budget)
        bounded_chat = build_chat_service(chat_service.repository.database)
        bounded_chat.dependencies = replace(bounded_chat.dependencies, chat=budget.chat)
        record = raw_run_case(
            case=case,
            repository=repository,
            service=guarded_research,
            chat_service=bounded_chat,
            reference_date=reference_date,
        )

        run_id = f"rq1c_{str(case.get('id') or '').strip()}"
        persisted_run = repository.get(run_id) if run_id != "rq1c_" else None
        record["planner"] = _planner_observability(persisted_run)

        observed = record.get("budget_observed")
        if isinstance(observed, dict):
            observed["research_model_call_count"] = budget.research_model_calls
            observed["answer_generation_model_call_count"] = budget.phase_calls[
                "answer_generation"
            ]
            observed["answer_binding_model_call_count"] = budget.phase_calls[
                "answer_claim_binding"
            ]
            observed["unclassified_answer_model_call_count"] = budget.phase_calls["other"]
            observed["model_call_count"] = budget.total_model_calls_started

        elapsed = round(max(0.0, time.monotonic() - budget.started_at), 3)
        record["elapsed_seconds"] = elapsed
        if isinstance(observed, dict):
            observed["elapsed_seconds"] = elapsed

        violations = record.get("budget_contract_violations")
        if not isinstance(violations, list):
            violations = []
            record["budget_contract_violations"] = violations
        violations[:] = [
            str(item)
            for item in violations
            if item
            not in {
                "answer_stage_model_call_count_unavailable",
                "model_call_budget_exceeded",
            }
        ]
        for reason in budget.rejection_reasons:
            if reason not in violations:
                violations.append(reason)

        if (
            budget.phase_calls["other"] > 0
            and "unclassified_answer_model_call" not in violations
        ):
            violations.append("unclassified_answer_model_call")

        answer = record.get("answer")
        validation = answer.get("validation") if isinstance(answer, Mapping) else None
        audit_counts = answer_stage_model_calls(validation)
        actual_counts = (
            budget.phase_calls["answer_generation"],
            budget.phase_calls["answer_claim_binding"],
        )
        if audit_counts is not None and audit_counts != actual_counts:
            if "answer_stage_call_audit_mismatch" not in violations:
                violations.append("answer_stage_call_audit_mismatch")

        if budget.total_model_calls_started > budget.max_model_calls:
            if "model_call_budget_exceeded" not in violations:
                violations.append("model_call_budget_exceeded")
        if elapsed > budget.hard_timeout_seconds:
            if "hard_timeout_exceeded" not in violations:
                violations.append("hard_timeout_exceeded")
        return record

    return guarded_run_case
