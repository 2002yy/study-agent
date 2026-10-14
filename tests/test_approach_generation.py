"""Budget-gated research-opening generation — deterministic acceptance tests."""

from __future__ import annotations

import json
import threading
import time

from src.web.research.approach_generation import (
    ApproachGenerationCoordinator,
    GenerationOutcome,
    generation_needed,
    write_allowed,
)
from src.web.research.research_approach import (
    APPROACH_SCHEMA,
    project_from_plan,
    seed_approach,
)


def _pending() -> dict:
    return seed_approach(mode="standard", turn_id="turn_1")


def _coordinator(*, authorize=None, write=None, completion=None):
    return ApproachGenerationCoordinator(
        authorize=authorize or (lambda run_id, operation_id: True),
        write=write or (lambda run_id, approach: True),
        completion=completion,
        timeout=1.0,
    )


def _ok_completion(messages, **kwargs):  # noqa: ANN001
    return json.dumps({"summary": "我会先核对官方说明，再比较自动化接口。", "focus": ["自动化"]}, ensure_ascii=False)


def test_existing_model_plan_costs_zero_calls() -> None:
    current = project_from_plan(mode="standard", summary="我会核对发布日期。", focus=["发布日期"])
    assert generation_needed(current) is False
    calls = {"authorize": 0, "completion": 0}

    def authorize(run_id, operation_id):
        calls["authorize"] += 1
        return True

    def completion(messages, **kwargs):  # noqa: ANN001
        calls["completion"] += 1
        return _ok_completion(messages, **kwargs)

    outcome = _coordinator(authorize=authorize, completion=completion).attempt(
        run_id="r1", operation_id="op1", mode="standard", query="q",
        current=current, is_terminal=lambda: False,
    )
    assert outcome.reason == "not_needed" and outcome.spent is False
    assert calls == {"authorize": 0, "completion": 0}


def test_budget_denied_costs_zero_calls() -> None:
    calls = {"completion": 0}

    def completion(messages, **kwargs):  # noqa: ANN001
        calls["completion"] += 1
        return _ok_completion(messages, **kwargs)

    outcome = _coordinator(authorize=lambda r, o: False, completion=completion).attempt(
        run_id="r1", operation_id="op1", mode="standard", query="q",
        current=_pending(), is_terminal=lambda: False,
    )
    assert outcome.reason == "budget_denied" and outcome.spent is False
    assert calls["completion"] == 0


def test_success_writes_and_spends_once() -> None:
    written = {}
    outcome = _coordinator(
        write=lambda run_id, approach: written.update({"run": run_id, "a": approach}) or True,
        completion=_ok_completion,
    ).attempt(
        run_id="r1", operation_id="op1", mode="standard", query="q",
        current=_pending(), is_terminal=lambda: False,
    )
    assert outcome.spent is True and outcome.written is True
    assert outcome.reason == "written"
    assert written["run"] == "r1"
    assert written["a"]["origin"] == "model_generated"
    assert written["a"]["schema"] == APPROACH_SCHEMA


def test_timeout_records_attempt_and_continues() -> None:
    def completion(messages, **kwargs):  # noqa: ANN001
        raise TimeoutError("provider timeout")

    outcome = _coordinator(completion=completion).attempt(
        run_id="r1", operation_id="op1", mode="deep", query="q",
        current=_pending(), is_terminal=lambda: False,
    )
    # The real attempt is counted even though generation failed.
    assert outcome.spent is True
    assert outcome.approach is not None and outcome.approach["origin"] == "fallback"


def test_cancel_during_generation_does_not_write() -> None:
    state = {"terminal": False}

    def completion(messages, **kwargs):  # noqa: ANN001
        state["terminal"] = True  # cancel lands while we are generating
        return _ok_completion(messages, **kwargs)

    writes = {"n": 0}
    outcome = _coordinator(
        write=lambda run_id, approach: writes.update({"n": writes["n"] + 1}) or True,
        completion=completion,
    ).attempt(
        run_id="r1", operation_id="op1", mode="standard", query="q",
        current=_pending(), is_terminal=lambda: state["terminal"],
    )
    assert outcome.spent is True and outcome.written is False
    assert outcome.reason == "write_rejected"
    assert writes["n"] == 0


def test_newer_direction_is_not_overwritten() -> None:
    from src.web.research.research_approach import direction_update

    updated = direction_update(
        previous=project_from_plan(mode="standard", summary="我会核对发布日期。", focus=["发布日期"]),
        summary="标准研究已经确认了发布日期，我会继续核对许可证。",
    )
    assert generation_needed(updated) is False
    outcome = _coordinator(completion=_ok_completion).attempt(
        run_id="r1", operation_id="op1", mode="standard", query="q",
        current=updated, is_terminal=lambda: False,
    )
    assert outcome.reason == "not_needed" and outcome.spent is False


def test_budget_authorize_error_does_not_propagate() -> None:
    def authorize(run_id, operation_id):
        raise RuntimeError("budget backend down")

    outcome = _coordinator(authorize=authorize, completion=_ok_completion).attempt(
        run_id="r1", operation_id="op1", mode="standard", query="q",
        current=_pending(), is_terminal=lambda: False,
    )
    assert outcome.reason == "budget_error" and outcome.spent is False


def test_write_error_does_not_propagate() -> None:
    def write(run_id, approach):
        raise RuntimeError("db contention")

    outcome = _coordinator(write=write, completion=_ok_completion).attempt(
        run_id="r1", operation_id="op1", mode="standard", query="q",
        current=_pending(), is_terminal=lambda: False,
    )
    assert outcome.spent is True and outcome.written is False
    assert outcome.reason == "write_failed"


def test_concurrent_same_authorization_spends_once() -> None:
    def completion(messages, **kwargs):  # noqa: ANN001
        time.sleep(0.05)
        return _ok_completion(messages, **kwargs)

    coordinator = _coordinator(completion=completion)
    results: list[GenerationOutcome] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        results.append(
            coordinator.attempt(
                run_id="r1", operation_id="op1", mode="standard", query="q",
                current=_pending(), is_terminal=lambda: False,
            )
        )

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 2
    assert sum(1 for r in results if r.spent) == 1
    assert sum(1 for r in results if r.reason == "duplicate_authorization") == 1


def test_write_allowed_rejects_cross_run_and_terminal() -> None:
    current = project_from_plan(
        mode="standard", summary="我会核对发布日期。", focus=["发布日期"], root_run_id="run_A"
    )
    candidate = project_from_plan(
        mode="standard", summary="我会核对许可证。", focus=["许可证"], root_run_id="run_A"
    )
    assert write_allowed(current=current, candidate=candidate, run_id="run_A", terminal=False) is False
    assert write_allowed(current=current, candidate=candidate, run_id="run_A", terminal=True) is False
