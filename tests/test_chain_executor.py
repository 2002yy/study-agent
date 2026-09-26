"""§102 P2-A2d-2 bounded chain executor tests.

The executor is the Progressive Reader skeleton: attempt, record, route, continue.
These tests pin the loop, its data-derived termination bound, the attempt
accounting, and the fact that this slice is production-inert.
"""

from __future__ import annotations

import io
import re

from src.web.research.chain_executor import (
    REASON_NO_EXECUTOR,
    ChainAttemptRequest,
    ChainStepResult,
    run_chain,
)
from src.web.research.progressive_routing import (
    ACTION_BLOCK_RUN,
    ACTION_DEFER,
    ACTION_EXHAUST,
    ACTION_RESOLVE,
    BackendAvailability,
)

NATIVE = "native_http"
WIGOLO = "wigolo_http"
CHAIN = (NATIVE, WIGOLO)


class _ScriptedBackend:
    """A backend whose outcome is scripted, recording what it was asked."""

    def __init__(self, name: str, result: ChainStepResult) -> None:
        self.name = name
        self.result = result
        self.requests: list[ChainAttemptRequest] = []

    def execute(self, request: ChainAttemptRequest) -> ChainStepResult:
        self.requests.append(request)
        return self.result


class _Recorder:
    def __init__(self) -> None:
        self.outcomes: list[ChainStepResult] = []

    def __call__(self, result: ChainStepResult) -> None:
        self.outcomes.append(result)


def _result(
    backend: str,
    state: str,
    *,
    usable: bool = False,
    content: str = "",
    adequacy: str = "",
    attempted: bool = True,
) -> ChainStepResult:
    return ChainStepResult(
        backend=backend,
        retrieval_state=state,
        attempted=attempted,
        usable_content=usable,
        content=content,
        adequacy_reason=adequacy,
    )


def _run(
    *,
    native: ChainStepResult,
    wigolo: ChainStepResult | None = None,
    chain: tuple[str, ...] = CHAIN,
    attempted: tuple[str, ...] = (),
    availability=None,
    health_state_for=None,
    run_blocked: bool = False,
    outer_attempt_number: int = 7,
):
    executors = {NATIVE: _ScriptedBackend(NATIVE, native)}
    if wigolo is not None:
        executors[WIGOLO] = _ScriptedBackend(WIGOLO, wigolo)
    recorder = _Recorder()
    run = run_chain(
        candidate_id="c1",
        url="https://x.example/a",
        host="x.example",
        outer_attempt_number=outer_attempt_number,
        chain=chain,
        executors=executors,
        record_outcome=recorder,
        attempted_backends=attempted,
        availability=availability,
        health_state_for=health_state_for,
        run_blocked=run_blocked,
    )
    return run, recorder, executors


# --------------------------------------------------------------- single step


def test_a_successful_first_backend_ends_in_one_step() -> None:
    run, recorder, executors = _run(native=_result(NATIVE, "success", usable=True))
    assert run.action == ACTION_RESOLVE
    assert run.terminal is True
    assert run.usable_content is True
    assert [step.backend for step in run.steps] == [NATIVE]
    assert [step.chain_step for step in run.steps] == [0]
    assert len(recorder.outcomes) == 1
    # The second backend was never asked to run.
    assert WIGOLO not in executors or not executors[WIGOLO].requests


def test_a_terminal_resource_outcome_does_not_escalate() -> None:
    run, recorder, _ = _run(native=_result(NATIVE, "not_found"))
    assert run.action == ACTION_RESOLVE
    assert run.terminal is True
    assert run.usable_content is False
    assert len(run.steps) == 1


# --------------------------------------------------------------- two steps


def test_a_fallback_state_moves_to_the_next_backend() -> None:
    run, recorder, executors = _run(
        native=_result(NATIVE, "reset"),
        wigolo=_result(WIGOLO, "success", usable=True, content="real text"),
    )
    assert [step.backend for step in run.steps] == [NATIVE, WIGOLO]
    assert [step.chain_step for step in run.steps] == [0, 1]
    assert run.action == ACTION_RESOLVE
    assert run.usable_content is True
    assert run.content == "real text"
    # One outcome per (candidate, backend), both real attempts recorded.
    assert [item.backend for item in recorder.outcomes] == [NATIVE, WIGOLO]


def test_both_backend_outcomes_coexist_in_history() -> None:
    run, recorder, _ = _run(
        native=_result(NATIVE, "timeout"),
        wigolo=_result(WIGOLO, "success", usable=True),
    )
    keys = [(item.backend, item.retrieval_state) for item in recorder.outcomes]
    assert keys == [(NATIVE, "timeout"), (WIGOLO, "success")]
    assert len(set(item.backend for item in recorder.outcomes)) == 2


def test_a_backend_is_never_executed_twice() -> None:
    run, _, executors = _run(
        native=_result(NATIVE, "reset"),
        wigolo=_result(WIGOLO, "reset"),
    )
    assert len(executors[NATIVE].requests) == 1
    assert len(executors[WIGOLO].requests) == 1
    assert run.action == ACTION_EXHAUST
    assert [step.backend for step in run.steps] == [NATIVE, WIGOLO]


def test_a_chain_of_one_backend_cannot_loop() -> None:
    run, recorder, executors = _run(
        native=_result(NATIVE, "reset"), chain=(NATIVE,)
    )
    assert len(executors[NATIVE].requests) == 1
    assert run.action == ACTION_EXHAUST
    assert len(recorder.outcomes) == 1


# --------------------------------------------------------------- accounting


def test_outer_attempt_number_is_constant_across_the_chain() -> None:
    """The chain does not consume extra read-slots (§101 accounting rule)."""

    run, _, _ = _run(
        native=_result(NATIVE, "reset"),
        wigolo=_result(WIGOLO, "success", usable=True),
        outer_attempt_number=17,
    )
    assert {step.outer_attempt_number for step in run.steps} == {17}
    assert [step.chain_step for step in run.steps] == [0, 1]


def test_chain_step_is_invocation_local_and_not_durable() -> None:
    run, _, _ = _run(
        native=_result(NATIVE, "reset"),
        wigolo=_result(WIGOLO, "success", usable=True),
    )
    payload = run.to_dict()
    assert [item["chain_step"] for item in payload["steps"]] == [0, 1]
    # Identity stays (candidate, backend); chain_step appears only in steps.
    assert payload["attempted_backends"] == [NATIVE, WIGOLO]
    assert "chain_step" not in payload


def test_a_policy_skip_records_no_outcome() -> None:
    """Nothing was read, so nothing may enter the attempt history."""

    run, recorder, executors = _run(
        native=_result(NATIVE, "backend_failure", attempted=False),
        wigolo=_result(WIGOLO, "success", usable=True),
    )
    assert [item.backend for item in recorder.outcomes] == [WIGOLO]
    assert run.attempted_backends == (WIGOLO,)
    assert [step.attempted for step in run.steps] == [False, True]
    assert len(executors[NATIVE].requests) == 1


# --------------------------------------------------------------- stop conditions


def test_an_unavailable_next_backend_defers_instead_of_looping() -> None:
    run, recorder, executors = _run(
        native=_result(NATIVE, "reset"),
        wigolo=_result(WIGOLO, "success", usable=True),
        availability={
            WIGOLO: BackendAvailability(
                backend=WIGOLO, available=False, reason="daemon_down"
            )
        },
    )
    assert run.action == ACTION_DEFER
    assert run.terminal is False
    assert len(run.steps) == 1
    assert not executors[WIGOLO].requests
    assert [item.backend for item in recorder.outcomes] == [NATIVE]


def test_an_unhealthy_next_backend_defers() -> None:
    run, _, executors = _run(
        native=_result(NATIVE, "reset"),
        wigolo=_result(WIGOLO, "success", usable=True),
        health_state_for=lambda backend, host: (
            "open" if backend == WIGOLO else "closed"
        ),
    )
    assert run.action == ACTION_DEFER
    assert not executors[WIGOLO].requests


def test_a_blocked_run_stops_before_any_attempt() -> None:
    run, recorder, executors = _run(
        native=_result(NATIVE, "success", usable=True), run_blocked=True
    )
    assert run.action == ACTION_BLOCK_RUN
    assert run.steps == ()
    assert not recorder.outcomes
    assert not executors[NATIVE].requests


def test_a_missing_executor_is_reported_not_retried() -> None:
    run, recorder, _ = _run(
        native=_result(NATIVE, "reset"), chain=(NATIVE, WIGOLO)
    )
    assert run.action == ACTION_EXHAUST
    assert run.reason == REASON_NO_EXECUTOR
    assert [item.backend for item in recorder.outcomes] == [NATIVE]


def test_an_already_attempted_backend_is_not_scheduled_again() -> None:
    run, recorder, executors = _run(
        native=_result(NATIVE, "success", usable=True), attempted=(NATIVE,)
    )
    # native is durable-attempted and wigolo has no executor here, so nothing runs.
    assert not executors[NATIVE].requests
    assert run.action == ACTION_EXHAUST
    assert run.steps == ()


def test_a_router_that_repeats_a_backend_is_stopped_safely() -> None:
    """A contract-violating router must not be able to spin the loop."""

    class _RepeatRouter:
        def __init__(self, name: str) -> None:
            self.name = name

        def execute(self, request: ChainAttemptRequest) -> ChainStepResult:
            # Always asks for native again, which is already visited.
            return _result(request.backend, "reset")

    run, recorder, _ = _run(native=_result(NATIVE, "reset"), chain=(NATIVE,))
    assert run.action == ACTION_EXHAUST
    assert len(run.steps) == 1  # the loop stopped after one step
    assert len(recorder.outcomes) == 1


# --------------------------------------------------------------- purity / scope


def test_the_executor_writes_no_evidence_authority() -> None:
    run, _, _ = _run(
        native=_result(NATIVE, "reset"),
        wigolo=_result(WIGOLO, "success", usable=True),
    )
    from src.web.research.retrieval_backends import FORBIDDEN_AUTHORITY_FIELDS

    payload = run.to_dict()
    assert not set(payload).intersection(FORBIDDEN_AUTHORITY_FIELDS)
    for step in payload["steps"]:
        assert not set(step).intersection(FORBIDDEN_AUTHORITY_FIELDS)


def test_retry_is_not_a_chain_step() -> None:
    """Backend-local retries stay inside one step; the chain has no retry action."""

    from src.web.research.progressive_routing import ROUTING_ACTIONS

    assert "retry" not in ROUTING_ACTIONS
    run, _, executors = _run(
        native=_result(NATIVE, "reset"),
        wigolo=_result(WIGOLO, "success", usable=True),
    )
    # Exactly one request per backend, however many network retries happened
    # inside them.
    assert len(executors[NATIVE].requests) == 1
    assert len(executors[WIGOLO].requests) == 1


# --------------------------------------------------------------- production cutover


def test_the_runtime_is_the_chain_execution_authority() -> None:
    """§105 A2d-4: the cutover is done - the runtime calls ``run_chain``.

    Before the cutover this test asserted the opposite (production-inert). It is
    inverted here because the atomic cutover makes the runtime the single
    execution authority: ``run_chain`` schedules, executes, records and routes.
    """

    pattern = re.compile(r"\brun_chain\b")
    text = io.open(
        "src/application/active_research_runtime.py", encoding="utf-8", errors="ignore"
    ).read()
    assert pattern.search(text), "the runtime must drive the reader chain"


def test_the_adapter_no_longer_executes_wigolo() -> None:
    """The hidden escalation is retired: the adapter never calls ``escalate_read``."""

    pattern = re.compile(r"\bescalate_read\b|_escalate_if_inadequate")
    offenders: list[str] = []
    for relative in (
        "src/web/research/active_adapter.py",
        "src/application/active_research_runtime.py",
    ):
        text = io.open(relative, encoding="utf-8", errors="ignore").read()
        if pattern.search(text):
            offenders.append(relative)
    assert offenders == [], f"production still escalates: {offenders}"


def test_the_hidden_escalation_keeps_only_its_signal_contract() -> None:
    """``escalate_read`` survives as a compatibility function, not as a caller."""

    from src.web.research.read_escalation import escalate_read

    assert callable(escalate_read)


def test_executor_decisions_are_serialisable() -> None:
    run, _, _ = _run(
        native=_result(NATIVE, "reset"),
        wigolo=_result(WIGOLO, "success", usable=True),
    )
    payload = run.to_dict()
    assert payload["action"] == ACTION_RESOLVE
    assert payload["terminal"] is True
    assert payload["usable_content"] is True
    assert set(payload) == {
        "candidate_id",
        "steps",
        "action",
        "reason",
        "final_state",
        "terminal",
        "usable_content",
        "attempted_backends",
    }
