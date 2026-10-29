"""Offline contracts for the four-arm runner.

Nothing here calls a model. An ``ArmExecutor`` is a fake that charges a send and
returns text, which is exactly the seam a live executor would use. The contracts
locked here are the ones a real preview depends on:

* the caps are the ones the preview tool derives - 45 / 20 / 20 / 5 / 4 - not a
  second opinion;
* one send is charged at all three levels, in one reservation;
* an exhausted budget stops the *run*, not just the turn, and no executor is
  called again;
* one arm cannot spend another arm's allowance, and a restart cannot replay
  sends that are already counted;
* the manual arm is recorded but never executed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.application.quality_0_arms import (
    ABORTED,
    COMPLETED,
    FAILED,
    MANUAL,
    NOT_RUN,
    ArmPlanError,
    Quality0ArmRunner,
    arm_specs,
    derive_caps,
    plan_turns,
)
from src.application.send_budget import SendBudget
from src.llm_spend_guard import charge_send, send_budget_scope
from tools.run_quality_0_preview import load_preview, plan

ROOT = Path(__file__).resolve().parents[1]
PREVIEW_PATH = ROOT / "tests" / "fixtures" / "quality_0" / "preview_v1.json"
TASKS_PATH = ROOT / "tests" / "fixtures" / "quality_0" / "tasks_v1.json"


class RecordingExecutor:
    """A fake arm: records the turns it saw, charges, returns text."""

    def __init__(
        self,
        *,
        sends: int = 1,
        attempts: int = 1,
        answer: str = "answer",
        error: Exception | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.sends = sends
        self.attempts = attempts
        self.answer = answer
        self.error = error

    def run_turn(self, turn, send) -> str:
        self.calls.append(f"{turn.arm_id}:{turn.round_index}")
        if self.error is not None:
            raise self.error
        for _ in range(self.sends):
            send(attempts=self.attempts)
        return self.answer


def _arm(arm_id: str, sends: int, execution: str = "api") -> dict:
    return {"id": arm_id, "execution": execution, "sends_per_round": sends}


def _preview(*, arms=None, task_ids=("T-1",)) -> dict:
    if arms is None:
        arms = [_arm("current", 4), _arm("candidate", 4), _arm("model_direct", 1)]
        arms.append(_arm("chatgpt", 0, execution="manual"))
    return {"task_ids": list(task_ids), "arms": arms}


def _tasks(*, follow_up: bool = False) -> dict:
    task = {"id": "T-1", "prompt": "first question"}
    if follow_up:
        task["follow_up"] = "second question"
    return {"tasks": [task]}


def _executors(**overrides) -> dict[str, RecordingExecutor]:
    base = {
        "current": RecordingExecutor(),
        "candidate": RecordingExecutor(),
        "model_direct": RecordingExecutor(),
    }
    base.update(overrides)
    return base


def _runner(tmp_path, *, run_id: str = "preview-1") -> tuple[Quality0ArmRunner, SendBudget]:
    budget = SendBudget(tmp_path / "sends.sqlite")
    return Quality0ArmRunner(budget=budget, run_id=run_id), budget


# -- the caps are the preview's, not the runner's own opinion -------------------


def test_the_caps_are_the_ones_the_preview_plan_derives():
    """A runner with a second cap formula would drift from the approved plan."""

    preview = json.loads(PREVIEW_PATH.read_text(encoding="utf-8"))
    tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    doc = plan(load_preview(PREVIEW_PATH, TASKS_PATH))

    specs = arm_specs(preview)
    turns = plan_turns(preview, tasks)
    caps = derive_caps(specs, turns)

    assert doc["turns_per_arm"] == 5
    assert caps["experiment:quality-0"] == doc["worst_case_model_sends"] == 45
    for arm_id, item in doc["per_arm"].items():
        assert len(turns[arm_id]) == doc["turns_per_arm"]
        if item["execution"] == "api":
            assert caps[f"arm:{arm_id}"] == item["max_sends"]
            assert caps[f"round:{arm_id}:1"] == item["sends_per_round"]
        else:
            assert f"arm:{arm_id}" not in caps
            assert not any(scope.startswith(f"round:{arm_id}:") for scope in caps)


def test_every_arm_sees_the_same_turns():
    preview = json.loads(PREVIEW_PATH.read_text(encoding="utf-8"))
    tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))

    turns = plan_turns(preview, tasks)
    shapes = {
        arm_id: [(turn.round_index, turn.task_id, turn.prompt) for turn in items]
        for arm_id, items in turns.items()
    }

    assert len(set(tuple(value) for value in shapes.values())) == 1
    assert [item[0] for item in shapes["current"]] == [1, 2, 3, 4, 5]


# -- one send, three scopes ------------------------------------------------------


def test_one_send_is_charged_at_every_level(tmp_path):
    preview = _preview(arms=[_arm("current", 4)])
    runner, budget = _runner(tmp_path)

    report = runner.run(
        preview=preview, tasks=_tasks(), executors={"current": RecordingExecutor()}
    )

    assert report.status == COMPLETED
    assert budget.cap("experiment:quality-0") == 4
    assert budget.cap("arm:current") == 4
    assert budget.cap("round:current:1") == 4
    assert budget.usage("experiment:quality-0") == 1
    assert budget.usage("arm:current") == 1
    assert budget.usage("round:current:1") == 1
    assert report.usage_of("experiment:quality-0") == 1


def test_charge_send_without_a_binding_does_nothing():
    """The public entry point keeps the pre-existing opt-in behaviour."""

    charge_send(request_key="unbound")


def test_a_retry_is_charged_as_extra_attempts(tmp_path):
    preview = _preview(arms=[_arm("current", 2)])
    runner, budget = _runner(tmp_path)

    report = runner.run(
        preview=preview,
        tasks=_tasks(),
        executors={"current": RecordingExecutor(attempts=2)},
    )

    assert report.status == COMPLETED
    assert budget.usage("round:current:1") == 2
    assert budget.usage("arm:current") == 2
    assert budget.usage("experiment:quality-0") == 2


# -- a refusal stops the run ------------------------------------------------------


def test_the_round_cap_stops_the_whole_run(tmp_path):
    """The second send in a one-send round aborts everything after it."""

    preview = _preview(arms=[_arm("current", 1), _arm("model_direct", 1)])
    runner, budget = _runner(tmp_path)
    direct = RecordingExecutor()
    executors = {"current": RecordingExecutor(sends=2), "model_direct": direct}

    report = runner.run(
        preview=preview, tasks=_tasks(follow_up=True), executors=executors
    )

    assert report.status == ABORTED
    assert report.abort is not None
    assert report.abort.arm_id == "current"
    assert report.abort.round_index == 1
    assert report.abort.reason == "exhausted"
    assert report.abort.scope == "round:current:1"
    assert executors["current"].calls == ["current:1"]
    assert direct.calls == []
    assert [record.status for record in report.turns] == [
        ABORTED,
        NOT_RUN,
        NOT_RUN,
        NOT_RUN,
    ]
    # The refused send left nothing behind: one attempt, one unit, everywhere.
    assert budget.usage("round:current:1") == 1
    assert budget.usage("arm:current") == 1
    assert budget.usage("arm:model_direct") == 0
    assert budget.usage("experiment:quality-0") == 1


def test_an_exhausted_arm_stops_the_run_without_charging_another_arm(tmp_path):
    """A restart that already spent an arm's allowance must not spend more.

    The arm is pre-charged through the public API, the way a previous process
    would have left it, and the runner is not told: it has to discover the state
    from the budget file.
    """

    preview = _preview(arms=[_arm("current", 4), _arm("candidate", 4)])
    runner, budget = _runner(tmp_path)
    caps = derive_caps(arm_specs(preview), plan_turns(preview, _tasks()))
    budget.register(caps)
    with send_budget_scope(budget, ["experiment:quality-0", "arm:current"]):
        for index in range(4):
            charge_send(request_key=f"earlier-{index}")

    candidate = RecordingExecutor()
    report = runner.run(
        preview=preview,
        tasks=_tasks(),
        executors={"current": RecordingExecutor(), "candidate": candidate},
    )

    assert report.status == ABORTED
    assert report.abort is not None
    assert report.abort.arm_id == "current"
    assert report.abort.reason == "exhausted"
    assert report.abort.scope == "arm:current"
    assert candidate.calls == []
    assert budget.usage("arm:candidate") == 0
    assert budget.usage("experiment:quality-0") == 4


def test_a_restarted_runner_cannot_replay_a_counted_send(tmp_path):
    preview = _preview(arms=[_arm("current", 1)])
    tasks = _tasks()

    first, budget = _runner(tmp_path, run_id="same-run")
    assert first.run(preview=preview, tasks=tasks, executors={"current": RecordingExecutor()}).status == COMPLETED

    rerun = Quality0ArmRunner(budget=SendBudget(tmp_path / "sends.sqlite"), run_id="same-run")
    replay = RecordingExecutor()
    report = rerun.run(preview=preview, tasks=tasks, executors={"current": replay})

    assert report.status == ABORTED
    assert report.abort is not None
    assert report.abort.reason == "conflict"
    assert replay.calls == ["current:1"]
    assert budget.usage("experiment:quality-0") == 1
    assert budget.usage("round:current:1") == 1


# -- the manual arm ---------------------------------------------------------------


def test_the_manual_arm_is_recorded_but_never_charged(tmp_path):
    preview = json.loads(PREVIEW_PATH.read_text(encoding="utf-8"))
    tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    runner, budget = _runner(tmp_path)

    report = runner.run(preview=preview, tasks=tasks, executors=_executors())

    manual = [record for record in report.turns if record.arm_id == "chatgpt"]
    assert len(manual) == 5
    assert {record.status for record in manual} == {MANUAL}
    assert all(record.sends == 0 for record in manual)
    assert "arm:chatgpt" not in report.caps
    assert budget.cap("arm:chatgpt") is None


def test_wiring_an_executor_to_the_manual_arm_is_refused(tmp_path):
    preview = _preview(arms=[_arm("current", 1), _arm("chatgpt", 0, execution="manual")])
    runner, _budget = _runner(tmp_path)

    with pytest.raises(ArmPlanError, match="manual_arm_has_executor"):
        runner.run(
            preview=preview,
            tasks=_tasks(),
            executors={"current": RecordingExecutor(), "chatgpt": RecordingExecutor()},
        )


# -- executor wiring and executor failures ----------------------------------------


def test_a_missing_executor_is_refused_before_anything_is_registered(tmp_path):
    runner, budget = _runner(tmp_path)

    with pytest.raises(ArmPlanError, match="missing_executors"):
        runner.run(
            preview=_preview(),
            tasks=_tasks(),
            executors={"current": RecordingExecutor()},
        )

    assert budget.cap("experiment:quality-0") is None


def test_an_unknown_executor_is_refused(tmp_path):
    runner, _budget = _runner(tmp_path)

    with pytest.raises(ArmPlanError, match="unknown_executors"):
        runner.run(
            preview=_preview(arms=[_arm("current", 1)]),
            tasks=_tasks(),
            executors={"current": RecordingExecutor(), "typo-arm": RecordingExecutor()},
        )


def test_an_executor_failure_is_recorded_and_later_arms_still_run(tmp_path):
    """A model exception is data about that turn; it is not a budget stop."""

    preview = _preview(arms=[_arm("current", 1), _arm("candidate", 1)])
    runner, _budget = _runner(tmp_path)

    report = runner.run(
        preview=preview,
        tasks=_tasks(),
        executors={
            "current": RecordingExecutor(error=RuntimeError("provider exploded")),
            "candidate": RecordingExecutor(),
        },
    )

    assert report.status == "partial"
    assert report.abort is None
    failed = [record for record in report.turns if record.arm_id == "current"][0]
    assert failed.status == FAILED
    assert failed.answer == ""
    assert "provider exploded" in failed.error
    assert [record.status for record in report.turns if record.arm_id == "candidate"] == [
        COMPLETED
    ]


def test_a_completed_turn_without_a_send_is_not_an_answer(tmp_path):
    """An api arm that answered for free would be a fabricated data point."""

    preview = _preview(arms=[_arm("current", 1)])
    runner, _budget = _runner(tmp_path)

    report = runner.run(
        preview=preview,
        tasks=_tasks(),
        executors={"current": RecordingExecutor(sends=0)},
    )

    assert report.status == "partial"
    record = report.turns[0]
    assert record.status == FAILED
    assert record.error == "completed_turn_without_a_send"
    assert record.answer == ""


def test_a_non_string_answer_is_a_failure(tmp_path):
    class Wordless:
        def run_turn(self, turn, send) -> str:
            send()
            return None  # type: ignore[return-value]

    runner, _budget = _runner(tmp_path)

    report = runner.run(
        preview=_preview(arms=[_arm("current", 1)]),
        tasks=_tasks(),
        executors={"current": Wordless()},
    )

    assert report.turns[0].status == FAILED
    assert report.turns[0].error == "non_string_answer"


# -- the preview document itself --------------------------------------------------


@pytest.mark.parametrize(
    ("arms", "message"),
    [
        ([], "preview_arms_empty"),
        ([_arm("current", 1), _arm("current", 1)], "preview_arms_duplicate"),
        ([_arm("chatgpt", 1, execution="manual")], "manual_arm_with_sends"),
        ([_arm("current", 0)], "api_arm_without_sends"),
        ([_arm("current", -1)], "preview_arm_sends_invalid"),
        ([_arm("current", True)], "preview_arm_sends_invalid"),
        ([_arm("current", 1, execution="shell")], "preview_arm_execution_invalid"),
    ],
)
def test_an_invalid_arm_set_is_refused(arms, message):
    with pytest.raises(ArmPlanError, match=message):
        arm_specs({"task_ids": ["T-1"], "arms": arms})


def test_an_unknown_task_is_refused():
    with pytest.raises(ArmPlanError, match="unknown_task"):
        plan_turns(_preview(task_ids=("T-404",)), _tasks())


def test_a_non_string_task_id_is_refused_without_crashing():
    preview = {"task_ids": [{"id": "T-1"}], "arms": [_arm("current", 1)]}

    with pytest.raises(ArmPlanError, match="preview_tasks_invalid"):
        plan_turns(preview, _tasks())
